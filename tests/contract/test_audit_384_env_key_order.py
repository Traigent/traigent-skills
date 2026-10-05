"""Keys are written to ``.env`` only after a runnable guard, never typed at a shell
prompt (traigent-skills#384).

Two defect classes in the quickstart docs:

* a filled ``.env`` example with no check that the file is untracked and git-ignored
  before a key goes in — a reader copying only that reference commits the key;
* a key typed at a shell prompt — ``export SOME_API_KEY="..."`` or
  ``echo "SOME_API_KEY=..." >> .env`` — lands in shell history and agent transcripts.

The fix puts one guard block (a fenced ``bash`` block; byte-identical wherever it
appears) before every filled ``.env`` example. It refuses when ``GIT_DIR`` or
``GIT_WORK_TREE`` is set, and decides "inside Git" by looking for a ``.git`` entry from
the current directory up to ``/``: when one exists, Git itself must confirm the work
tree (a missing git or a repository owned by someone else is a refusal, never "outside
Git"). ``.env`` must be absent or a regular file. Inside Git, ``git ls-files
--error-unmatch -- .env`` must exit exactly 1 and ``.env`` must be ignored by the
repository's own rules — ``core.excludesFile=/dev/null`` switches off both a configured
global excludes file and the default ``$XDG_CONFIG_HOME/git/ignore``, while
``.git/info/exclude`` (repository-local) still counts. Outside Git, ``./.gitignore``
must already hold a ``.env`` or ``/.env`` line. Only then does it create ``.env``
(keeping existing content) with mode 0600; every refusal prints ``STOP:`` and creates
nothing.

``violations()`` is a pure function of a file's text so it can run against any
revision. A key typed at a shell prompt is a violation wherever it appears — in a fence
or in inline code in prose: an ``export`` with any secret-named assignment holding a
literal, or an ``echo``/``printf`` that writes ``SECRET=literal`` into ``.env``. In a
non-Python fence, a bare ``SECRET=literal`` line (a ``.env`` body) is a violation when
no earlier fence in the same section (nearest preceding heading) is a guard block.
A blank ``NAME=`` slot, a ``$VAR`` / ``$(...)`` / ``%s`` reference and a value that
reads the environment (``os.environ``, ``os.getenv``) are not key writes.

The guard blocks are also executed in temporary repositories — once in a plain shell
and once with ``set -euo pipefail`` active in the caller — so the test proves what the
guard does, not only that its words are present.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

SCOPED_FILES = (
    "skills/traigent-setup-quickstart/SKILL.md",
    "skills/traigent-setup-quickstart/references/environment-variables.md",
    "skills/traigent-setup-quickstart/references/first-value-fallback.md",
)

SECRET_NAME = r"[A-Z][A-Z0-9_]*(?:API_KEY|SECRET_ACCESS_KEY|SECRET|TOKEN|PASSWORD)"
ASSIGNMENT_RE = re.compile(rf"^(?P<name>{SECRET_NAME})\s*=\s*(?P<value>.*)$")
EXPORT_WORD_RE = re.compile(rf"^(?P<name>{SECRET_NAME})=(?P<value>.*)$", re.S)
TRAILING_COMMENT_RE = re.compile(r"(?:^|\s+)#.*$")
COMMAND_SPLIT_RE = re.compile(r";|&&|\|\|")
ENV_READ_RE = re.compile(r"\bos\.(?:environ|getenv)\b|\bgetenv\s*\(")
PYTHON_INFO = frozenset({"python", "python3", "py", "pycon", "ipython"})

QUOTE_PREFIX = r"(?:[ \t]*>[ \t]?)*"
OPEN_FENCE_RE = re.compile(
    rf"^(?P<quote>{QUOTE_PREFIX})(?P<indent>[ \t]*)(?P<fence>`{{3,}}|~{{3,}})(?P<info>.*)$"
)
HEADING_RE = re.compile(r"^ {0,3}#{1,6}[ \t]+(?P<title>.*?)[ \t#]*$")
INLINE_CODE_RE = re.compile(
    r"(?<!`)(?P<ticks>`+)(?!`)(?P<code>.+?)(?<!`)(?P=ticks)(?!`)"
)

ENV_FILE = r"\.env(?![\w.])"
ECHO_WRITE_RE = re.compile(
    rf"\b(?P<cmd>echo|printf)\b(?P<args>.*?)>>?\s*['\"]?(?:\./)?{ENV_FILE}"
)
ECHO_ASSIGNMENT_RE = re.compile(rf"(?P<name>{SECRET_NAME})=(?P<value>[^\s'\"]*)")
GUARD_COMMANDS = (
    re.compile(rf"git\s+ls-files\s+--error-unmatch\b.*{ENV_FILE}"),
    re.compile(rf"git\s+(?:-c\s+\S+\s+)*check-ignore\b.*{ENV_FILE}"),
    re.compile(rf"\bchmod\s+0?600\b.*{ENV_FILE}"),
)


@dataclass(frozen=True)
class Fence:
    line: int  # 1-based line of the opening fence
    section_line: int  # 1-based line of the nearest preceding heading (0: none)
    section: str
    info: str  # info string after the opening fence, e.g. "bash" or "python title=x"
    body: tuple[tuple[int, str], ...]  # (1-based line, code with prefixes removed)

    @property
    def text(self) -> str:
        return "".join(code + "\n" for _, code in self.body)

    @property
    def language(self) -> str:
        words = self.info.split()
        return words[0].lower() if words else ""


def _strip_quote(line: str, depth: int) -> str:
    for _ in range(depth):
        line = re.sub(r"^[ \t]*>[ \t]?", "", line, count=1)
    return line


def _strip_indent(line: str, width: int) -> str:
    removed = 0
    while removed < width and line[:1] in (" ", "\t"):
        line = line[1:]
        removed += 1
    return line


def _parse(text: str) -> tuple[list[Fence], list[tuple[int, str]]]:
    """(every fenced block, every prose line outside a fence as (line, text))."""
    fences: list[Fence] = []
    prose: list[tuple[int, str]] = []
    lines = text.splitlines()
    section_line, section = 0, ""
    index = 0
    while index < len(lines):
        line = lines[index]
        match = OPEN_FENCE_RE.match(line)
        if match and not (
            match.group("fence").startswith("`") and "`" in match.group("info")
        ):
            depth = match.group("quote").count(">")
            width = len(match.group("indent"))
            marker = match.group("fence")
            close_re = re.compile(
                rf"^[ \t]*{re.escape(marker[0])}{{{len(marker)},}}[ \t]*$"
            )
            opened = index + 1
            body: list[tuple[int, str]] = []
            index += 1
            while index < len(lines):
                inner = _strip_quote(lines[index], depth)
                if close_re.match(inner):
                    break
                body.append((index + 1, _strip_indent(inner, width)))
                index += 1
            info = match.group("info").strip()
            fences.append(Fence(opened, section_line, section, info, tuple(body)))
            index += 1
            continue
        unquoted = re.sub(rf"^{QUOTE_PREFIX}", "", line)
        heading = HEADING_RE.match(unquoted)
        if heading:
            section_line, section = index + 1, heading.group("title")
        else:
            prose.append((index + 1, unquoted))
        index += 1
    return fences, prose


def parse_fences(text: str) -> list[Fence]:
    """Every fenced block, including blockquoted, indented and info-string fences."""
    return _parse(text)[0]


def is_guard(fence: Fence) -> bool:
    lines = [code for _, code in fence.body]
    return all(any(cmd.search(code) for code in lines) for cmd in GUARD_COMMANDS)


def _literal_value(raw: str) -> str:
    value = TRAILING_COMMENT_RE.sub("", raw).strip().strip("\"'").strip()
    if value.startswith(("$", "%")) or ENV_READ_RE.search(value):
        return ""
    return value


def _export_words(command: str) -> list[str]:
    rest = command[len("export") :]
    try:
        return shlex.split(rest, comments=True)
    except ValueError:  # unbalanced quotes: fall back to whitespace words
        return TRAILING_COMMENT_RE.sub("", rest).split()


def _shell_violations(where: str, code: str) -> tuple[bool, list[str]]:
    """(is a shell command that sets a secret, violations) for one line of shell."""
    found: list[str] = []
    shell = False
    for command in COMMAND_SPLIT_RE.split(code):
        command = command.strip()
        if not re.match(r"export\s", command):
            continue
        for word in _export_words(command):
            match = EXPORT_WORD_RE.match(word)
            if not match:
                continue
            shell = True
            if _literal_value(match.group("value")):
                found.append(
                    f"{where}: `export {match.group('name')}=<literal>` types a key at "
                    "a shell prompt (shell history); put it in .env after the guard block"
                )
    for write in ECHO_WRITE_RE.finditer(code):
        for match in ECHO_ASSIGNMENT_RE.finditer(write.group("args")):
            shell = True
            if _literal_value(match.group("value")):
                found.append(
                    f"{where}: `{write.group('cmd')} {match.group('name')}=<literal> "
                    "> .env` types a key at a shell prompt (shell history); have the "
                    "user type it into .env in an editor after the guard block"
                )
    return shell, found


def _scan(path: str, text: str) -> tuple[list[str], list[tuple[int, str]]]:
    """(violations, guarded .env key writes as (line, section))."""
    found: list[str] = []
    guarded: list[tuple[int, str]] = []
    guarded_sections: set[int] = set()
    fences, prose = _parse(text)
    for fence in fences:
        for lineno, code in fence.body:
            line = code.strip()
            shell, shell_found = _shell_violations(f"{path}:{lineno}", line)
            found.extend(shell_found)
            if shell or re.match(r"export\s", line) or fence.language in PYTHON_INFO:
                continue
            match = ASSIGNMENT_RE.match(line)
            if not match or not _literal_value(match.group("value")):
                continue
            name = match.group("name")
            if fence.section_line not in guarded_sections:
                found.append(
                    f"{path}:{lineno}: .env key write `{name}=<literal>` in section "
                    f"{fence.section!r} has no earlier guard block in that section "
                    "(untracked + git-ignored check, chmod 600) before the key goes in"
                )
            else:
                guarded.append((lineno, fence.section))
        if is_guard(fence):
            guarded_sections.add(fence.section_line)
    for lineno, line in prose:
        for span in INLINE_CODE_RE.finditer(line):
            where = f"{path}:{lineno} (inline code)"
            found.extend(_shell_violations(where, span.group("code").strip())[1])
    return found, guarded


def violations(path: str, text: str) -> list[str]:
    """``file:line: reason`` for each key write that is typed at a prompt or unguarded."""
    return _scan(path, text)[0]


def _scoped_texts(repo_root: Path) -> list[tuple[str, str]]:
    return [
        (rel, (repo_root / rel).read_text(encoding="utf-8")) for rel in SCOPED_FILES
    ]


def _guard_blocks(repo_root: Path) -> list[tuple[str, int, str]]:
    return [
        (rel, fence.line, fence.text)
        for rel, text in _scoped_texts(repo_root)
        for fence in parse_fences(text)
        if is_guard(fence)
    ]


# 1 ---------------------------------------------------------------------------


def test_scoped_files_write_keys_only_after_the_guard(repo_root: Path) -> None:
    found = [v for rel, text in _scoped_texts(repo_root) for v in violations(rel, text)]
    assert not found, "\n".join(found)


# 2 ---------------------------------------------------------------------------


def test_guarded_env_examples_are_found(repo_root: Path) -> None:
    sections = {
        (rel, section)
        for rel, text in _scoped_texts(repo_root)
        for _, section in _scan(rel, text)[1]
    }
    assert len(sections) >= 2, (
        "expected a guarded .env key-write example in at least two sections "
        f"(found {sorted(sections)}); a parser regression must not pass by finding nothing"
    )


# 3 ---------------------------------------------------------------------------

GUARD = (
    "```bash\n"
    "git ls-files --error-unmatch -- .env\n"
    "git -c core.excludesFile=/dev/null check-ignore -q -- .env\n"
    "chmod 600 .env\n"
    "```\n"
)
ENV_EXAMPLE = "```\nOPENAI_API_KEY=sk-...\n```\n"


def test_probe_guard_before_example_passes() -> None:
    assert not violations("p.md", "## .env\n\n" + GUARD + "\n" + ENV_EXAMPLE)


def test_probe_guard_after_example_fails() -> None:
    assert violations("p.md", "## .env\n\n" + ENV_EXAMPLE + "\n" + GUARD)


def test_probe_guard_missing_fails() -> None:
    found = violations("p.md", "## .env\n\n" + ENV_EXAMPLE)
    assert found == [
        "p.md:4: .env key write `OPENAI_API_KEY=<literal>` in section '.env' has no "
        "earlier guard block in that section (untracked + git-ignored check, "
        "chmod 600) before the key goes in"
    ]


def test_probe_guard_in_another_section_fails() -> None:
    text = "## Setup\n\n" + GUARD + "\n### Example\n\n" + ENV_EXAMPLE
    assert violations("p.md", text)


def test_probe_prose_rule_is_not_a_guard() -> None:
    text = (
        "## .env\n\n`.env` must be git-ignored — never commit real keys. Run "
        "`git check-ignore -q -- .env` first.\n\n" + ENV_EXAMPLE
    )
    assert violations("p.md", text)


def test_probe_incomplete_guard_fails() -> None:
    partial = GUARD.replace("chmod 600 .env\n", "")
    assert violations("p.md", "## .env\n\n" + partial + ENV_EXAMPLE)


def test_probe_plain_check_ignore_still_identifies_a_guard() -> None:
    plain = GUARD.replace("git -c core.excludesFile=/dev/null ", "git ")
    assert not violations("p.md", "## .env\n\n" + plain + ENV_EXAMPLE)


def test_probe_export_literal_fails_even_after_guard() -> None:
    text = "## .env\n\n" + GUARD + '```bash\nexport OPENAI_API_KEY="sk-..."\n```\n'
    found = violations("p.md", text)
    assert len(found) == 1 and "export OPENAI_API_KEY" in found[0]


@pytest.mark.parametrize(
    "line",
    [
        "TRAIGENT_API_KEY=",
        'OPENAI_API_KEY=""',
        "OPENAI_API_KEY=   # paste after the =",
        "# OPENAI_API_KEY=sk-...",
        'export OPENAI_API_KEY="$OPENAI_API_KEY"',
        "export OPENAI_API_KEY=$(secret-tool lookup openai key)",
        'export A=1 OPENAI_API_KEY="$OPENAI_API_KEY"',
        'export TRAIGENT_BACKEND_URL="https://portal.traigent.ai"',
        "export TRAIGENT_COST_APPROVED=true",
        "export TRAIGENT_RUN_COST_LIMIT=5.0",
        'echo "OPENAI_API_KEY=$OPENAI_API_KEY" >> .env',
        "printf 'OPENAI_API_KEY=%s\\n' \"$KEY\" >> .env",
        'echo "OPENAI_API_KEY=" >> .env',
        "set -a; . ./.env; set +a",
        'OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]',
        'TRAIGENT_API_KEY = os.getenv("TRAIGENT_API_KEY")',
        'OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")',
    ],
)
def test_probe_non_key_writes_pass(line: str) -> None:
    assert not violations("p.md", f"## Any\n\n```bash\n{line}\n```\n")


@pytest.mark.parametrize(
    "line",
    [
        "export TRAIGENT_API_KEY=uk_...",
        "export AWS_SECRET_ACCESS_KEY=abc",
        "export GITHUB_TOKEN='x'",
        "export TRAIGENT_MASTER_PASSWORD=pw  # comment",
        "export A=1 OPENAI_API_KEY=sk-abc",
        "export TRAIGENT_DEBUG=1 GH_TOKEN='x' B=2",
        "cd app && export GH_TOKEN=x",
        'echo "OPENAI_API_KEY=sk-abc" >> .env',
        "echo OPENAI_API_KEY=sk-abc > .env",
        "printf 'GITHUB_TOKEN=ghp_x\\n' >> ./.env",
        'echo "A=1 OPENAI_API_KEY=sk-abc" >> .env',
    ],
)
def test_probe_secret_names_are_matched(line: str) -> None:
    assert violations("p.md", f"## Any\n\n{GUARD}```bash\n{line}\n```\n")


@pytest.mark.parametrize(
    "prose",
    [
        "Run `export OPENAI_API_KEY=sk-abc` first.",
        "> Or ``export GH_TOKEN=x`` in your shell.",
        "Last resort: `export A=1 TRAIGENT_API_KEY=uk_abc`.",
        "Or `echo 'OPENAI_API_KEY=sk-abc' >> .env`.",
    ],
)
def test_probe_inline_code_key_typing_fails(prose: str) -> None:
    found = violations("p.md", f"## Any\n\n{GUARD}\n{prose}\n")
    assert len(found) == 1 and "(inline code)" in found[0], found


@pytest.mark.parametrize(
    "prose",
    [
        "Don't type it into an `export` at a shell prompt.",
        "The docs taught `export TRAIGENT_MOCK_LLM=true`.",
        'Use `export OPENAI_API_KEY="$OPENAI_API_KEY"` only to pass one on.',
        "Load it with `set -a; . ./.env; set +a`.",
        "Leave `OPENAI_API_KEY=sk-...` in `.env` after the check.",
    ],
)
def test_probe_inline_code_non_key_writes_pass(prose: str) -> None:
    assert not violations("p.md", f"## Any\n\n{prose}\n")


@pytest.mark.parametrize("info", ["python", "py title=x.py", ""])
def test_probe_python_env_reads_pass(info: str) -> None:
    code = (
        'OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]\n'
        'TRAIGENT_API_KEY = os.getenv("TRAIGENT_API_KEY")\n'
    )
    assert not violations("p.md", f"## Any\n\n```{info}\n{code}```\n")


def test_probe_python_fence_is_not_a_env_body() -> None:
    assert not violations("p.md", "## Any\n\n```python\nX_TOKEN = 'y'\n```\n")
    assert violations("p.md", "## Any\n\n```\nX_TOKEN = 'y'\n```\n")


def _quoted(block: str) -> str:
    return "".join(f"> {line}\n" for line in block.splitlines())


def _indented(block: str) -> str:
    return "".join(f"   {line}\n" for line in block.splitlines())


@pytest.mark.parametrize("wrap", [_quoted, _indented], ids=["blockquote", "indented"])
def test_probe_wrapped_fences_parse_like_plain(wrap: Callable[[str], str]) -> None:
    plain_fences = parse_fences("## .env\n\n" + GUARD + "\n" + ENV_EXAMPLE)
    wrapped_fences = parse_fences(
        "## .env\n\n" + wrap(GUARD) + "\n" + wrap(ENV_EXAMPLE)
    )
    assert wrapped_fences == plain_fences
    assert not violations(
        "p.md", "## .env\n\n" + wrap(GUARD) + "\n" + wrap(ENV_EXAMPLE)
    )
    assert violations("p.md", "## .env\n\n" + wrap(ENV_EXAMPLE))
    assert violations("p.md", "## .env\n\n" + wrap('```bash\nexport GH_TOKEN="x"\n```'))


def test_probe_info_string_and_tilde_fences() -> None:
    text = (
        "## .env\n\n~~~bash title=guard\n"
        + GUARD[8:-4]
        + "~~~\n\n```dotenv\nX_TOKEN=y\n```\n"
    )
    assert not violations("p.md", text)
    assert violations("p.md", "## .env\n\n```dotenv title=.env\nX_TOKEN=y\n```\n")


# 4 ---------------------------------------------------------------------------

CALLER_ALIVE = "caller-alive-status:"
SENTINEL = "EXISTING_CONTENT_SENTINEL_384"
TRACKED_CONTENT = "tracked-target-384\n"

# scenario -> whether the guard must pass (exit 0, .env present at mode 0600)
SCENARIOS = {
    "fresh_ignored": True,
    "existing_ignored": True,
    "info_exclude_only": True,  # .git/info/exclude is repository-local: accepted
    "subdir_project": True,  # rule in the .gitignore next to a subdirectory's .env
    "outside_git_gitignored": True,
    "outside_git_no_git_on_path": True,
    "not_ignored": False,
    "subdir_root_rule_only": False,  # root "/.env" does not match app/.env
    "force_tracked": False,
    "ls_files_says_tracked": False,
    "ls_files_errors": False,
    "outside_git_no_gitignore": False,
    "no_git_on_path_in_repo": False,
    "dubious_owner": False,
    "git_dir_set": False,
    "symlink_to_tracked": False,
    "env_is_directory": False,
    "global_excludes_file": False,
    "xdg_excludes": False,
}
# ``git check-ignore`` never reports a tracked path as ignored, so a real force-tracked
# .env fails the ignore check whatever the guard does with ``ls-files``. These
# scenarios stub only ``git ls-files`` (exit status below) in an otherwise safe repo,
# so the guard's own reading of that status is what decides.
LS_FILES_STUB = {"ls_files_says_tracked": 0, "ls_files_errors": 128}
NO_REPO_GITIGNORE = {
    "not_ignored",
    "info_exclude_only",
    "global_excludes_file",
    "xdg_excludes",
}
SUBDIR = {"subdir_project", "subdir_root_rule_only"}
EXISTING_ENV = {"existing_ignored", "force_tracked"}
TOOLS_WITHOUT_GIT = ("grep", "touch", "chmod")
BASH = shutil.which("bash")


def _env(run_dir: Path) -> dict[str, str]:
    home = run_dir / "home"
    home.mkdir(exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CEILING_DIRECTORIES": str(run_dir),
        "LC_ALL": "C",
    }


def _git(cwd: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )


def _repo_ignores_env(project: Path, env: dict[str, str]) -> bool:
    done = subprocess.run(
        ["git", "check-ignore", "-q", "--", ".env"], cwd=project, env=env
    )
    return done.returncode == 0


def _without_git(run_dir: Path, env: dict[str, str]) -> dict[str, str]:
    bin_dir = run_dir / "no-git-bin"
    bin_dir.mkdir()
    for tool in TOOLS_WITHOUT_GIT:
        found = shutil.which(tool, path=env["PATH"])
        assert found, f"{tool} is needed to build a PATH without git"
        (bin_dir / tool).symlink_to(found)
    assert shutil.which("git", path=str(bin_dir)) is None
    return {**env, "PATH": str(bin_dir)}


def _stub_ls_files(run_dir: Path, env: dict[str, str], status: int) -> dict[str, str]:
    real_git = shutil.which("git", path=env["PATH"])
    stub_dir = run_dir / "stub-bin"
    stub_dir.mkdir()
    stub = stub_dir / "git"
    stub.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = ls-files ]; then exit {status}; fi\n'
        f'exec "{real_git}" "$@"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return {**env, "PATH": f"{stub_dir}{os.pathsep}{env['PATH']}"}


def _setup(scenario: str, run_dir: Path) -> tuple[Path, dict[str, str]]:
    """Build the scenario's project; return (directory the guard runs in, env)."""
    env = _env(run_dir)
    repo = run_dir / "project"
    project = repo / "app" if scenario in SUBDIR else repo
    project.mkdir(parents=True)
    if scenario.startswith("outside_git"):
        above = [p for p in project.parents if (p / ".git").exists()]
        assert not above, f"temp dir sits inside a Git repository: {above[0]}"
        if scenario != "outside_git_no_gitignore":
            (project / ".gitignore").write_text("node_modules/\n /.env \n", "utf-8")
        if scenario == "outside_git_no_git_on_path":
            env = _without_git(run_dir, env)
        return project, env

    _git(repo, env, "init", "-q")
    if scenario == "subdir_project":
        (project / ".gitignore").write_text("/.env\n", encoding="utf-8")
    elif scenario not in NO_REPO_GITIGNORE:
        (repo / ".gitignore").write_text("/.env\n", encoding="utf-8")
    if scenario == "info_exclude_only":
        with (repo / ".git" / "info" / "exclude").open("a", encoding="utf-8") as fh:
            fh.write(".env\n")
    if scenario == "global_excludes_file":
        excludes = run_dir / "global-excludes"
        excludes.write_text(".env\n", encoding="utf-8")
        config = run_dir / "global-gitconfig"
        config.write_text(f"[core]\n\texcludesFile = {excludes}\n", encoding="utf-8")
        env["GIT_CONFIG_GLOBAL"] = str(config)
    if scenario == "xdg_excludes":
        xdg = run_dir / "xdg"
        (xdg / "git").mkdir(parents=True)
        (xdg / "git" / "ignore").write_text(".env\n", encoding="utf-8")
        env["XDG_CONFIG_HOME"] = str(xdg)
    if scenario in {"global_excludes_file", "xdg_excludes"}:
        # The setup itself must make plain Git call .env ignored; otherwise the
        # scenario would pass for the wrong reason.
        assert _repo_ignores_env(project, env), f"{scenario}: setup did not ignore .env"
    if scenario in EXISTING_ENV:
        env_file = project / ".env"
        env_file.write_text(f"{SENTINEL}=1\n", encoding="utf-8")
        env_file.chmod(0o644)
    if scenario == "force_tracked":
        _git(repo, env, "add", "-f", ".env")
    if scenario == "symlink_to_tracked":
        target = repo / "config.txt"
        target.write_text(TRACKED_CONTENT, encoding="utf-8")
        target.chmod(0o644)
        _git(repo, env, "add", "config.txt")
        identity = ("-c", "user.name=t", "-c", "user.email=t@example.invalid")
        _git(repo, env, *identity, "commit", "-qm", "init")
        (project / ".env").symlink_to("config.txt")
    if scenario == "env_is_directory":
        (project / ".env").mkdir()
        (project / ".env").chmod(0o755)
    if scenario in LS_FILES_STUB:
        env = _stub_ls_files(run_dir, env, LS_FILES_STUB[scenario])
    if scenario == "no_git_on_path_in_repo":
        env = _without_git(run_dir, env)
    if scenario == "dubious_owner":
        env["GIT_TEST_ASSUME_DIFFERENT_OWNER"] = "1"
        probe = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            pytest.skip("this git ignores GIT_TEST_ASSUME_DIFFERENT_OWNER")
    if scenario == "git_dir_set":
        env["GIT_DIR"] = str(repo / ".git")
    return project, env


