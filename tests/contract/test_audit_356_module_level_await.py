"""No module-level ``await`` in script examples (traigent-skills#356).

A fenced Python block with ``await`` outside an ``async def`` is a
``SyntaxError: 'await' outside function`` when pasted into a ``.py`` file. Such a
block is allowed only when it says it is notebook / async-context code with a
comment (for example ``# in a notebook cell`` or ``# inside an async function``).

Scope: the setup skills. The synced interaction-policy block (edited only in
``docs/shared/interaction-policy.v1.md``) is skipped here; it and other skills'
module-level awaits are tracked separately.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SCOPED_SKILLS = (
    "traigent-setup-decorator",
    "traigent-setup-integrations",
    "traigent-setup-quickstart",
)
PYTHON_BLOCK_RE = re.compile(r"^```(?:python|py)\n(.*?)^```", re.S | re.M)
ASYNC_CONTEXT_MARK_RE = re.compile(
    r"#.*\b(?:notebook|async context|inside an? async)\b", re.I
)
SYNCED_POLICY_RE = re.compile(
    r"<!-- INTERACTION_POLICY v\d+ .*?<!-- /INTERACTION_POLICY v\d+ -->", re.S
)


def _module_level_awaits(tree: ast.AST) -> list[int]:
    lines: list[int] = []

    def visit(node: ast.AST, in_async: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AsyncFunctionDef):
                visit(child, True)
            elif isinstance(child, (ast.FunctionDef, ast.Lambda)):
                visit(child, False)
            else:
                if not in_async and isinstance(
                    child, (ast.Await, ast.AsyncFor, ast.AsyncWith)
                ):
                    lines.append(child.lineno)
                visit(child, in_async)

    visit(tree, False)
    return lines


def _scan(rel: str, text: str) -> list[str]:
    synced = [m.span() for m in SYNCED_POLICY_RE.finditer(text)]
    violations = []
    for match in PYTHON_BLOCK_RE.finditer(text):
        if any(start <= match.start() < end for start, end in synced):
            continue
        block = match.group(1)
        if ASYNC_CONTEXT_MARK_RE.search(block):
            continue
        try:
            tree = ast.parse(block)
        except SyntaxError:
            continue
        first = text.count("\n", 0, match.start(1))
        for lineno in _module_level_awaits(tree):
            violations.append(
                f"{rel}:{first + lineno}: module-level `await` in a script example "
                "(SyntaxError in a .py file); use the sync call, asyncio.run(...), or "
                "mark the block as notebook / async-context code"
            )
    return violations


def test_setup_skill_examples_have_no_module_level_await(repo_root: Path) -> None:
    violations: list[str] = []
    for skill in SCOPED_SKILLS:
        skill_dir = repo_root / "skills" / skill
        for path in [
            skill_dir / "SKILL.md",
            *sorted(skill_dir.glob("references/*.md")),
        ]:
            rel = path.relative_to(repo_root).as_posix()
            violations.extend(_scan(rel, path.read_text(encoding="utf-8")))
    assert not violations, "\n".join(violations)


def test_module_level_await_lint_has_teeth() -> None:
    bad = "```python\nresults = await f.optimize(max_trials=3)\n```\n"
    assert _scan("bad.md", bad)
    assert not _scan(
        "async.md", bad.replace("results", "# in a notebook cell\nresults")
    )
    wrapped = (
        "```python\nimport asyncio\n\nasync def main():\n"
        "    return await f.optimize(max_trials=3)\n\nasyncio.run(main())\n```\n"
    )
    assert not _scan("wrapped.md", wrapped)
    policy = (
        "<!-- INTERACTION_POLICY v1 (synced) -->\n"
        + bad
        + "<!-- /INTERACTION_POLICY v1 -->\n"
    )
    assert not _scan("policy.md", policy)
