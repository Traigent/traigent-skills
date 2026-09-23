"""Raw provider clients are not intercepted by mock mode (traigent-skills#349).

``enable_mock_mode_for_quickstart()`` intercepts LiteLLM and LangChain calls only. A
raw ``openai`` / ``anthropic`` client in an example that the same page tells the
reader to mock dry-run makes real, billable requests during the "keyless" dry-run.
A page may still show a raw client (for example, the reader's existing code), but
only next to the raw-client caveat.

Scope: the setup skills. ``traigent-boost-agent/references/instrument-recipe.md``
has the same defect and is fixed separately; add its skill to ``SCOPED_SKILLS``
when that lands.
"""

from __future__ import annotations

import re
from pathlib import Path

SCOPED_SKILLS = (
    "traigent-setup-decorator",
    "traigent-setup-integrations",
    "traigent-setup-quickstart",
)

PYTHON_BLOCK_RE = re.compile(r"^```(?:python|py)\n(.*?)^```", re.S | re.M)
MOCK_DRY_RUN_RE = re.compile(r"enable_mock_mode_for_quickstart|mock dry-run", re.I)
RAW_CLIENT_CALL_RE = re.compile(
    r"openai\.chat\.completions\.create"
    r"|\b(?:Async)?OpenAI\(\)"
    r"|\banthropic\.(?:Async)?Anthropic\("
    r"|\bclient\.chat\.completions\.create"
)
RAW_CLIENT_CAVEAT_RE = re.compile(
    r"raw\s+`?(?:openai|anthropic)`?[^.\n]*(?:client|/)[^.\n]*?"
    r"(?:real, billable|not intercepted|still bill)",
    re.I,
)


def _scan(rel: str, text: str) -> list[str]:
    if not MOCK_DRY_RUN_RE.search(text) or RAW_CLIENT_CAVEAT_RE.search(text):
        return []
    violations = []
    for match in PYTHON_BLOCK_RE.finditer(text):
        call = RAW_CLIENT_CALL_RE.search(match.group(1))
        if call:
            line = text.count("\n", 0, match.start(1) + call.start()) + 1
            violations.append(
                f"{rel}:{line}: raw client `{call.group(0)}` on a page that teaches a "
                "mock dry-run, with no raw-client caveat (mock intercepts LiteLLM/LangChain only)"
            )
    return violations


def _scoped_markdown(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for skill in SCOPED_SKILLS:
        skill_dir = repo_root / "skills" / skill
        paths.append(skill_dir / "SKILL.md")
        paths.extend(sorted((skill_dir / "references").glob("*.md")))
    return paths


def test_mock_dry_run_pages_do_not_teach_uncaveated_raw_clients(
    repo_root: Path,
) -> None:
    violations: list[str] = []
    for path in _scoped_markdown(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        violations.extend(_scan(rel, path.read_text(encoding="utf-8")))
    assert not violations, "\n".join(violations)


def test_raw_client_lint_has_teeth() -> None:
    bad = (
        "Run a mock dry-run first.\n\n```python\n"
        "def f(q):\n    return openai.chat.completions.create(model=m, messages=[])\n```\n"
    )
    assert _scan("bad.md", bad)
    caveated = bad + (
        "\n> Mock mode covers LiteLLM/LangChain calls only — a raw `openai` / "
        "`anthropic` client in the body makes real, billable calls.\n"
    )
    assert not _scan("caveated.md", caveated)
    no_mock = bad.replace("Run a mock dry-run first.", "Production example.")
    assert not _scan("no_mock.md", no_mock)
