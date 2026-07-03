from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from .facts import ContractFact
from .verifier import format_dead_teaching


ID_RE = re.compile(
    r"^(?:\d+|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
BACKEND_ROUTE_FAMILIES = (
    "datasets",
    "analytics",
    "experiment-runs",
    "optimization-comparisons",
    "sessions",
    "hybrid",
)
ENDPOINT_FIX_MENU = (
    "  fix one : (a) refresh tests/data/backend_routes_snapshot.json from TraigentBackend\n"
    "                (b) fix the taught endpoint path or HTTP method in the skill text\n"
    "                (c) declare this skill's backend_prefixes in sync_map.yml only when it owns that backend family"
)


@pytest.fixture(scope="session")
def backend_routes_snapshot(repo_root: Path) -> dict[str, Any]:
    return json.loads(
        (repo_root / "tests/data/backend_routes_snapshot.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.fixture(scope="session")
def backend_route_index(
    backend_routes_snapshot: dict[str, Any],
) -> tuple[set[str], set[tuple[str, str]]]:
    paths: set[str] = set()
    methods: set[tuple[str, str]] = set()
    for route in backend_routes_snapshot.get("routes") or []:
        path = _normalize_endpoint_path(str(route["path_template"]))
        method = str(route["method"]).upper()
        paths.add(path)
        methods.add((method, path))
    return paths, methods


def test_taught_backend_endpoint_exists_in_snapshot(
    url_fact: ContractFact,
    repo_root: Path,
    sync_map: dict,
    sdk_version_label: str,
    backend_routes_snapshot: dict[str, Any],
    backend_route_index: tuple[set[str], set[tuple[str, str]]],
) -> None:
    taught_path = url_fact.url or ""
    if not _falls_under_declared_prefix(url_fact.skill, taught_path, sync_map):
        pytest.skip(f"prefix not declared for {url_fact.skill} — advisory only")

    snapshot_paths, snapshot_methods = backend_route_index
    candidates = _candidate_paths(taught_path)
    method = url_fact.method
    found = (
        any((method, path) in snapshot_methods for path in candidates)
        if method
        else any(path in snapshot_paths for path in candidates)
    )
    if found:
        return

    sha = str(
        (backend_routes_snapshot.get("generated_from") or {}).get("commit_sha")
        or "unknown"
    )
    raise AssertionError(
        format_dead_teaching(
            url_fact,
            repo_root=repo_root,
            sdk_version=sdk_version_label,
            taught=url_fact.display(),
            problem=f"endpoint not found in backend route snapshot (ref {sha})",
            fix_menu=ENDPOINT_FIX_MENU,
        )
    )


def _falls_under_declared_prefix(skill: str, taught_path: str, sync_map: dict) -> bool:
    entry = (sync_map.get("skills") or {}).get(skill) or {}
    prefixes = [str(prefix) for prefix in (entry.get("backend_prefixes") or [])]
    if not prefixes:
        return False
    candidates = _candidate_paths(taught_path)
    return any(
        _path_is_under(candidate, _normalize_endpoint_path(prefix))
        for candidate in candidates
        for prefix in prefixes
    )


def _candidate_paths(path: str) -> tuple[str, ...]:
    normalized = _normalize_endpoint_path(path)
    candidates = {normalized}
    first_segment = normalized.strip("/").split("/", 1)[0]
    if first_segment in BACKEND_ROUTE_FAMILIES:
        candidates.add(_normalize_endpoint_path(f"/api/v1{normalized}"))
    return tuple(sorted(candidates))


def _path_is_under(path: str, prefix: str) -> bool:
    if path == prefix:
        return True
    return path.startswith(f"{prefix.rstrip('/')}/")


def _normalize_endpoint_path(path: str) -> str:
    cleaned = path.strip().split("?", 1)[0].split("#", 1)[0].rstrip(".,;:")
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    segments = [segment for segment in cleaned.strip("/").split("/") if segment]
    normalized = [_normalize_segment(segment) for segment in segments]
    return "/" + "/".join(normalized)


def _normalize_segment(segment: str) -> str:
    if (segment.startswith("{") and segment.endswith("}")) or (
        segment.startswith("<") and segment.endswith(">")
    ):
        return "*"
    if segment.startswith(":") and len(segment) > 1:
        return "*"
    if ID_RE.match(segment):
        return "*"
    return segment
