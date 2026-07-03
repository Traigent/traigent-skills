from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.version import Version

from .conftest import skill_floor


def test_sync_map_has_bidirectional_skill_completeness(
    repo_root: Path, sync_map: dict
) -> None:
    skill_dirs = {
        path.name
        for path in (repo_root / "skills").iterdir()
        if (path / "SKILL.md").is_file()
    }
    mapped = set((sync_map.get("skills") or {}).keys())
    assert skill_dirs == mapped


def test_sync_map_declares_current_released_sdk(sync_map: dict) -> None:
    current_release = sync_map.get("current_released_sdk_version")
    assert isinstance(current_release, str) and current_release
    assert Version(current_release) >= Version(str(sync_map["default_min_sdk_version"]))


def test_released_bucket_list_includes_current_release(
    repo_root: Path, sync_map: dict
) -> None:
    output = subprocess.check_output(
        [sys.executable, str(repo_root / "tools/contract/list_buckets.py")],
        cwd=repo_root,
        text=True,
    )
    buckets = [line for line in output.splitlines() if line]
    assert str(sync_map["current_released_sdk_version"]) in buckets
    assert buckets == sorted(set(buckets), key=Version)


def test_sync_map_modules_import_in_current_bucket(
    sync_map: dict, pytestconfig: pytest.Config
) -> None:
    sdk_version = pytestconfig.getoption("--sdk-version") or "0"
    for skill, entry in (sync_map.get("skills") or {}).items():
        if sdk_version != "develop" and Version(skill_floor(sync_map, skill)) > Version(
            str(sdk_version)
        ):
            continue
        for module in entry.get("modules") or []:
            importlib.import_module(module)


def test_sync_map_sdk_paths_exist_in_installed_dist(
    sync_map: dict, pytestconfig: pytest.Config
) -> None:
    import traigent

    sdk_version = pytestconfig.getoption("--sdk-version") or "0"
    dist_root = Path(traigent.__file__).parent
    for skill, entry in (sync_map.get("skills") or {}).items():
        if sdk_version != "develop" and Version(skill_floor(sync_map, skill)) > Version(
            str(sdk_version)
        ):
            continue
        for sdk_path in entry.get("sdk_paths") or []:
            if not sdk_path.startswith("traigent/"):
                continue
            relative = sdk_path.removeprefix("traigent/")
            if "*" in relative:
                matches = list(dist_root.glob(relative))
                assert matches, f"{skill}: {sdk_path} matched no installed SDK files"
            else:
                assert (dist_root / relative).exists(), (
                    f"{skill}: {sdk_path} is absent from installed SDK"
                )


def _doc_cases() -> list[tuple[str, str]]:
    import yaml

    root = Path(__file__).resolve().parents[2]
    data = yaml.safe_load((root / "sync_map.yml").read_text(encoding="utf-8"))
    cases: list[tuple[str, str]] = []
    for skill, entry in (data.get("skills") or {}).items():
        for doc_path in entry.get("docs") or []:
            cases.append((skill, doc_path))
    return cases


@pytest.mark.parametrize("skill,doc_path", _doc_cases(), ids=lambda value: str(value))
def test_sync_map_docs_are_advisory_for_released_wheel(
    skill: str, doc_path: str
) -> None:
    pytest.skip(
        f"{skill}: {doc_path} is repo-only advisory material; nightly SDK-repo checks own it"
    )


def test_sync_map_render_is_current(repo_root: Path) -> None:
    rendered = subprocess.check_output(
        [sys.executable, str(repo_root / "tools/contract/render_sync_map.py")],
        cwd=repo_root,
    )
    assert rendered == (repo_root / "SYNC_MAP.md").read_bytes()
