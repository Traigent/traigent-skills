"""No ``dspy.configure`` inside an optimized function (traigent-skills#353).

Traigent runs examples on worker threads. DSPy only lets the thread that first
configured it call ``dspy.configure``; every other thread raises, and those
examples score as wrong without failing the trial. Inside a
``@traigent.optimize``-decorated function, examples must use
``with dspy.context(lm=...)``. Module-level ``dspy.configure`` stays allowed.
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


def _is_traigent_optimize(dec: ast.expr) -> bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "optimize"
        and isinstance(target.value, ast.Name)
        and target.value.id == "traigent"
    )


def _is_dspy_configure(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "configure"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "dspy"
    )


def _scan(rel: str, text: str) -> list[str]:
    violations = []
    for match in PYTHON_BLOCK_RE.finditer(text):
        try:
            tree = ast.parse(match.group(1))
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(_is_traigent_optimize(d) for d in fn.decorator_list):
                continue
            for node in ast.walk(fn):
                if _is_dspy_configure(node):
                    line = text.count("\n", 0, match.start(1)) + node.lineno
                    violations.append(
                        f"{rel}:{line}: dspy.configure() inside @traigent.optimize "
                        f"function `{fn.name}`; use `with dspy.context(lm=...)`"
                    )
    return violations


def test_no_dspy_configure_inside_optimized_functions(repo_root: Path) -> None:
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


def test_dspy_configure_lint_has_teeth() -> None:
    bad = (
        "```python\nimport dspy, traigent\ndspy.configure(lm=None)\n\n"
        "@traigent.optimize(configuration_space={})\ndef f(q):\n"
        "    dspy.configure(lm=dspy.LM('m'))\n    return q\n```\n"
    )
    found = _scan("bad.md", bad)
    assert len(found) == 1 and "bad.md:7" in found[0], found
    good = bad.replace(
        "    dspy.configure(lm=dspy.LM('m'))\n    return q",
        "    with dspy.context(lm=dspy.LM('m')):\n        return q",
    )
    assert not _scan("good.md", good)
