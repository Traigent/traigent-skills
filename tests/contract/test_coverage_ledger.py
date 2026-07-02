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


# python_api_snapshot.json section -> the `call_kwargs` namespace it maps into. Mirrors
# build_interface_inventory._PY_SECTION_NAMESPACES for the option namespaces (the surfaces a
# `call_kwargs` fact can teach).
_PY_KWARG_SECTIONS = {
    "optimize": "optimize_kwargs",
    "EvaluationOptions": "evaluation_options",
    "InjectionOptions": "injection_options",
    "ExecutionOptions": "execution_options",
}
_PY_OPTION_NAMESPACES = frozenset(
    {"EvaluationOptions", "InjectionOptions", "ExecutionOptions"}
)


def _py_namespace_fields(repo_root: Path) -> dict[str, frozenset[str]]:
    """Per-namespace public field/kwarg sets from the committed Python API snapshot."""
    path = repo_root / "tests/data/python_api_snapshot.json"
    snapshot = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {
        ns: frozenset(snapshot.get(section) or [])
        for ns, section in _PY_KWARG_SECTIONS.items()
    }


def _py_flatten_namespaces(leaf: str) -> frozenset[str]:
    """Namespaces a kwarg taught on ``leaf`` may be credited to.

    optimize() accepts each Options bundle's fields as flattened sugar, so a kwarg taught on
    ``optimize`` is the same capability as the matching Options field and vice versa. That bridge
    runs ONLY between optimize and an Options namespace — never Options<->Options: two distinct
    bundles do not share a kwarg just because a field NAME collides across them.
    """
    if leaf == "optimize":
        return _PY_OPTION_NAMESPACES | {"optimize"}
    if leaf in _PY_OPTION_NAMESPACES:
        return frozenset({leaf, "optimize"})
    return frozenset()


def _python_taught_ids(
    facts: tuple[ContractFact, ...], ns_fields: dict[str, frozenset[str]]
) -> set[str]:
    """Derive taught `py:` ids from the Python contract facts collected across skills.

    - call_kwargs on optimize / *Options -> py:<ns>#<kwarg> for each namespace that is BOTH a
      genuine flatten partner of the taught namespace (optimize<->Options only) AND actually
      declares <kwarg> per the snapshot (`ns_fields`). Requiring the field to exist in the target
      namespace stops a future same-name field in a *different* bundle from being silently
      counted as taught.
    - `from traigent...exceptions import X`  -> py:exception#X
    - `traigent <cmd> [<subcmd> ...]` CLI    -> py:cli#<cmd>, py:cli#<cmd subcmd>, ...
    """
    taught: set[str] = set()
    for fact in facts:
        if fact.kind == "call_kwargs" and fact.target:
            leaf = fact.target.rsplit(".", 1)[-1]
            namespaces = _py_flatten_namespaces(leaf)
            for kwarg in fact.kwargs:
                for namespace in namespaces:
                    if kwarg in ns_fields.get(namespace, frozenset()):
                        taught.add(f"py:{namespace}#{kwarg}")
        elif (
            fact.kind == "symbol"
            and fact.symbol
            and fact.module
            and fact.module.endswith("exceptions")
        ):
            taught.add(f"py:exception#{fact.symbol}")
        elif fact.kind == "cli" and fact.command:
            command = fact.command.strip()
            if not command.startswith("traigent "):
                continue  # e.g. `python -m traigent.tvl ...` is not a click subcommand
            tokens: list[str] = []
            for token in command[len("traigent ") :].split():
                if token.startswith("-"):
                    break
                tokens.append(token)
            for depth in range(1, len(tokens) + 1):
                taught.add("py:cli#" + " ".join(tokens[:depth]))
    return taught


def derive_taught_ids(repo_root: Path, facts: tuple[ContractFact, ...]) -> set[str]:
    taught: set[str] = {
        f"js:{f.module}#{f.symbol}" for f in facts if f.kind == "js_import"
    }
    taught |= _python_taught_ids(facts, _py_namespace_fields(repo_root))
    if _candidate_paths is None:
        return taught
    # BE: a route is taught if a url fact's candidate paths (and method) match it.
    routes = (
        json.loads(
            (repo_root / "tests/data/backend_routes_snapshot.json").read_text(
                encoding="utf-8"
            )
        ).get("routes")
        or []
    )
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
    new_unclassified = [
        c for c in (current - baseline) if c not in taught and c not in waivers
    ]
    assert new_unclassified == ["js:@traigent/sdk#BrandNewExport"]
    # taught silences it
    assert not [
        c
        for c in (current - baseline)
        if c not in {"js:@traigent/sdk#BrandNewExport"} and c not in waivers
    ]
    # waiver silences it
    assert not [
        c
        for c in (current - baseline)
        if c not in taught and c not in {"js:@traigent/sdk#BrandNewExport"}
    ]


def _kwargs_fact(target: str, *kwargs: str) -> ContractFact:
    return ContractFact(
        kind="call_kwargs",
        skill="fake-skill",
        path=Path("fake.md"),
        line=1,
        target=target,
        kwargs=kwargs,
    )


def test_python_taught_flattening_is_namespace_scoped() -> None:
    """Defect-2 teeth: a kwarg taught on one Options bundle must NOT credit a same-name field
    that only lives in a *different* bundle. The optimize<->Options flatten bridge never spans
    Options<->Options, and a credit requires the field to exist in the target namespace."""
    ns_fields = {
        "optimize": frozenset({"eval_dataset"}),
        "EvaluationOptions": frozenset({"eval_dataset", "question_budget"}),
        "InjectionOptions": frozenset({"question_budget"}),
        "ExecutionOptions": frozenset(),
    }

    # A skill teaches `question_budget` only under EvaluationOptions.
    taught = _python_taught_ids((_kwargs_fact("traigent.EvaluationOptions", "question_budget"),), ns_fields)
    assert "py:EvaluationOptions#question_budget" in taught  # exact namespace credited
    assert "py:InjectionOptions#question_budget" not in taught  # same-name other bundle NOT
    assert "py:optimize#question_budget" not in taught  # optimize does not accept it

    # Genuine optimize<->Options flattening still credits both sides: optimize(eval_dataset=)
    # is sugar for the EvaluationOptions field, and both namespaces declare it.
    opt_taught = _python_taught_ids((_kwargs_fact("traigent.optimize", "eval_dataset"),), ns_fields)
    assert "py:optimize#eval_dataset" in opt_taught
    assert "py:EvaluationOptions#eval_dataset" in opt_taught
