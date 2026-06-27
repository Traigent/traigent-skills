"""JS SDK contract — validate taught `@traigent/sdk` imports against the real exported surface.

The traigent-js skill teaches `import { X } from '@traigent/sdk[/sub]'`; those symbols rot when
the JS SDK renames/removes exports, and the Python contract can't see them (the harness installs
the Python wheel). This validates each taught named import against `tests/data/js_api_snapshot.json`,
which is vendored from traigent-js's committed api-surface snapshot (itself gated by the JS repo's
`api-surface.test.ts` against the built `dist/*.d.ts`).

Blocking only for skills that declare `js: true` in `sync_map.yml` (advisory otherwise).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from .facts import ContractFact

JS_FIX_MENU = (
    "  fix one : (a) refresh tests/data/js_api_snapshot.json from traigent-js\n"
    "            (b) fix the taught import symbol / subpath in the skill text\n"
    "            (c) declare `js: true` on this skill in sync_map.yml only when it owns the JS surface"
)


@pytest.fixture(scope="session")
def js_api_snapshot(repo_root: Path) -> dict[str, Any]:
    return json.loads(
        (repo_root / "tests/data/js_api_snapshot.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="session")
def js_export_index(js_api_snapshot: dict[str, Any]) -> dict[str, set[str]]:
    return {
        sub: set(symbols)
        for sub, symbols in (js_api_snapshot.get("exports") or {}).items()
    }


def check_js_import(module: str, symbol: str, index: dict[str, set[str]]) -> str | None:
    """Return a problem string if the import is invalid against the snapshot, else None."""
    if module not in index:
        return f"'{module}' is not an export subpath of @traigent/sdk"
    if symbol not in index[module]:
        return f"'{symbol}' is not exported from '{module}'"
    return None


def _js_declared(skill: str, sync_map: dict) -> bool:
    return bool(((sync_map.get("skills") or {}).get(skill) or {}).get("js"))


def _js_dead_teaching(
    fact: ContractFact, repo_root: Path, problem: str, ref: str
) -> str:
    return (
        f"DEAD TEACHING  {fact.rel_path(repo_root)}:{fact.line}\n"
        f"  teaches : {fact.display()}\n"
        f"  against : traigent-js API snapshot (ref {ref})\n"
        f"  problem : {problem}\n"
        f"{JS_FIX_MENU}"
    )


def test_taught_js_import_is_exported(
    js_fact: ContractFact,
    repo_root: Path,
    sync_map: dict,
    js_api_snapshot: dict[str, Any],
    js_export_index: dict[str, set[str]],
) -> None:
    if not _js_declared(js_fact.skill, sync_map):
        pytest.skip(f"js not declared for {js_fact.skill} — advisory only")
    reason = check_js_import(
        js_fact.module or "", js_fact.symbol or "", js_export_index
    )
    if reason is None:
        return
    ref = str(
        (js_api_snapshot.get("generated_from") or {}).get("commit_sha") or "unknown"
    )
    raise AssertionError(_js_dead_teaching(js_fact, repo_root, reason, ref))


def test_js_contract_has_teeth() -> None:
    """Self-test: the validator must flag bad symbol/subpath and pass a good one."""
    index = {
        "@traigent/sdk": {"optimize", "param", "getTrialParam"},
        "@traigent/sdk/langchain": {"withTraigentModel"},
    }
    assert check_js_import("@traigent/sdk", "optimize", index) is None
    assert check_js_import("@traigent/sdk", "notReal", index) is not None
    assert check_js_import("@traigent/sdk/nope", "optimize", index) is not None
