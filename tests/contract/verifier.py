from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .facts import ContractFact


def format_dead_teaching(
    fact: ContractFact,
    *,
    repo_root: Path | None,
    sdk_version: str,
    taught: str,
    problem: str,
    fix_menu: str | None = None,
) -> str:
    fix = fix_menu or (
        "  fix one : (a) raise this skill's min_sdk_version in sync_map.yml AND add\n"
        '                    "Requires `traigent>=X.Y.Z`" to its When to Use section\n'
        "                (b) replace the taught API with one available at the declared floor\n"
        "                (c) mark the block `# contract: skip` ONLY if it is illustrative pseudo-code"
    )
    return (
        f"DEAD TEACHING  {fact.rel_path(repo_root)}:{fact.line}\n"
        f"  teaches : {taught}\n"
        f"  against : traigent=={sdk_version}  (this skill's min_sdk_version bucket)\n"
        f"  problem : {problem}\n"
        f"{fix}"
    )


def verify_python_fact(fact: ContractFact, *, repo_root: Path | None, sdk_version: str) -> None:
    if fact.kind == "import":
        _assert_imports(fact, fact.module or "", repo_root=repo_root, sdk_version=sdk_version)
        return
    if fact.kind == "symbol":
        module = _assert_imports(fact, fact.module or "", repo_root=repo_root, sdk_version=sdk_version)
        if not hasattr(module, fact.symbol or ""):
            message = format_dead_teaching(
                fact,
                repo_root=repo_root,
                sdk_version=sdk_version,
                taught=f"from {fact.module} import {fact.symbol}",
                problem="symbol missing",
            )
            raise AssertionError(message)
        return
    if fact.kind == "call_kwargs":
        _assert_call_kwargs(fact, repo_root=repo_root, sdk_version=sdk_version)
        return
    raise AssertionError(f"unsupported python fact kind: {fact.kind}")


def _assert_imports(fact: ContractFact, module_name: str, *, repo_root: Path | None, sdk_version: str) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        message = format_dead_teaching(
            fact,
            repo_root=repo_root,
            sdk_version=sdk_version,
            taught=f"import {module_name}",
            problem="module not found",
        )
        raise AssertionError(message) from exc
    except Exception as exc:
        message = format_dead_teaching(
            fact,
            repo_root=repo_root,
            sdk_version=sdk_version,
            taught=f"import {module_name}",
            problem=f"module import failed: {type(exc).__name__}: {exc}",
        )
        raise AssertionError(message) from exc


def _assert_call_kwargs(fact: ContractFact, *, repo_root: Path | None, sdk_version: str) -> None:
    target = fact.target or ""
    try:
        obj = resolve_dotted(target)
    except ModuleNotFoundError as exc:
        message = format_dead_teaching(
            fact,
            repo_root=repo_root,
            sdk_version=sdk_version,
            taught=fact.display(),
            problem="module not found",
        )
        raise AssertionError(message) from exc
    except AttributeError as exc:
        message = format_dead_teaching(
            fact,
            repo_root=repo_root,
            sdk_version=sdk_version,
            taught=fact.display(),
            problem="symbol missing",
        )
        raise AssertionError(message) from exc

    inspect_target: Any = obj.__init__ if inspect.isclass(obj) else obj
    try:
        signature = inspect.signature(inspect_target)
    except (TypeError, ValueError) as exc:
        pytest.skip(f"{target} has no inspectable signature: {exc}")

    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        pytest.skip(f"{target} accepts **kwargs")

    missing = [name for name in fact.kwargs if name not in signature.parameters]
    if missing:
        message = format_dead_teaching(
            fact,
            repo_root=repo_root,
            sdk_version=sdk_version,
            taught=fact.display(),
            problem=f"kwarg not accepted: {', '.join(missing)}",
        )
        raise AssertionError(message)


def resolve_dotted(target: str) -> Any:
    parts = target.split(".")
    last_error: ModuleNotFoundError | None = None
    for index in range(len(parts), 0, -1):
        module_name = ".".join(parts[:index])
        try:
            obj: Any = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            last_error = exc
            continue
        for attr in parts[index:]:
            obj = getattr(obj, attr)
        return obj
    if last_error is not None:
        raise last_error
    raise ModuleNotFoundError(target)