def _run_guard(
    block: str, project: Path, env: dict[str, str], caller: str
) -> tuple[int, str]:
    if caller == "plain":
        # Appended to the same shell, as if pasted: the line runs only if the guard
        # did not kill its caller, and it reports the guard's own exit status.
        script = block + f'printf "{CALLER_ALIVE}%s\\n" "$?"\n'
    else:
        # A caller with errexit, nounset and pipefail on. Run as a background job the
        # block inherits all three (an ``if`` or ``||`` around it would switch errexit
        # off inside it), so an expected non-zero status inside the block must be
        # handled by the block itself; ``wait`` then hands its status back to a
        # caller that is still alive to report it.
        script = (
            "set -euo pipefail\n"
            + block.rstrip("\n")
            + " &\n"
            + 'status=0; wait "$!" || status=$?\n'
            + f'printf "{CALLER_ALIVE}%s\\n" "$status"\n'
        )
    done = subprocess.run(
        [BASH or "bash", "-c", script],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = done.stdout + done.stderr
    marker = [
        line for line in done.stdout.splitlines() if line.startswith(CALLER_ALIVE)
    ]
    assert marker, f"guard ended the caller's shell (exit {done.returncode}):\n{output}"
    return int(marker[-1][len(CALLER_ALIVE) :]), output


@pytest.mark.parametrize("caller", ["plain", "errexit"])
@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_guard_blocks_behave(
    scenario: str, caller: str, repo_root: Path, tmp_path: Path
) -> None:
    if BASH is None or shutil.which("git") is None:
        pytest.skip("bash and git are needed to execute the guard block")
    blocks = _guard_blocks(repo_root)
    assert blocks, "no guard block found in the scoped files"
    for number, (rel, line, block) in enumerate(blocks):
        where = f"{rel}:{line} [{scenario}, {caller}]"
        run_dir = tmp_path / str(number)
        run_dir.mkdir()
        project, env = _setup(scenario, run_dir)
        env_file = project / ".env"

        status, output = _run_guard(block, project, env, caller)

        assert SENTINEL not in output, f"{where}: guard printed .env contents"
        assert TRACKED_CONTENT.strip() not in output, f"{where}: printed the target"
        if SCENARIOS[scenario]:
            assert status == 0, f"{where}: guard failed a safe .env\n{output}"
            assert not env_file.is_symlink() and env_file.is_file(), where
            assert stat.S_IMODE(env_file.stat().st_mode) == 0o600, where
            expected = f"{SENTINEL}=1\n" if scenario in EXISTING_ENV else ""
            assert env_file.read_text(encoding="utf-8") == expected, where
            continue
        assert status != 0, f"{where}: guard passed an unsafe .env\n{output}"
        assert "STOP:" in output, f"{where}: refused without a STOP message\n{output}"
        if scenario == "symlink_to_tracked":
            target = project / "config.txt"
            assert env_file.is_symlink(), where
            assert stat.S_IMODE(target.stat().st_mode) == 0o644, where
            assert target.read_text(encoding="utf-8") == TRACKED_CONTENT, where
        elif scenario == "env_is_directory":
            assert env_file.is_dir() and not any(env_file.iterdir()), where
            assert stat.S_IMODE(env_file.stat().st_mode) == 0o755, where
        elif scenario in EXISTING_ENV:
            assert env_file.read_text(encoding="utf-8") == f"{SENTINEL}=1\n", where
            assert stat.S_IMODE(env_file.stat().st_mode) == 0o644, where
        else:
            assert not os.path.lexists(env_file), f"{where}: created .env on failure"
        if scenario == "outside_git_no_gitignore":
            assert sorted(os.listdir(project)) == [], f"{where}: created files"


# 5 ---------------------------------------------------------------------------


def test_guard_blocks_are_identical(repo_root: Path) -> None:
    blocks = _guard_blocks(repo_root)
    assert blocks, "no guard block found in the scoped files"
    distinct = {block for _, _, block in blocks}
    where = ", ".join(f"{rel}:{line}" for rel, line, _ in blocks)
    assert len(distinct) == 1, f"guard blocks differ ({where}); keep one text"
