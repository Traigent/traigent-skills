"""Semantic skill lints — teaching rules the SDK-signature contract cannot see.

The released/develop contract tests validate that taught imports, symbols, and
``traigent.*``-rooted call kwargs exist in the installed wheel. They are blind to
two whole classes of wrong teaching, because the offending call is on a *user*
object (a ``@traigent.optimize``-decorated function), not a ``traigent.*`` name,
and because the real method signatures are permissive (``**algorithm_kwargs``):

1. ``func.optimize(dataset=...)`` / ``func.optimize_sync(dataset=...)`` — neither
   ``optimize`` nor ``optimize_sync`` has a ``dataset`` parameter (it is swallowed
   by ``**algorithm_kwargs`` and silently ignored). The evaluation dataset belongs
   on the decorator: ``@traigent.optimize(evaluation={"eval_dataset": ...})`` or
   the ``eval_dataset=`` shorthand.
2. ``results = func.optimize(...)`` with no ``await`` — ``OptimizedFunction.optimize``
   is a coroutine; assigning it without ``await`` (or ``asyncio.run(...)``) binds a
   never-run coroutine, not an ``OptimizationResult``. Top-level scripts must use the
   sync convenience ``func.optimize_sync(...)``.

Both shipped repo-wide (see traigent-skills#8) and survived the signature contract.
These lints gate that class directly.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .extract import _iter_fenced_blocks

# .optimize(dataset=  /  .optimize_sync( dataset = ...   (robust to whitespace;
# works on unparseable illustrative blocks too, since it is line-based)
DATASET_ON_OPTIMIZE_RE = re.compile(r"\.optimize(?:_sync)?\s*\(\s*dataset\s*=")


def _skill_markdown_files(repo_root: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    skills_root = repo_root / "skills"
    for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        out.append((skill_dir.name, skill_file))
        references = skill_dir / "references"
        if references.is_dir():
            out.extend((skill_dir.name, ref) for ref in sorted(references.glob("*.md")))
    return out


def _python_blocks(text: str):
    for block in _iter_fenced_blocks(text.splitlines()):
        if block.language.lower() not in {"python", "py"}:
            continue
        if block.lines and block.lines[0].strip() == "# contract: skip":
            continue
        yield block


def _decorated_with_traigent_optimize(tree: ast.AST) -> set[str]:
    """Names of functions carrying an ``@traigent.optimize(...)`` decorator."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "optimize"
                and isinstance(target.value, ast.Name)
                and target.value.id == "traigent"
            ):
                names.add(node.name)
    return names


def _awaited_or_runner_call_ids(tree: ast.AST) -> set[int]:
    """ids() of Call nodes that are awaited or wrapped in ``asyncio.run(...)``."""
    ok: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            ok.add(id(node.value))
        if isinstance(node, ast.Call):
            fn = node.func
            is_asyncio_run = (
                isinstance(fn, ast.Attribute)
                and fn.attr == "run"
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "asyncio"
            )
            if is_asyncio_run:
                for arg in node.args:
                    if isinstance(arg, ast.Call):
                        ok.add(id(arg))
    return ok


def _scan_dataset_kwarg(name: str, path: Path, text: str, repo_root: Path) -> list[str]:
    violations: list[str] = []
    for block in _python_blocks(text):
        for offset, line in enumerate(block.lines):
            if DATASET_ON_OPTIMIZE_RE.search(line):
                lineno = block.start_line + offset
                rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
                violations.append(
                    f"DEAD TEACHING  {rel}:{lineno}\n"
                    f"  teaches : {line.strip()}\n"
                    f"  problem : optimize()/optimize_sync() have no `dataset` param; it is "
                    f"silently swallowed by **algorithm_kwargs and ignored.\n"
                    f"  fix     : move the dataset onto the decorator — "
                    f'@traigent.optimize(eval_dataset="...") — and call '
                    f"func.optimize_sync() / await func.optimize() with no dataset."
                )
    return violations


def _scan_unawaited_optimize(name: str, path: Path, text: str, repo_root: Path) -> list[str]:
    violations: list[str] = []
    for block in _python_blocks(text):
        try:
            tree = ast.parse(block.text)
        except SyntaxError:
            continue  # illustrative fragment; signature contract handles imports
        decorated = _decorated_with_traigent_optimize(tree)
        if not decorated:
            continue
        ok_ids = _awaited_or_runner_call_ids(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "optimize":
                continue
            recv = node.func.value
            if not (isinstance(recv, ast.Name) and recv.id in decorated):
                continue
            if id(node) in ok_ids:
                continue
            lineno = block.start_line + node.lineno - 1
            rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
            violations.append(
                f"DEAD TEACHING  {rel}:{lineno}\n"
                f"  teaches : {recv.id}.optimize(...) bound without await\n"
                f"  problem : OptimizedFunction.optimize is a coroutine; without await "
                f"(or asyncio.run) this binds a never-run coroutine, not a result.\n"
                f"  fix     : use {recv.id}.optimize_sync(...) at top level, or "
                f"await {recv.id}.optimize(...) inside async code."
            )
    return violations


def test_no_dataset_kwarg_on_optimize(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(_scan_dataset_kwarg(name, path, path.read_text(encoding="utf-8"), repo_root))
    assert not violations, "\n\n".join(["", *violations, ""])


def test_optimize_method_calls_are_awaited_or_sync(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(_scan_unawaited_optimize(name, path, path.read_text(encoding="utf-8"), repo_root))
    assert not violations, "\n\n".join(["", *violations, ""])


def test_optimize_lints_have_teeth(tmp_path: Path) -> None:
    """Self-test: the lints must flag known-bad teaching and pass known-good."""
    bad = tmp_path / "skills" / "bad" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "```python\n"
        "import traigent\n"
        "@traigent.optimize(configuration_space={'model': ['gpt-4o-mini']})\n"
        "def f(x):\n"
        "    return x\n"
        'results = f.optimize(dataset="d.jsonl")\n'
        "```\n",
        encoding="utf-8",
    )
    assert _scan_dataset_kwarg("bad", bad, bad.read_text(), tmp_path), "dataset= lint missed a violation"
    assert _scan_unawaited_optimize("bad", bad, bad.read_text(), tmp_path), "await lint missed a violation"

    good = tmp_path / "skills" / "good" / "SKILL.md"
    good.parent.mkdir(parents=True)
    good.write_text(
        "```python\n"
        "import traigent\n"
        '@traigent.optimize(eval_dataset="d.jsonl")\n'
        "def f(x):\n"
        "    return x\n"
        "results = f.optimize_sync()\n"
        "```\n",
        encoding="utf-8",
    )
    assert not _scan_dataset_kwarg("good", good, good.read_text(), tmp_path), "dataset= lint false-positive"
    assert not _scan_unawaited_optimize("good", good, good.read_text(), tmp_path), "await lint false-positive"
