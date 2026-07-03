#!/usr/bin/env python3
"""Refresh the vendored Traigent (Python SDK) public teaching surface snapshot.

Generates ``tests/data/python_api_snapshot.json`` from a Traigent SDK checkout so the
coverage ("should-use") ledger can see when a NEW public Python kwarg / option / exception /
CLI subcommand ships. Before this generator the inventory only covered JS symbols and backend
routes, so Python drift (e.g. ``warm_start_from`` + ``surrogate_evaluator`` shipping publicly
yet taught nowhere) was structurally invisible.

The snapshot captures the *stable, machine-readable* public surface:

  * ``optimize_kwargs``     — the canonical current @traigent.optimize kwarg set. AUTHORITATIVE
                              source is the public ``def optimize(...)`` signature in
                              ``traigent/api/decorators.py``, unioned with the two supporting
                              literals it delegates to: the ``_OPTIMIZE_DEFAULTS`` dict keys (flat
                              bundle aliases folded in via ``**runtime_overrides``) and the
                              ``_ALLOWED_RUNTIME_OVERRIDE_KEYS`` frozenset (runtime-only knobs).
                              The union is required because no single source is complete — the
                              earlier DEFAULTS-only parse silently dropped signature-only kwargs
                              (``strategy``, ``strategy_params``, ``prompt_rewrite``,
                              ``grow_dataset``, ``skill_train``, ``legacy``). Legacy / removed
                              keys and the ``**runtime_overrides`` catch-all name are excluded.
  * ``evaluation_options``  — annotated fields of ``EvaluationOptions``  (same module).
  * ``injection_options``   — annotated fields of ``InjectionOptions``   (same module).
  * ``execution_options``   — annotated fields of ``ExecutionOptions``   (same module).
  * ``exceptions``          — public top-level classes of ``traigent/utils/exceptions.py``
                              (no ``__all__`` exists there, so "module public names" is used).
  * ``cli_commands``        — the ``traigent`` CLI command tree (dotted -> space-joined paths),
                              introspected from the live ``click`` group because subcommands are
                              registered dynamically (``cli.add_command`` / ``register_*``) and
                              have no reliable static source.

Everything except ``cli_commands`` is parsed with ``ast`` from ``git show <ref>:<path>`` — no
import, immune to a dirty/parked working tree. ``cli_commands`` requires importing the SDK, so
the checkout should be clean at ``--ref`` (a detached ``origin/develop`` worktree is ideal);
the recorded ``commit_sha`` is that ref's HEAD.

Usage (from the traigent-skills repo root, with the SDK importable in the env):

    python tools/contract/refresh_python_api.py --sdk-repo /tmp/rev-sdk-dev --ref HEAD
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_SLUG = "Traigent/Traigent"
# Source of truth: a detached worktree of Traigent origin/develop (see the workspace CLAUDE.md
# "Review-freshness guard"). Override with --sdk-repo for a different checkout.
DEFAULT_SDK_REPO = Path("/tmp/rev-sdk-dev")
DEFAULT_REF = "HEAD"
DEFAULT_OUT = Path("tests/data/python_api_snapshot.json")

DECORATORS_REL = "traigent/api/decorators.py"
EXCEPTIONS_REL = "traigent/utils/exceptions.py"

_OPTIMIZE_FUNC_NAME = "optimize"
_OPTIMIZE_DEFAULTS_NAME = "_OPTIMIZE_DEFAULTS"
# Current runtime-only override kwargs (cost_limit, metric_limit, ...) that are accepted by
# optimize() but not part of the decorator DEFAULTS dict. These are public and teaching-relevant
# (unlike ``_LEGACY_EXECUTION_OPTION_KEYS`` / ``_REMOVED_PARAMETERS``, which we exclude).
_RUNTIME_OVERRIDE_NAME = "_ALLOWED_RUNTIME_OVERRIDE_KEYS"
_OPTION_MODELS = ("EvaluationOptions", "InjectionOptions", "ExecutionOptions")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the vendored Traigent (Python SDK) public API snapshot.",
    )
    parser.add_argument("--sdk-repo", type=Path, default=DEFAULT_SDK_REPO)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    snapshot = build_snapshot(sdk_repo=args.sdk_repo, ref=args.ref)
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    total = (
        len(snapshot["optimize_kwargs"])
        + len(snapshot["evaluation_options"])
        + len(snapshot["injection_options"])
        + len(snapshot["execution_options"])
        + len(snapshot["exceptions"])
        + len(snapshot["cli_commands"])
    )
    print(
        f"wrote {out.as_posix()} with {total} python surface elements "
        f"from {snapshot['generated_from']['commit_sha']}",
    )
    return 0


def build_snapshot(*, sdk_repo: Path, ref: str) -> dict[str, Any]:
    commit_sha = _git(sdk_repo, "rev-parse", ref).strip()

    decorators_tree = ast.parse(
        _git(sdk_repo, "show", f"{ref}:{DECORATORS_REL}"), filename=DECORATORS_REL
    )
    exceptions_tree = ast.parse(
        _git(sdk_repo, "show", f"{ref}:{EXCEPTIONS_REL}"), filename=EXCEPTIONS_REL
    )

    return {
        "generated_from": {
            "repo": REPO_SLUG,
            "ref": ref,
            "commit_sha": commit_sha,
        },
        "optimize_kwargs": _optimize_kwargs(decorators_tree),
        "evaluation_options": _model_fields(decorators_tree, "EvaluationOptions"),
        "injection_options": _model_fields(decorators_tree, "InjectionOptions"),
        "execution_options": _model_fields(decorators_tree, "ExecutionOptions"),
        "exceptions": _public_exceptions(exceptions_tree),
        "cli_commands": _cli_commands(sdk_repo),
    }


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True)


def _optimize_kwargs(tree: ast.AST) -> list[str]:
    """The canonical current @traigent.optimize kwarg surface.

    AUTHORITATIVE source is the public ``def optimize(...)`` signature — the ground truth for
    what the decorator accepts directly. It is unioned with the two supporting literals the
    signature delegates to, because no single source is complete:

      * ``def optimize(...)`` keyword params — capture signature-only kwargs that live NOWHERE
        else (``strategy``, ``strategy_params``, ``prompt_rewrite``, ``grow_dataset``,
        ``skill_train``, ``legacy``). Parsing DEFAULTS alone (the prior behavior) dropped these.
      * ``_OPTIMIZE_DEFAULTS`` keys — flat bundle aliases (``injection_mode``, ``config_param``,
        ``auto_detect_tvars*``, ``max_trials``, ...) that the signature folds in through
        ``**runtime_overrides`` rather than declaring as standalone params.
      * ``_ALLOWED_RUNTIME_OVERRIDE_KEYS`` — runtime-only overrides (``cost_limit``,
        ``metric_limit``, ...) also accepted through ``**runtime_overrides``.

    Legacy / removed keys (``_LEGACY_EXECUTION_OPTION_KEYS``, ``_REMOVED_PARAMETERS``) and the
    ``**runtime_overrides`` catch-all name are intentionally NOT folded in — the ledger gates on
    the surface users are taught to use, not deprecated back-compat aliases or the var-keyword
    sink. Any ``_``-prefixed name is dropped as private.
    """
    keys = _optimize_signature_kwargs(tree)

    assignments = _top_level_assignments(tree)

    defaults_node = assignments.get(_OPTIMIZE_DEFAULTS_NAME)
    if not isinstance(defaults_node, ast.Dict):
        raise ValueError(f"could not find dict literal {_OPTIMIZE_DEFAULTS_NAME}")
    keys |= {
        key.value
        for key in defaults_node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }

    runtime_node = assignments.get(_RUNTIME_OVERRIDE_NAME)
    keys |= _string_literals(runtime_node)

    return sorted(k for k in keys if not k.startswith("_"))


def _optimize_signature_kwargs(tree: ast.AST) -> set[str]:
    """Public keyword parameter names of the ``def optimize(...)`` decorator signature.

    Collects positional-or-keyword and keyword-only params. The ``**runtime_overrides``
    var-keyword sink (and any ``*args`` vararg) is excluded — it is a catch-all, not a named
    public kwarg. ``_``-prefixed private params are dropped.
    """
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.FunctionDef) and node.name == _OPTIMIZE_FUNC_NAME:
            args = node.args
            names = {
                arg.arg
                for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)
            }
            return {name for name in names if not name.startswith("_")}
    raise ValueError(f"could not find function def {_OPTIMIZE_FUNC_NAME}")


def _top_level_assignments(tree: ast.AST) -> dict[str, ast.expr]:
    """Map of module-level target name -> assigned value node (plain and annotated)."""
    assignments: dict[str, ast.expr] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                assignments.setdefault(node.target.id, node.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, node.value)
    return assignments


def _string_literals(node: ast.expr | None) -> set[str]:
    """String constants inside a ``frozenset((...))`` / set / tuple / list literal."""
    if node is None:
        return set()
    if isinstance(node, ast.Call):
        # frozenset((...)) / set([...]) — descend into the single collection argument.
        collected: set[str] = set()
        for arg in node.args:
            collected |= _string_literals(arg)
        return collected
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        return {
            elt.value
            for elt in node.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        }
    return set()


def _model_fields(tree: ast.AST, class_name: str) -> list[str]:
    """Annotated (pydantic) field names of a top-level model class.

    Only ``name: Annotation`` assignments count, which naturally excludes ``model_config``
    (a plain assignment), validators/methods, and any ``_``-prefixed private field.
    """
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            fields: list[str] = []
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    name = stmt.target.id
                    if not name.startswith("_"):
                        fields.append(name)
            return sorted(set(fields))
    raise ValueError(f"could not find model class {class_name}")


def _public_exceptions(tree: ast.AST) -> list[str]:
    """Public top-level class names in exceptions.py (no ``__all__`` there)."""
    names = [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    ]
    return sorted(set(names))


def _cli_commands(sdk_repo: Path) -> list[str]:
    """Space-joined ``traigent`` CLI command paths, from the live click group.

    Subcommands are registered dynamically (``cli.add_command``, ``register_local_commands``,
    ``register_sync_command``), so there is no reliable static source — introspecting the built
    ``click`` group is the most stable machine-readable option. Hidden groups/commands (e.g. the
    ``edge-analytics`` internal tree) are excluded as non-teaching surface.
    """
    repo_str = str(sdk_repo)
    inserted = repo_str not in sys.path
    if inserted:
        sys.path.insert(0, repo_str)
    try:
        # Import fresh in case a different traigent is already resolved on the path.
        for mod in [m for m in list(sys.modules) if m == "traigent" or m.startswith("traigent.")]:
            del sys.modules[mod]
        cli_module = importlib.import_module("traigent.cli.main")
        group = cli_module.cli
    finally:
        if inserted and repo_str in sys.path:
            sys.path.remove(repo_str)

    commands: set[str] = set()

    def _walk(grp: Any, prefix: str) -> None:
        for name in sorted(getattr(grp, "commands", {})):
            command = grp.commands[name]
            if getattr(command, "hidden", False):
                continue
            path = f"{prefix} {name}".strip()
            commands.add(path)
            if hasattr(command, "commands"):
                _walk(command, path)

    _walk(group, "")
    return sorted(commands)


if __name__ == "__main__":
    raise SystemExit(main())
