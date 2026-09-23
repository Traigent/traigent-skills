"""Fenced-block reader shared by the setup-skill audit lints (traigent-skills#349-#356).

The skills write Python examples as plain ```` ```python ```` fences, as
```` ```python runnable ```` fences (executed by ``test_runnable_snippets``), inside
blockquotes (``> ```python``) and indented under list items. A lint that only
matches ``^```python\\n`` silently skips the last three forms. ``python_blocks``
returns every Python block with its blockquote markers and indentation removed.

The probe test below plants one violation per lint in each of those forms and
requires every lint to report it.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

SCOPED_SKILLS = (
    "traigent-setup-decorator",
    "traigent-setup-integrations",
    "traigent-setup-quickstart",
)
PYTHON_LANGUAGES = {"python", "py"}
OPEN_FENCE_RE = re.compile(r"^(?P<prefix>[ \t]*(?:>[ \t]?)*[ \t]*)```(?P<info>[^`]*)$")


def _strip_prefix(line: str, quote_depth: int) -> str:
    for _ in range(quote_depth):
        line = re.sub(r"^[ \t]*>[ \t]?", "", line, count=1)
    return line


def python_blocks(text: str) -> list[tuple[int, str]]:
    """(1-based line of the block's first code line, dedented code) per Python fence."""
    blocks: list[tuple[int, str]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = OPEN_FENCE_RE.match(lines[index])
        if not match:
            index += 1
            continue
        depth = match.group("prefix").count(">")
        info = match.group("info").strip().split()
        language = info[0].lower() if info else ""
        body: list[str] = []
        index += 1
        start = index + 1
        while index < len(lines):
            inner = _strip_prefix(lines[index], depth)
            if inner.strip() == "```":
                break
            body.append(inner)
            index += 1
        index += 1
        if language in PYTHON_LANGUAGES:
            blocks.append((start, textwrap.dedent("\n".join(body)) + "\n"))
    return blocks


def scoped_markdown(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for skill in SCOPED_SKILLS:
        skill_dir = repo_root / "skills" / skill
        paths.append(skill_dir / "SKILL.md")
        paths.extend(sorted((skill_dir / "references").glob("*.md")))
    return paths


def test_python_blocks_reads_every_fence_form() -> None:
    doc = (
        "```python\na = 1\n```\n"
        "```python runnable\nb = 2\n```\n"
        "> ```python\n> c = 3\n>\n> d = 4\n> ```\n"
        "1. item\n   ```py\n   e = 5\n   ```\n"
        "```bash\nf=6\n```\n"
    )
    blocks = python_blocks(doc)
    assert [code for _, code in blocks] == [
        "a = 1\n",
        "b = 2\n",
        "c = 3\n\nd = 4\n",
        "e = 5\n",
    ]
    assert [line for line, _ in blocks] == [2, 5, 8, 14]


def test_audit_lints_see_runnable_quoted_and_indented_blocks() -> None:
    from .test_audit_349_raw_client_mock import _scan as scan_raw_client
    from .test_audit_350_auto_override import _scan_targets_without_flag
    from .test_audit_352_dspy_optimizer import _call_kwarg_violations
    from .test_audit_353_dspy_thread_safety import _scan as scan_dspy_configure
    from .test_audit_356_module_level_await import _scan as scan_await

    probes = {
        "raw client": (
            scan_raw_client,
            "Run a mock dry-run first.\n",
            "r = openai.chat.completions.create(model='m', messages=[])",
        ),
        "framework_targets": (
            _scan_targets_without_flag,
            "",
            "traigent.optimize(framework_targets=['langchain_openai.ChatOpenAI'])",
        ),
        "dspy kwargs": (
            _call_kwarg_violations,
            "",
            "DSPyPromptOptimizer(method='bootstrap', max_bootstrapped_demos=2)",
        ),
        "dspy.configure": (
            scan_dspy_configure,
            "",
            "@traigent.optimize(configuration_space={})\n"
            "def f(q):\n    dspy.configure(lm=None)\n    return q",
        ),
        "module await": (scan_await, "", "results = await f.optimize(max_trials=3)"),
    }
    missed = []
    for name, (scan, preamble, code) in probes.items():
        for form in ("runnable", "quoted", "indented"):
            if form == "runnable":
                block = f"```python runnable\n{code}\n```\n"
            elif form == "quoted":
                quoted = "\n".join(
                    f"> {line}" if line else ">" for line in code.split("\n")
                )
                block = f"> ```python\n{quoted}\n> ```\n"
            else:
                indented = textwrap.indent(code, "   ")
                block = f"1. step\n   ```python\n{indented}\n   ```\n"
            if not scan("probe.md", preamble + block):
                missed.append(f"{name} in a {form} block")
    assert not missed, "lint blind to: " + ", ".join(missed)
