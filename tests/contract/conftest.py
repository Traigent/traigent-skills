from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from packaging.version import InvalidVersion, Version

from .facts import ContractFact, collect_contract_facts


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--sdk-version",
        action="store",
        default=None,
        help="installed Traigent SDK version to validate against, or 'develop'",
    )


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def sync_map(repo_root: Path) -> dict[str, Any]:
    return _load_sync_map(repo_root)


@pytest.fixture(scope="session")
def all_contract_facts(repo_root: Path) -> tuple[ContractFact, ...]:
    return collect_contract_facts(str(repo_root))


@pytest.fixture(scope="session")
def sdk_version_label(pytestconfig: pytest.Config) -> str:
    return _sdk_version_label(pytestconfig)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    sync_map = _load_sync_map(repo_root)
    facts = collect_contract_facts(str(repo_root))

    if "python_fact" in metafunc.fixturenames:
        selected = [
            fact
            for fact in facts
            if fact.kind in {"import", "symbol", "call_kwargs"} and _in_bucket(fact.skill, sync_map, metafunc.config)
        ]
        metafunc.parametrize("python_fact", selected, ids=[fact.identifier(repo_root) for fact in selected])

    if "env_fact" in metafunc.fixturenames:
        selected = [
            fact
            for fact in facts
            if fact.kind == "env"
            and _in_bucket(fact.skill, sync_map, metafunc.config)
            and _env_fact_in_bucket(fact, sync_map, metafunc.config)
        ]
        metafunc.parametrize("env_fact", selected, ids=[fact.identifier(repo_root) for fact in selected])

    if "cli_fact" in metafunc.fixturenames:
        selected = [fact for fact in facts if fact.kind == "cli" and _in_bucket(fact.skill, sync_map, metafunc.config)]
        metafunc.parametrize("cli_fact", selected, ids=[fact.identifier(repo_root) for fact in selected])


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed or os.environ.get("GITHUB_ACTIONS") != "true":
        return

    fact = None
    if hasattr(item, "funcargs"):
        for name in ("python_fact", "env_fact", "cli_fact"):
            value = item.funcargs.get(name)
            if isinstance(value, ContractFact):
                fact = value
                break

    if fact is None:
        path = item.location[0]
        line = item.location[1] + 1
    else:
        path = fact.rel_path(Path(__file__).resolve().parents[2])
        line = fact.line

    message = _escape_github_annotation(str(report.longrepr))
    print(f"::error file={path},line={line}::{message}")


def skill_floor(sync_map: dict[str, Any], skill: str) -> str:
    skills = sync_map.get("skills") or {}
    entry = skills.get(skill) or {}
    return str(entry.get("min_sdk_version") or sync_map.get("default_min_sdk_version"))


def _load_sync_map(repo_root: Path) -> dict[str, Any]:
    data = yaml.safe_load((repo_root / "sync_map.yml").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError("sync_map.yml must contain a mapping")
    return data


def _sdk_version_label(config: pytest.Config) -> str:
    selected = config.getoption("--sdk-version")
    if selected:
        return str(selected)
    dist = _load_sync_map(Path(__file__).resolve().parents[2]).get("sdk", {}).get("dist", "traigent")
    try:
        return importlib.metadata.version(str(dist))
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _in_bucket(skill: str, sync_map: dict[str, Any], config: pytest.Config) -> bool:
    selected = _sdk_version_label(config)
    if selected == "develop":
        return True
    floor = skill_floor(sync_map, skill)
    try:
        return Version(floor) <= Version(selected)
    except InvalidVersion:
        return True


def _env_fact_in_bucket(fact: ContractFact, sync_map: dict[str, Any], config: pytest.Config) -> bool:
    """Per-variable version floors for env facts.

    A skill may teach an env var that only exists at a newer SDK version than
    the skill's own floor (e.g. documented for the next release). Declaring it
    under the skill's ``env_version_floors`` in sync_map.yml validates that
    variable only in buckets at or above its floor — and the skill text must
    state the version requirement in prose next to the variable.
    """
    floors = ((sync_map.get("skills") or {}).get(fact.skill) or {}).get("env_version_floors") or {}
    floor = floors.get(fact.name or "")
    if not floor:
        return True
    selected = _sdk_version_label(config)
    if selected == "develop":
        return True
    try:
        return Version(str(floor)) <= Version(selected)
    except InvalidVersion:
        return True


def _escape_github_annotation(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
