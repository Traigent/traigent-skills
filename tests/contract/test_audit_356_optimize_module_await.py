"""No module-level `await` in the optimize skills' Python examples.

A top-level `await` is a SyntaxError once the example is pasted into a `.py`
file. Examples use `optimize_sync(...)`, or wrap the coroutine in
`async def main()` + `asyncio.run(main())`. Blockquoted fences are included;
the synced interaction-policy region is not an example and is skipped.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = [
    ROOT / "skills" / "traigent-optimize-run",
    ROOT / "skills" / "traigent-optimize-config-space",
    ROOT / "skills" / "traigent-optimize-composite-knobs",
]
FENCE_RE = re.compile(r"^(?P<quote>(?:>\s?)*)\s*(?P<fence>```+|~~~+)\s*(?P<info>[\w+-]*)")
POLICY_MARK = "<!-- INTERACTION_POLICY v1"


def _python_blocks(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    blocks: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        match = FENCE_RE.match(lines[index])
        if match and match["info"] in {"python", "py"}:
            quoted = bool(match["quote"])
            first = index + 2  # 1-based line of the first body line
            body: list[str] = []
            index += 1
            while index < len(lines) and not FENCE_RE.match(lines[index]):
                line = lines[index]
                if quoted:
                    line = re.sub(r"^(?:>\s?)", "", line)
                body.append(line)
                index += 1
            blocks.append((first, "\n".join(body)))
        index += 1
    return blocks


def _module_level_awaits(source: str) -> list[int]:
    try:
        tree = ast.parse(source)  # parse accepts top-level await; compile would not
    except SyntaxError:
        return []  # not a complete program (signature sketch); nothing to paste
    hits: list[int] = []

    def visit(node: ast.AST, in_async: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Await) and not in_async:
                hits.append(child.lineno)
            if isinstance(child, ast.AsyncFunctionDef):
                visit(child, True)
            elif isinstance(child, (ast.FunctionDef, ast.Lambda)):
                visit(child, False)
            else:
                visit(child, in_async)

    visit(tree, False)
    return hits


def test_optimize_skill_examples_have_no_module_level_await() -> None:
    offenders: list[str] = []
    for skill in SKILLS:
        for path in sorted(skill.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            cut = text.find(POLICY_MARK)
            if cut >= 0:
                text = text[:cut]
            for first, source in _python_blocks(text):
                for line in _module_level_awaits(source):
                    offenders.append(f"{path.relative_to(ROOT)}:{first + line - 1}")
    assert not offenders, "module-level await (SyntaxError in a .py file):\n" + "\n".join(
        offenders
    )


def test_detector_flags_top_level_await_only() -> None:
    assert _module_level_awaits("results = await f.optimize()") == [1]
    assert _module_level_awaits("async def main():\n    return await f.optimize()\n") == []
    assert _module_level_awaits("def g():\n    x = 1\nresults = await f()\n") == [3]
