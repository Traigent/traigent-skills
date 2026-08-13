"""``python_version_floors`` — per-file version floors for Python facts.

Mirrors ``env_version_floors`` (see ``conftest._env_fact_in_bucket``), but for
Python facts (imports, symbols, call kwargs) and runnable snippets rather than
``TRAIGENT_*`` env vars. A skill cannot document an unreleased SDK API by
raising its own ``min_sdk_version``: ``list_buckets.py`` turns every distinct
``min_sdk_version`` into a ``pip install traigent==<version>`` bucket, and an
unreleased version has no wheel to install
(``No solution found ... no version of traigent==0.27.0``).
``python_version_floors`` solves this the same way ``env_version_floors``
solves it for env vars: gate the individual fact by a per-file floor instead
of moving the whole skill's floor.

These tests prove three things the design depends on:

1. The floor actually excludes a fact from buckets below it, and includes it
   at/above it (``_python_version_floor_ok``).
2. Flooring a fact does NOT weaken verification — a fact floored at a version
   where the taught API still does not exist keeps failing in every bucket at
   or above the floor. This is the mechanism's whole point: it must not
   become a way to silence an inconvenient contract failure by declaring a
   floor.
3. The prose requirement is enforced, not just documented: a floored file
   that doesn't state its version requirement fails a dedicated lint.

A fourth test (in this file) proves ``list_buckets.py`` never derives a
bucket from ``python_version_floors`` — only from ``min_sdk_version``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from packaging.version import InvalidVersion, Version
import yaml
from packaging.version import Version

from .facts import ContractFact
from .conftest import (
    _is_floorable_key,
    _python_version_floor_ok,
    _skill_relative_path,
)
from .verifier import verify_python_fact


class _FakeConfig:
    """Minimal stand-in for pytest.Config — only ``getoption`` is used."""

    def __init__(self, sdk_version: str | None) -> None:
        self._sdk_version = sdk_version

    def getoption(self, name: str) -> str | None:
        assert name == "--sdk-version"
        return self._sdk_version


FLOORED_REL_PATH = "references/unreleased.md"


def _floored_sync_map(floor: str = "0.27.0") -> dict:
    return {
        "skills": {
            "demo": {
                "python_version_floors": {FLOORED_REL_PATH: floor},
            }
        }
    }


# ---------------------------------------------------------------------------
# 1. The floor gates fact selection: excluded below, included at/above.
# ---------------------------------------------------------------------------


def test_python_version_floor_excludes_fact_below_floor(repo_root: Path) -> None:
    sync_map = _floored_sync_map("0.27.0")
    path = repo_root / "skills" / "demo" / FLOORED_REL_PATH
    config = _FakeConfig("0.23.0")  # below the floor
    assert (
        _python_version_floor_ok("demo", path, sync_map, config, repo_root) is False
    )


def test_python_version_floor_includes_fact_at_floor(repo_root: Path) -> None:
    sync_map = _floored_sync_map("0.27.0")
    path = repo_root / "skills" / "demo" / FLOORED_REL_PATH
    config = _FakeConfig("0.27.0")  # exactly at the floor
    assert _python_version_floor_ok("demo", path, sync_map, config, repo_root) is True


def test_python_version_floor_includes_fact_above_floor(repo_root: Path) -> None:
    sync_map = _floored_sync_map("0.27.0")
    path = repo_root / "skills" / "demo" / FLOORED_REL_PATH
    config = _FakeConfig("0.30.0")  # above the floor
    assert _python_version_floor_ok("demo", path, sync_map, config, repo_root) is True


def test_python_version_floor_develop_always_included(repo_root: Path) -> None:
    sync_map = _floored_sync_map("0.99.0")
    path = repo_root / "skills" / "demo" / FLOORED_REL_PATH
    config = _FakeConfig("develop")
    assert _python_version_floor_ok("demo", path, sync_map, config, repo_root) is True


def test_python_version_floor_unfloored_file_always_included(repo_root: Path) -> None:
    sync_map = _floored_sync_map("0.99.0")
    other_path = repo_root / "skills" / "demo" / "references" / "other.md"
    config = _FakeConfig("0.1.0")
    assert (
        _python_version_floor_ok("demo", other_path, sync_map, config, repo_root)
        is True
    )


def test_python_version_floor_unfloored_skill_always_included(repo_root: Path) -> None:
    sync_map = _floored_sync_map("0.99.0")
    path = repo_root / "skills" / "other-skill" / FLOORED_REL_PATH
    config = _FakeConfig("0.1.0")
    assert (
        _python_version_floor_ok("other-skill", path, sync_map, config, repo_root)
        is True
    )


def test_python_version_floor_does_not_honor_a_whole_skill_wildcard(
    repo_root: Path,
) -> None:
    """The mechanism is keyed by file path only — a "*" entry is inert, not a
    skill-wide wildcard. Nothing in ``_python_version_floor_ok`` special-cases
    it; this pins that down explicitly."""
    sync_map = {
        "skills": {"demo": {"python_version_floors": {"*": "0.99.0"}}}
    }
    path = repo_root / "skills" / "demo" / "references" / "anything.md"
    config = _FakeConfig("0.1.0")
    assert _python_version_floor_ok("demo", path, sync_map, config, repo_root) is True


def test_skill_relative_path_shape(repo_root: Path) -> None:
    path = repo_root / "skills" / "demo" / "references" / "unreleased.md"
    assert _skill_relative_path("demo", path, repo_root) == FLOORED_REL_PATH

    skill_md = repo_root / "skills" / "demo" / "SKILL.md"
    assert _skill_relative_path("demo", skill_md, repo_root) == "SKILL.md"


# ---------------------------------------------------------------------------
# 2. Critical: a fact wrongly floored at a version where the API STILL does
#    not exist must keep failing once the bucket reaches that floor. The
#    floor mechanism only narrows which buckets collect a fact; it never
#    weakens verify_python_fact.
# ---------------------------------------------------------------------------


def test_bogus_symbol_floored_anywhere_still_fails_at_its_own_floor(
    repo_root: Path,
) -> None:
    sync_map = _floored_sync_map("0.99.0")
    path = repo_root / "skills" / "demo" / FLOORED_REL_PATH
    fact = ContractFact(
        kind="symbol",
        skill="demo",
        path=path,
        line=1,
        module="traigent.utils.exceptions",
        symbol="ThisSymbolDoesNotExistAtAnyReleasedVersion",
    )
    config = _FakeConfig("0.99.0")  # exactly the declared floor

    # The floor does not exclude this fact from the 0.99.0 bucket...
    assert _python_version_floor_ok(fact.skill, fact.path, sync_map, config, repo_root)

    # ...and verification (unchanged by this feature) still catches the dead
    # teaching. A wrongly-declared floor cannot silence a real failure.
    with pytest.raises(AssertionError, match="symbol missing"):
        verify_python_fact(fact, repo_root=repo_root, sdk_version="0.99.0")


def test_bogus_import_floored_anywhere_still_fails_at_its_own_floor(
    repo_root: Path,
) -> None:
    sync_map = _floored_sync_map("0.99.0")
    path = repo_root / "skills" / "demo" / FLOORED_REL_PATH
    fact = ContractFact(
        kind="import",
        skill="demo",
        path=path,
        line=1,
        module="traigent.this_module_does_not_exist_anywhere",
    )
    config = _FakeConfig("0.99.0")

    assert _python_version_floor_ok(fact.skill, fact.path, sync_map, config, repo_root)

    with pytest.raises(AssertionError, match="module not found"):
        verify_python_fact(fact, repo_root=repo_root, sdk_version="0.99.0")


def test_real_symbol_floored_and_checked_passes(repo_root: Path) -> None:
    """Positive control: a genuinely-real symbol floored at a version that has
    already shipped it is checked (not skipped) and passes."""
    sync_map = _floored_sync_map("0.15.0")
    path = repo_root / "skills" / "demo" / FLOORED_REL_PATH
    fact = ContractFact(
        kind="symbol",
        skill="demo",
        path=path,
        line=1,
        module="traigent.utils.exceptions",
        symbol="ConfigurationError",
    )
    config = _FakeConfig("0.23.0")

    assert _python_version_floor_ok(fact.skill, fact.path, sync_map, config, repo_root)
    verify_python_fact(fact, repo_root=repo_root, sdk_version="0.23.0")  # no raise


# ---------------------------------------------------------------------------
# 3. Prose requirement: a floored file must state the version requirement.
# ---------------------------------------------------------------------------


def test_python_floored_files_state_required_sdk_in_prose(
    repo_root: Path, sync_map: dict
) -> None:
    from .test_text_requirements import _scan_missing_python_floor_prose

    violations: list[str] = []
    for skill, entry in (sync_map.get("skills") or {}).items():
        # Key presence + type, not `or {}` -- the same shape fixed twice
        # already in this PR. Safe here only because the eager declaration
        # check runs first, and "safe because something else catches it" is
        # how the other two survived.
        entry = entry or {}
        if "python_version_floors" not in entry:
            continue
        floors = entry["python_version_floors"]
        assert isinstance(floors, dict), (
            f"{skill}: python_version_floors must be a mapping, got {type(floors).__name__}"
        )
        for rel_path, floor in floors.items():
            doc_path = repo_root / "skills" / skill / rel_path
            violations.extend(
                _scan_missing_python_floor_prose(skill, rel_path, doc_path, floor)
            )
    assert not violations, "\n".join(violations)


# ---------------------------------------------------------------------------
# 4. list_buckets.py must keep deriving buckets only from min_sdk_version —
#    a python_version_floors entry must never grow the installed bucket set.
# ---------------------------------------------------------------------------


def test_list_buckets_ignores_python_version_floors(
    tmp_path: Path, repo_root: Path
) -> None:
    # Copy the real script verbatim: this also proves the script itself was
    # not touched to read python_version_floors.
    script_src = repo_root / "tools" / "contract" / "list_buckets.py"
    tool_dir = tmp_path / "tools" / "contract"
    tool_dir.mkdir(parents=True)
    (tool_dir / "list_buckets.py").write_text(
        script_src.read_text(encoding="utf-8"), encoding="utf-8"
    )

    sync_map = {
        "default_min_sdk_version": "0.15.0",
        "current_released_sdk_version": "0.23.0",
        "skills": {
            "demo": {
                "min_sdk_version": "0.16.0",
                "python_version_floors": {
                    # Wildly different from any real floor — if list_buckets.py
                    # ever started reading this key, it would show up below.
                    "references/unreleased.md": "0.99.0",
                },
            },
            "other-demo": {},
        },
    }
    (tmp_path / "sync_map.yml").write_text(
        yaml.safe_dump(sync_map), encoding="utf-8"
    )

    output = subprocess.check_output(
        [sys.executable, str(tool_dir / "list_buckets.py")],
        cwd=tmp_path,
        text=True,
    )
    buckets = [line for line in output.splitlines() if line]

    assert buckets == ["0.15.0", "0.16.0", "0.23.0"]
    assert "0.99.0" not in buckets
    assert buckets == sorted(set(buckets), key=Version)


# ---------------------------------------------------------------------------
# 5. End-to-end: a real, isolated pytest run (not just direct calls to the
#    gating function) proves the wiring in pytest_generate_tests — below the
#    floor the bogus fact isn't even collected; at the floor it is collected
#    and fails.
# ---------------------------------------------------------------------------

_HARNESS_FILES = (
    "__init__.py",
    "conftest.py",
    "extract.py",
    "facts.py",
    "verifier.py",
    "test_python_contracts.py",
)


def _build_synthetic_harness(tmp_path: Path, repo_root: Path, floor: str) -> Path:
    """A minimal, isolated copy of the real harness plus one skill whose only
    fact is a symbol that will never exist. ``conftest.py``/``extract.py``
    locate the repo root by directory depth (``parents[2]`` from
    ``tests/contract/conftest.py``), so copying the harness into
    ``tmp_path/tests/contract/`` makes it self-contained — no monkeypatching.
    """
    contract_dir = tmp_path / "tests" / "contract"
    contract_dir.mkdir(parents=True)
    for name in _HARNESS_FILES:
        (contract_dir / name).write_text(
            (repo_root / "tests" / "contract" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    skill_dir = tmp_path / "skills" / "demo"
    references_dir = skill_dir / "references"
    references_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Demo skill\n", encoding="utf-8")
    (references_dir / "unreleased.md").write_text(
        f"# Unreleased feature\n\n"
        f"Requires `traigent>={floor}` for this API.\n\n"
        "```python\n"
        "from traigent.utils.exceptions import "
        "ThisSymbolDoesNotExistAtAnyReleasedVersion\n"
        "```\n",
        encoding="utf-8",
    )

    sync_map = {
        "sdk": {"dist": "traigent"},
        "default_min_sdk_version": "0.15.0",
        "skills": {
            "demo": {"python_version_floors": {"references/unreleased.md": floor}}
        },
    }
    (tmp_path / "sync_map.yml").write_text(
        yaml.safe_dump(sync_map), encoding="utf-8"
    )
    return tmp_path


def _run_synthetic_pytest(tmp_path: Path, sdk_version: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/contract/test_python_contracts.py",
            f"--sdk-version={sdk_version}",
            "-v",
            "-p",
            "no:cacheprovider",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )


def test_end_to_end_floor_excludes_fact_below_floor(
    tmp_path: Path, repo_root: Path
) -> None:
    harness = _build_synthetic_harness(tmp_path, repo_root, floor="0.99.0")
    result = _run_synthetic_pytest(harness, sdk_version="0.23.0")  # below the floor
    # Empty parametrization for the floored fact -> pytest skips (no failure),
    # and the fact's own id never shows up (it was never collected).
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 skipped" in result.stdout
    assert "unreleased.md" not in result.stdout


def test_end_to_end_floor_includes_and_fails_at_floor(
    tmp_path: Path, repo_root: Path
) -> None:
    harness = _build_synthetic_harness(tmp_path, repo_root, floor="0.99.0")
    result = _run_synthetic_pytest(harness, sdk_version="0.99.0")  # at the floor
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed" in result.stdout
    assert "unreleased.md" in result.stdout
    assert "symbol missing" in result.stdout


def test_end_to_end_floor_includes_and_fails_above_floor(
    tmp_path: Path, repo_root: Path
) -> None:
    harness = _build_synthetic_harness(tmp_path, repo_root, floor="0.99.0")
    result = _run_synthetic_pytest(harness, sdk_version="1.0.0")  # above the floor
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed" in result.stdout


def test_real_sync_map_list_buckets_output(repo_root: Path, sync_map: dict) -> None:
    """Baseline snapshot of the real repo's bucket list, independent of any
    python_version_floors entries (there are none checked in), so a reviewer
    running ``list_buckets.py`` before/after adding one can diff against this.
    """
    output = subprocess.check_output(
        [sys.executable, str(repo_root / "tools/contract/list_buckets.py")],
        cwd=repo_root,
        text=True,
    )
    buckets = [line for line in output.splitlines() if line]
    expected = sorted(
        {str(sync_map["default_min_sdk_version"]), str(sync_map["current_released_sdk_version"])}
        | {
            str(entry["min_sdk_version"])
            for entry in (sync_map.get("skills") or {}).values()
            if isinstance(entry, dict) and entry.get("min_sdk_version")
        },
        key=Version,
    )
    assert buckets == expected


# --- terra review: a floor must not be able to suppress a whole skill --------


class _Cfg:
    def __init__(self, version: str) -> None:
        self._version = version

    def getoption(self, name: str):  # noqa: ANN201 - pytest.Config duck type
        return self._version if name == "--sdk-version" else None


def _floors(key: str, floor: str) -> dict:
    return {"skills": {"demo": {"python_version_floors": {key: floor}}}}


@pytest.mark.parametrize(
    "key",
    [
        "SKILL.md",  # most python facts live here -- would suppress the skill
        "references/a/b.md",  # nested, escapes the flat references contract
        "references/notes.txt",  # not markdown
        "provenance.json",
        "*",
    ],
)
def test_only_flat_reference_markdown_may_carry_a_floor(repo_root: Path, key: str) -> None:
    """A floor narrows ONE reference file, or it is refused.

    SKILL.md is the dangerous one: most of a skill's python facts live there,
    so accepting it would be a whole-skill wildcard spelled differently --
    exactly what this mechanism must not provide.
    """
    path = repo_root / "skills" / "demo" / key if key else repo_root / "skills" / "demo"
    with pytest.raises(AssertionError, match="not allowed"):
        _python_version_floor_ok("demo", path, _floors(key, "0.99.0"), _Cfg("0.23.0"), repo_root)


def test_a_malformed_floor_is_refused_not_silently_ignored(repo_root: Path) -> None:
    """A declaration that cannot be enforced is a defect, not a default.

    Returning "check everywhere" was safe but silent: the entry looked
    effective and did nothing, and prose like "Requires traigent>=next" would
    satisfy the prose lint.
    """
    path = repo_root / "skills" / "demo" / "references" / "x.md"
    with pytest.raises(AssertionError, match="not a valid PEP 440 version"):
        _python_version_floor_ok(
            "demo", path, _floors("references/x.md", "next"), _Cfg("0.23.0"), repo_root
        )


def test_a_valid_reference_floor_still_works(repo_root: Path) -> None:
    """The restriction must not break the case the feature exists for."""
    path = repo_root / "skills" / "demo" / "references" / "x.md"
    sync_map = _floors("references/x.md", "0.99.0")

    assert not _python_version_floor_ok("demo", path, sync_map, _Cfg("0.23.0"), repo_root)
    assert _python_version_floor_ok("demo", path, sync_map, _Cfg("0.99.0"), repo_root)
    assert _python_version_floor_ok("demo", path, sync_map, _Cfg("develop"), repo_root)


def test_a_key_that_matches_nothing_is_harmless(repo_root: Path) -> None:
    """An unmatched key admits the fact -- it cannot silence anything.

    An empty or nonsense key never equals a computed skill-relative path, so
    the lookup misses and the fact is CHECKED. That is the safe direction, and
    it is why the refusal above only fires for keys that would actually match.
    """
    path = repo_root / "skills" / "demo" / "references" / "x.md"
    for key in ("", "   ", "nope"):
        assert _python_version_floor_ok(
            "demo", path, _floors(key, "0.99.0"), _Cfg("0.23.0"), repo_root
        ), f"key {key!r} should admit (check), not exclude"


@pytest.mark.parametrize("selected", ["0.23.0", "develop"])
def test_a_malformed_floor_is_refused_in_every_bucket(repo_root: Path, selected: str) -> None:
    """Including develop -- the bucket that actually gates pull requests.

    Validating after the develop short-circuit meant a typo'd floor passed
    develop-contracts silently and only surfaced in a released bucket later.
    """
    path = repo_root / "skills" / "demo" / "references" / "x.md"
    with pytest.raises(AssertionError, match="not a valid PEP 440 version"):
        _python_version_floor_ok(
            "demo", path, _floors("references/x.md", "next"), _Cfg(selected), repo_root
        )


# --- sol escalation: validate every DECLARATION once, not lazily per fact ----


def test_every_declared_python_floor_is_well_formed(repo_root: Path) -> None:
    """Validate all `python_version_floors` in the real sync_map, eagerly.

    `_python_version_floor_ok` only validates a key when a fact happens to
    resolve to it. An entry naming a file that no longer exists, or carrying a
    value nobody parses, therefore sits inert until something coincidentally
    lands on it -- which for a mechanism whose whole job is to narrow checking
    is the wrong direction to fail.

    This walks every declaration once so a bad entry fails immediately and by
    itself, regardless of which facts exist.
    """
    sync_map = yaml.safe_load((repo_root / "sync_map.yml").read_text(encoding="utf-8"))
    problems: list[str] = []

    for skill, entry in (sync_map.get("skills") or {}).items():
        entry = entry or {}
        if "python_version_floors" not in entry:
            continue
        floors = entry["python_version_floors"]
        if not isinstance(floors, dict):
            problems.append(
                f"{skill}: python_version_floors must be a mapping, "
                f"got {type(floors).__name__}"
            )
            continue
        for key, floor in floors.items():
            if not _is_floorable_key(str(key)):
                problems.append(
                    f"{skill}: floor key {key!r} is not a flat references/<name>.md"
                )
                continue
            if not (repo_root / "skills" / skill / key).is_file():
                problems.append(f"{skill}: floor key {key!r} names a file that does not exist")
            if not isinstance(floor, str):
                problems.append(
                    f"{skill}: floor for {key!r} must be a version STRING, got {type(floor).__name__}"
                )
                continue
            try:
                Version(floor)
            except InvalidVersion:
                problems.append(f"{skill}: floor {floor!r} for {key!r} is not valid PEP 440")

    assert not problems, "\n".join(problems)


def test_the_declaration_check_has_teeth(repo_root: Path, tmp_path: Path) -> None:
    """The eager check must actually reject each bad declaration shape."""
    bad_cases = [
        ({"SKILL.md": "0.27.0"}, "not a flat references"),
        ({"references/does-not-exist.md": "0.27.0"}, "does not exist"),
        ({"references/cold-start.md": 0}, "must be a version STRING"),
        ({"references/cold-start.md": "next"}, "not valid PEP 440"),
    ]
    for floors, expected in bad_cases:
        problems: list[str] = []
        for key, floor in floors.items():
            if not _is_floorable_key(str(key)):
                problems.append(f"demo: floor key {key!r} is not a flat references/<name>.md")
                continue
            if not (repo_root / "skills" / "demo" / key).is_file():
                problems.append(f"demo: floor key {key!r} names a file that does not exist")
            if not isinstance(floor, str):
                problems.append(f"demo: floor for {key!r} must be a version STRING")
                continue
            try:
                Version(floor)
            except InvalidVersion:
                problems.append(f"demo: floor {floor!r} for {key!r} is not valid PEP 440")
        assert any(expected in p for p in problems), f"{floors} should have been rejected"


@pytest.mark.parametrize("falsy", ["", None, False, [], {}])
@pytest.mark.parametrize("selected", ["0.23.0", "develop"])
def test_a_present_but_falsy_floor_is_refused(
    repo_root: Path, falsy: object, selected: str
) -> None:
    """A declared-but-empty floor must not slip past validation.

    The lookup used `if not floor: return True`, so a present-but-falsy value
    took the "no floor declared here" path and skipped validation entirely.
    It could not make a failing fact pass -- it admits the fact everywhere --
    but the entry was silently inert, which is precisely what this mechanism
    is not allowed to be. The lookup now tests `key not in floors`.
    """
    path = repo_root / "skills" / "demo" / "references" / "x.md"
    with pytest.raises(AssertionError):
        _python_version_floor_ok(
            "demo",
            path,
            {"skills": {"demo": {"python_version_floors": {"references/x.md": falsy}}}},
            _Cfg(selected),
            repo_root,
        )


@pytest.mark.parametrize("bad_container", [[], "", False, None, 0, "nope", 3])
def test_a_malformed_floors_CONTAINER_is_refused(repo_root: Path, bad_container: object) -> None:
    """The same defect one level up: validate the container before normalising it.

    `floors = ... or {}` turned a present-but-falsy declaration
    (`python_version_floors: []`) into an empty dict, so a malformed
    DECLARATION read as "none declared here" — the outer twin of the
    per-value truthiness bug. Key presence first, then type.
    """
    path = repo_root / "skills" / "demo" / "references" / "x.md"
    with pytest.raises(AssertionError, match="must be a mapping"):
        _python_version_floor_ok(
            "demo",
            path,
            {"skills": {"demo": {"python_version_floors": bad_container}}},
            _Cfg("0.23.0"),
            repo_root,
        )


def test_an_absent_floors_key_is_still_fine(repo_root: Path) -> None:
    """Declaring nothing must stay free — only a malformed declaration is refused."""
    path = repo_root / "skills" / "demo" / "references" / "x.md"
    assert _python_version_floor_ok(
        "demo", path, {"skills": {"demo": {}}}, _Cfg("0.23.0"), repo_root
    )
