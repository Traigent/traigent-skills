"""Coverage ("should-use") ledger — flag a NEW interface element that no skill teaches.

The interface inventory baseline (``tests/data/interface_inventory.json``) records the public
elements that exist. This test rebuilds the current inventory from the committed snapshots and
fails when a **new** element (not in the baseline) is neither taught by a skill (derived from the
contract facts) nor waived in ``coverage_ledger.yml``. Today's surface is grandfathered, so the
gate only fires on future additions — the "should-use" direction: a new capability surfaces a
decision (teach it, or waive it) rather than shipping unmentioned.

Refresh the baseline with ``tools/contract/build_interface_inventory.py`` in the same PR that
introduces the new element; the diff is the review surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .facts import ContractFact, collect_contract_facts

try:
    from .test_endpoints import _candidate_paths, _normalize_endpoint_path
except Exception:  # pragma: no cover - endpoint helpers optional
    _candidate_paths = None
    _normalize_endpoint_path = None


def _baseline_ids(repo_root: Path) -> set[str]:
    path = repo_root / "tests/data/interface_inventory.json"
    if not path.is_file():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")).get("ids") or [])


def _current_ids(repo_root: Path) -> set[str]:
    import sys

    sys.path.insert(0, str(repo_root / "tools" / "contract"))
    from build_interface_inventory import build_ids  # type: ignore[import-not-found]

    return set(build_ids(repo_root))


def _waivers(repo_root: Path) -> set[str]:
    path = repo_root / "coverage_ledger.yml"
    if not path.is_file():
        return set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return set((data.get("waivers") or {}).keys())


def derive_taught_ids(repo_root: Path, facts: tuple[ContractFact, ...]) -> set[str]:
    taught: set[str] = {f"js:{f.module}#{f.symbol}" for f in facts if f.kind == "js_import"}
    if _candidate_paths is None:
        return taught
    # BE: a route is taught if a url fact's candidate paths (and method) match it.
    routes = json.loads(
        (repo_root / "tests/data/backend_routes_snapshot.json").read_text(encoding="utf-8")
    ).get("routes") or []
    url_facts = [f for f in facts if f.kind == "url"]
    for route in routes:
        method = str(route["method"]).upper()
        norm_template = _normalize_endpoint_path(str(route["path_template"]))
        for fact in url_facts:
            if fact.method and fact.method.upper() != method:
                continue
            if norm_template in _candidate_paths(fact.url or ""):
                taught.add(f"be:{method} {route['path_template']}")
                break
    return taught


def test_new_interfaces_are_taught_or_waived(repo_root: Path) -> None:
    current = _current_ids(repo_root)
    baseline = _baseline_ids(repo_root)
    taught = derive_taught_ids(repo_root, collect_contract_facts(str(repo_root)))
    waivers = _waivers(repo_root)

    new_unclassified = sorted(
        cid for cid in (current - baseline) if cid not in taught and cid not in waivers
    )
    assert not new_unclassified, (
        "\n\nNew interface element(s) that no skill teaches and no waiver covers:\n"
        + "\n".join(f"  - {cid}" for cid in new_unclassified)
        + "\n\nDecide each: teach it in a skill, OR add a `no_skill` waiver to coverage_ledger.yml,\n"
        + "then refresh tests/data/interface_inventory.json with build_interface_inventory.py.\n"
    )


def test_coverage_ledger_has_teeth(tmp_path: Path) -> None:
    """Self-test: a new untaught/unwaived id must be flagged; taught/waived ones must not."""
    baseline = {"js:@traigent/sdk#optimize"}
    current = {"js:@traigent/sdk#optimize", "js:@traigent/sdk#BrandNewExport"}
    taught: set[str] = set()
    waivers: set[str] = set()
    new_unclassified = [c for c in (current - baseline) if c not in taught and c not in waivers]
    assert new_unclassified == ["js:@traigent/sdk#BrandNewExport"]
    # taught silences it
    assert not [c for c in (current - baseline) if c not in {"js:@traigent/sdk#BrandNewExport"} and c not in waivers]
    # waiver silences it
    assert not [c for c in (current - baseline) if c not in taught and c not in {"js:@traigent/sdk#BrandNewExport"}]
