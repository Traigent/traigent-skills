from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from packaging.version import InvalidVersion, Version

from .extract import RunnableSnippet, collect_runnable_snippets
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
            if fact.kind in {"import", "symbol", "call_kwargs"}
            and _in_bucket(fact.skill, sync_map, metafunc.config)
            and _python_version_floor_ok(
                fact.skill, fact.path, sync_map, metafunc.config, repo_root
            )
        ]
        metafunc.parametrize(
            "python_fact",
            selected,
            ids=[fact.identifier(repo_root) for fact in selected],
        )

    if "env_fact" in metafunc.fixturenames:
        selected = [
            fact
            for fact in facts
            if fact.kind == "env"
            and _in_bucket(fact.skill, sync_map, metafunc.config)
            and _env_fact_in_bucket(fact, sync_map, metafunc.config)
        ]
        metafunc.parametrize(
            "env_fact", selected, ids=[fact.identifier(repo_root) for fact in selected]
        )

    if "cli_fact" in metafunc.fixturenames:
        selected = [
            fact
            for fact in facts
            if fact.kind == "cli" and _in_bucket(fact.skill, sync_map, metafunc.config)
        ]
        metafunc.parametrize(
            "cli_fact", selected, ids=[fact.identifier(repo_root) for fact in selected]
        )

    if "url_fact" in metafunc.fixturenames:
        selected = [
            fact
            for fact in facts
            if fact.kind == "url" and _in_bucket(fact.skill, sync_map, metafunc.config)
        ]
        metafunc.parametrize(
            "url_fact", selected, ids=[fact.identifier(repo_root) for fact in selected]
        )

    if "js_fact" in metafunc.fixturenames:
        # JS facts validate against the vendored JS API snapshot — version-independent.
        selected = [fact for fact in facts if fact.kind == "js_import"]
        metafunc.parametrize(
            "js_fact", selected, ids=[fact.identifier(repo_root) for fact in selected]
        )

    if "runnable_snippet" in metafunc.fixturenames:
        snippets = [
            snippet
            for snippet in collect_runnable_snippets(repo_root)
            if _in_bucket(snippet.skill, sync_map, metafunc.config)
            and _python_version_floor_ok(
                snippet.skill, snippet.path, sync_map, metafunc.config, repo_root
            )
        ]
        metafunc.parametrize(
            "runnable_snippet",
            snippets,
            ids=[snippet.identifier(repo_root) for snippet in snippets],
        )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    outcome = yield
    report = outcome.get_result()
    if (
        report.when != "call"
        or not report.failed
        or os.environ.get("GITHUB_ACTIONS") != "true"
    ):
        return

    fact = None
    if hasattr(item, "funcargs"):
        for name in ("python_fact", "env_fact", "cli_fact", "url_fact", "js_fact"):
            value = item.funcargs.get(name)
            if isinstance(value, ContractFact):
                fact = value
                break

    snippet = (
        item.funcargs.get("runnable_snippet") if hasattr(item, "funcargs") else None
    )

    if fact is not None:
        path = fact.rel_path(Path(__file__).resolve().parents[2])
        line = fact.line
    elif isinstance(snippet, RunnableSnippet):
        path = snippet.rel_path(Path(__file__).resolve().parents[2])
        line = snippet.start_line
    else:
        path = item.location[0]
        line = item.location[1] + 1

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
    dist = (
        _load_sync_map(Path(__file__).resolve().parents[2])
        .get("sdk", {})
        .get("dist", "traigent")
    )
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


def _env_fact_in_bucket(
    fact: ContractFact, sync_map: dict[str, Any], config: pytest.Config
) -> bool:
    """Per-variable version floors for env facts.

    A skill may teach an env var that only exists at a newer SDK version than
    the skill's own floor (e.g. documented for the next release). Declaring it
    under the skill's ``env_version_floors`` in sync_map.yml validates that
    variable only in buckets at or above its floor — and the skill text must
    state the version requirement in prose next to the variable.
    """
    floors = ((sync_map.get("skills") or {}).get(fact.skill) or {}).get(
        "env_version_floors"
    ) or {}
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


