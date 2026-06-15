#!/usr/bin/env python3
"""Build the interface inventory baseline for the coverage ("should-use") ledger.

Emits ``tests/data/interface_inventory.json`` — the set of public interface elements that
EXIST, with stable IDs per surface:

    js:@traigent/sdk[/sub]#<symbol>     (from tests/data/js_api_snapshot.json)
    be:<METHOD> <path_template>          (from tests/data/backend_routes_snapshot.json)

The coverage ledger test (``test_coverage_ledger.py``) diffs the *current* inventory against
this committed baseline: a NEW element that no skill teaches and that has no `no_skill` waiver
fails — forcing a "does this need a skill?" decision. Today's surface is grandfathered (the
baseline == current), so the gate only fires on future additions. Regenerate this file (in the
same PR that refreshes a snapshot) to accept new elements; the diff is the review surface.

Usage (from the repo root):

    python tools/contract/build_interface_inventory.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path("tests/data/interface_inventory.json")


def build_ids(repo_root: Path) -> list[str]:
    ids: set[str] = set()
    ids.update(_js_ids(repo_root))
    ids.update(_be_ids(repo_root))
    return sorted(ids)


def _js_ids(repo_root: Path) -> set[str]:
    path = repo_root / "tests/data/js_api_snapshot.json"
    if not path.is_file():
        return set()
    exports = json.loads(path.read_text(encoding="utf-8")).get("exports") or {}
    return {f"js:{subpath}#{symbol}" for subpath, symbols in exports.items() for symbol in symbols}


def _be_ids(repo_root: Path) -> set[str]:
    path = repo_root / "tests/data/backend_routes_snapshot.json"
    if not path.is_file():
        return set()
    routes = json.loads(path.read_text(encoding="utf-8")).get("routes") or []
    return {f"be:{str(r['method']).upper()} {r['path_template']}" for r in routes}


def main() -> int:
    repo_root = Path.cwd()
    ids = build_ids(repo_root)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"schema": "interface-inventory/v1", "ids": ids}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.as_posix()} with {len(ids)} interface ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