def _is_floorable_key(key: str) -> bool:
    """Only ``references/<name>.md`` inside the skill directory may be floored.

    Rejects ``SKILL.md`` (too broad -- see ``_python_version_floor_ok``), any
    nested or escaping path, and any non-markdown file.
    """
    parts = key.split("/")
    return (
        len(parts) == 2
        and parts[0] == "references"
        and parts[1].endswith(".md")
        and parts[1] not in ("", ".", "..")
    )


def _python_version_floor_ok(
    skill: str,
    path: Path,
    sync_map: dict[str, Any],
    config: pytest.Config,
    repo_root: Path,
) -> bool:
    """Per-file version floors for Python facts and runnable snippets.

    Mirrors ``env_version_floors`` (see ``_env_fact_in_bucket``): a skill may
    document an unreleased Traigent API — an import, symbol, call kwarg, or a
    runnable example — in one reference file (e.g.
    ``references/cold-start.md``) that only exists at a newer SDK version than
    the skill's own floor. Declaring that file under the skill's
    ``python_version_floors`` in sync_map.yml validates every Python fact and
    runnable snippet extracted from that file only in buckets at or above the
    floor — and the file must state the version requirement in prose (see
    ``test_python_floored_files_state_required_sdk_in_prose``).

    Keyed by the file's path relative to the skill directory, not by symbol
    name (a ``call_kwargs`` fact is a target+kwargs tuple, not one stable
    string) and never by a whole-skill wildcard: raising ``min_sdk_version``
    itself to an unreleased version is what this mechanism exists to avoid —
    ``list_buckets.py`` turns every distinct ``min_sdk_version`` into a
    ``pip install traigent==<version>`` bucket, and an unreleased version has
    no wheel to install. This function only narrows which buckets a fact is
    *collected* into; it never weakens ``verify_python_fact`` itself, so a
    fact floored at a version where the taught API still does not exist keeps
    failing in every bucket at or above that floor.
    """
    floors = ((sync_map.get("skills") or {}).get(skill) or {}).get(
        "python_version_floors"
    ) or {}
    if not floors:
        return True
    key = _skill_relative_path(skill, path, repo_root)
    # `key not in floors`, NOT `if not floor`. A present-but-falsy value ("",
    # None, False, 0, []) is a malformed DECLARATION, and truthiness would send
    # it down the "no floor here" path, skipping validation entirely. It cannot
    # make a failing fact pass -- it admits the fact everywhere -- but it makes
    # the entry silently inert, which is the failure mode this file exists to
    # refuse.
    if key not in floors:
        return True
    floor = floors[key]
    # A floor may only narrow a REFERENCE file, never SKILL.md.
    #
    # Most of a skill's Python facts live in SKILL.md itself, so accepting it
    # as a key would let one line suppress an entire skill's contract checking
    # in every lower bucket -- the whole-skill wildcard this mechanism is
    # supposed not to have, spelled differently. Reference files are where an
    # unreleased API actually gets documented, which is the case this exists
    # to serve.
    if not _is_floorable_key(key):
        raise AssertionError(
            f"{skill}: python_version_floors key {key!r} is not allowed. "
            "Only 'references/*.md' may carry a floor; SKILL.md and other "
            "paths would suppress checking too broadly."
        )
    # Validate the floor BEFORE the develop short-circuit. Returning early on
    # develop would silently honour an unparseable floor in exactly the job
    # that gates pull requests (develop-contracts), so a typo'd version would
    # ship and only surface later in a released bucket.
    try:
        floor_version = Version(str(floor))
    except InvalidVersion as exc:
        # A typo'd floor previously fell through to "check everywhere", which
        # is safe but silent: the declaration looked effective and did nothing,
        # and prose like "Requires traigent>=next" satisfied the lint. Fail
        # loudly instead -- an unenforceable declaration is a defect, not a
        # default.
        raise AssertionError(
            f"{skill}: python_version_floors[{key!r}] = {floor!r} is not a "
            "valid PEP 440 version"
        ) from exc
    selected = _sdk_version_label(config)
    if selected == "develop":
        return True
    return floor_version <= Version(selected)


def _skill_relative_path(skill: str, path: Path, repo_root: Path) -> str:
    skill_dir = repo_root / "skills" / skill
    try:
        return path.resolve().relative_to(skill_dir.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _escape_github_annotation(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
