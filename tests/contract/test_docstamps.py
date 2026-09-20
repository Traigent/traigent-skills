from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest
from packaging.version import InvalidVersion, Version

from .conftest import _docstamp_fact_in_bucket, skill_floor
from .extract import collect_file
from .facts import ContractFact
from .verifier import verify_docstamp_fact


class _FakeConfig:
    """Minimal stand-in for pytest.Config — only ``getoption`` is used.

    Same pattern as ``test_python_version_floors.py``'s ``_FakeConfig``.
    """

    def __init__(self, sdk_version: str | None) -> None:
        self._sdk_version = sdk_version

    def getoption(self, name: str) -> str | None:
        assert name == "--sdk-version"
        return self._sdk_version


@contextmanager
def _fake_module(tmp_path: Path, module_name: str, source: str) -> Iterator[None]:
    (tmp_path / f"{module_name}.py").write_text(source, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        yield
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(module_name, None)


def _verify_fixture_stamp(
    tmp_path: Path, module_name: str, stamp_body: str, source: str
) -> None:
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text(f"<!-- contract: {stamp_body} -->\n", encoding="utf-8")
    facts = collect_file("demo", skill_path)
    assert len(facts) == 1
    with _fake_module(tmp_path, module_name, source):
        verify_docstamp_fact(facts[0], repo_root=tmp_path, sdk_version="test")


def test_extractor_detects_html_docstamps(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        """# Demo

<!-- contract: path /api/v1/optimization/plan in traigent.analytics.optimization_plan @ SDK 0.21.1 -->
<!-- contract: literal "requires managed optimization" in traigent.config.types -->
<!-- contract: raises ConfigurationError in traigent.core.optimized_function -->
""",
        encoding="utf-8",
    )

    facts = collect_file("demo", path)
    assert (
        ContractFact(
            kind="docstamp",
            skill="demo",
            path=path,
            line=3,
            module="traigent.analytics.optimization_plan",
            target="/api/v1/optimization/plan",
            name="path",
            stamped_sdk_version="0.21.1",
        )
        in facts
    )
    assert (
        ContractFact(
            kind="docstamp",
            skill="demo",
            path=path,
            line=4,
            module="traigent.config.types",
            target="requires managed optimization",
            name="literal",
        )
        in facts
    )
    assert (
        ContractFact(
            kind="docstamp",
            skill="demo",
            path=path,
            line=5,
            module="traigent.core.optimized_function",
            target="ConfigurationError",
            name="raises",
        )
        in facts
    )


# Every one of these bodies looks close to a valid stamp but is not: each must produce a
# `malformed` fact (never silently zero facts — see test_malformed_stamp_fails_loud) so an
# author who mistypes a stamp gets a red test, not a check that quietly never ran.
MALFORMED_STAMP_BODIES = [
    pytest.param("raise ConfigurationError in traigent.x", id="raise-not-raises"),
    pytest.param(
        "literal requires managed optimization in traigent.config.types",
        id="unquoted-literal",
    ),
    pytest.param("path /some/path", id="missing-in-module"),
    pytest.param("path /some/path in os.path", id="module-not-traigent"),
    pytest.param(
        'literal "x" in traigent.config.types@SDK 0.21.0', id="at-sdk-no-space"
    ),
    pytest.param(
        'literal "x" in traigent.config.types @ sdk 0.21.0', id="lowercase-sdk"
    ),
    pytest.param(
        "raises pkg.ConfigurationError in traigent.x", id="qualified-exception-name"
    ),
    pytest.param("", id="empty-body"),
    pytest.param(
        'literal "x" in traigent @ SDK 0.21.0 @ SDK 0.22.0', id="double-at-sdk"
    ),
    pytest.param('literal "x" in traigent @ SDK banana', id="unparseable-version"),
]


@pytest.mark.parametrize("body", MALFORMED_STAMP_BODIES)
def test_malformed_stamp_produces_malformed_fact(tmp_path: Path, body: str) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(f"<!-- contract: {body} -->\n", encoding="utf-8")

    facts = collect_file("demo", path)
    assert len(facts) == 1, f"expected exactly one fact for body={body!r}, got {facts}"
    fact = facts[0]
    assert fact.kind == "docstamp"
    assert fact.name == "malformed"

    with pytest.raises(AssertionError) as exc_info:
        verify_docstamp_fact(fact, repo_root=tmp_path, sdk_version="test")
    assert "MALFORMED CONTRACT STAMP" in str(exc_info.value)


def test_malformed_stamp_split_across_lines_is_flagged(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        '<!-- contract: literal "x"\n     in traigent.config.types -->\n',
        encoding="utf-8",
    )
    facts = collect_file("demo", path)
    assert len(facts) == 1
    assert facts[0].name == "malformed"
    with pytest.raises(AssertionError, match="MALFORMED CONTRACT STAMP"):
        verify_docstamp_fact(facts[0], repo_root=tmp_path, sdk_version="test")


def test_unterminated_stamp_at_end_of_file_is_flagged(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        '<!-- contract: literal "x" in traigent.config.types', encoding="utf-8"
    )

    facts = collect_file("demo", path)

    assert len(facts) == 1
    assert facts[0].name == "malformed"
    assert "missing closing `-->`" in facts[0].target


def test_unterminated_stamp_does_not_consume_following_valid_stamp(
    tmp_path: Path,
) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        '<!-- contract: literal "x" in traigent.config.types '
        "<!-- contract: raises ConfigurationError in traigent.core.optimized_function -->\n",
        encoding="utf-8",
    )

    facts = collect_file("demo", path)

    assert [(fact.name, fact.line) for fact in facts] == [
        ("malformed", 1),
        ("raises", 1),
    ]


def test_unterminated_stamp_before_unrelated_closed_comment_is_flagged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        '<!-- contract: literal "x" in traigent.config.types\n'
        "<!-- unrelated comment -->\n",
        encoding="utf-8",
    )

    facts = collect_file("demo", path)

    assert len(facts) == 1
    assert facts[0].name == "malformed"
    assert "missing closing `-->`" in facts[0].target


def test_no_malformed_docstamps_in_repo(
    all_contract_facts: tuple[ContractFact, ...], repo_root: Path
) -> None:
    """Corpus lint: no malformed stamp is committed anywhere in skills/.

    Independent of the parametrized ``docstamp_fact`` bucket run — this fails even
    when a subset of tests is selected, so a mistyped stamp cannot slip in on a
    partial local run.
    """
    malformed = [
        fact
        for fact in all_contract_facts
        if fact.kind == "docstamp" and fact.name == "malformed"
    ]
    assert not malformed, "malformed contract stamp(s):\n" + "\n".join(
        f"  {fact.rel_path(repo_root)}:{fact.line}: {fact.target}" for fact in malformed
    )


def test_docstamp_contract_fact_matches_sdk_source(
    docstamp_fact: ContractFact,
    repo_root: Path,
    sdk_version_label: str,
) -> None:
    verify_docstamp_fact(
        docstamp_fact, repo_root=repo_root, sdk_version=sdk_version_label
    )


def test_docstamp_asserter_rejects_wrong_literal_fixture(tmp_path: Path) -> None:
    """Red-before-green proof (protocol A4): a dead literal claim goes red."""
    path = tmp_path / "SKILL.md"
    path.write_text(
        '<!-- contract: literal "definitely-not-present-docstamp-fixture" in traigent -->\n',
        encoding="utf-8",
    )
    facts = collect_file("demo", path)
    assert len(facts) == 1

    with pytest.raises(AssertionError) as exc_info:
        verify_docstamp_fact(facts[0], repo_root=tmp_path, sdk_version="test")

    message = str(exc_info.value)
    assert "DEAD TEACHING" in message
    assert "source literal missing" in message
    assert "definitely-not-present-docstamp-fixture" in message


def test_docstamp_asserter_rejects_wrong_path_fixture(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        "<!-- contract: path /api/v1/definitely-not-a-real-route in traigent -->\n",
        encoding="utf-8",
    )
    facts = collect_file("demo", path)
    assert len(facts) == 1

    with pytest.raises(AssertionError) as exc_info:
        verify_docstamp_fact(facts[0], repo_root=tmp_path, sdk_version="test")

    message = str(exc_info.value)
    assert "DEAD TEACHING" in message
    assert "source path string missing" in message


def test_docstamp_asserter_rejects_wrong_raises_fixture(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        "<!-- contract: raises DefinitelyNotARealException in traigent -->\n",
        encoding="utf-8",
    )
    facts = collect_file("demo", path)
    assert len(facts) == 1

    with pytest.raises(AssertionError) as exc_info:
        verify_docstamp_fact(facts[0], repo_root=tmp_path, sdk_version="test")

    message = str(exc_info.value)
    assert "DEAD TEACHING" in message
    assert "`raise DefinitelyNotARealException` missing" in message


def test_docstamp_asserter_ignores_docstring_only_matches(tmp_path: Path) -> None:
    """A claim that only matches inside a module docstring must go red.

    Regression proof for the review finding that the harness's own proof stamp
    was satisfied only by a module docstring while the real code built the
    string dynamically — docstrings are prose *about* the code, not the code.
    """
    # Module name must start with `traigent` — the stamp grammar requires it.
    module_name = "traigent_docstring_only_fixture"
    module_path = tmp_path / f"{module_name}.py"
    module_path.write_text(
        '"""This module handles /api/v1/only-in-the-docstring requests."""\n',
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        skill_path = tmp_path / "SKILL.md"
        skill_path.write_text(
            f"<!-- contract: path /api/v1/only-in-the-docstring in {module_name} -->\n",
            encoding="utf-8",
        )
        facts = collect_file("demo", skill_path)
        assert len(facts) == 1
        with pytest.raises(AssertionError, match="source path string missing"):
            verify_docstamp_fact(facts[0], repo_root=tmp_path, sdk_version="test")
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(module_name, None)


@pytest.mark.parametrize(
    ("stamp_body", "comment"),
    [
        (
            "path /api/v1/comment-only in traigent_comment_path_fixture",
            "# /api/v1/comment-only\n",
        ),
        (
            'literal "comment-only-literal" in traigent_comment_literal_fixture',
            "# comment-only-literal\n",
        ),
        (
            "raises ConfigurationError in traigent_comment_raises_fixture",
            "# raise ConfigurationError\n",
        ),
    ],
)
def test_docstamp_asserter_rejects_comment_only_matches(
    tmp_path: Path, stamp_body: str, comment: str
) -> None:
    module_name = stamp_body.split(" in ", maxsplit=1)[1]
    with pytest.raises(AssertionError, match="DEAD TEACHING"):
        _verify_fixture_stamp(tmp_path, module_name, stamp_body, comment)


@pytest.mark.parametrize(
    ("target", "source"),
    [
        ("value#fragment", 'VALUE = "value#fragment"\n'),
        ("https://example.test/#anchor", 'URL = "https://example.test/#anchor"\n'),
        ("prefix#", 'suffix = "suffix"\nVALUE = f"prefix#{suffix}"\n'),
        (
            "triple#quoted",
            'VALUE = """a multiline string with triple#quoted content"""\n',
        ),
    ],
)
def test_docstamp_asserter_preserves_hashes_in_real_string_literals(
    tmp_path: Path, target: str, source: str
) -> None:
    module_name = "traigent_hash_string_fixture"
    _verify_fixture_stamp(
        tmp_path,
        module_name,
        f'literal "{target}" in {module_name}',
        source,
    )


def test_docstamp_asserter_blanks_unicode_prefixed_multiline_docstring(
    tmp_path: Path,
) -> None:
    module_name = "traigent_unicode_docstring_fixture"
    source = 'PREFIX = "é"\n\ndef f():\n    """line one\n    docstring-only-value\n    """\n'
    with pytest.raises(AssertionError, match="source literal missing"):
        _verify_fixture_stamp(
            tmp_path,
            module_name,
            f'literal "docstring-only-value" in {module_name}',
            source,
        )


def test_docstamp_asserter_preserves_code_after_unicode_docstring(
    tmp_path: Path,
) -> None:
    module_name = "traigent_unicode_offset_fixture"
    source = 'def f():\n    """ééééé"""; value = "live-after-docstring"\n'
    _verify_fixture_stamp(
        tmp_path,
        module_name,
        f'literal "value = \\"live-after-docstring\\"" in {module_name}',
        source,
    )


def test_docstamp_asserter_fails_closed_on_malformed_package_source(
    tmp_path: Path,
) -> None:
    module_name = "traigent_malformed_source_fixture"
    package = tmp_path / module_name
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "broken.py").write_text('VALUE = "unterminated\n', encoding="utf-8")
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text(
        f'<!-- contract: literal "unterminated" in {module_name} -->\n',
        encoding="utf-8",
    )
    facts = collect_file("demo", skill_path)
    assert len(facts) == 1

    sys.path.insert(0, str(tmp_path))
    try:
        with pytest.raises(AssertionError, match="DOCSTAMP SOURCE UNVERIFIABLE"):
            verify_docstamp_fact(facts[0], repo_root=tmp_path, sdk_version="test")
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(module_name, None)


class TestDocstampFactInBucket:
    """Three-case proof of the per-stamp ``@ SDK`` floor (mirrors env facts)."""

    FACT = ContractFact(
        kind="docstamp",
        skill="demo",
        path=Path("SKILL.md"),
        line=1,
        module="traigent",
        target="x",
        name="literal",
        stamped_sdk_version="0.22.0",
    )

    def test_below_floor_is_excluded(self) -> None:
        assert _docstamp_fact_in_bucket(self.FACT, _FakeConfig("0.21.0")) is False

    def test_at_floor_is_included(self) -> None:
        assert _docstamp_fact_in_bucket(self.FACT, _FakeConfig("0.22.0")) is True

    def test_develop_bucket_always_included(self) -> None:
        assert _docstamp_fact_in_bucket(self.FACT, _FakeConfig("develop")) is True

    def test_no_floor_is_always_included(self) -> None:
        no_floor = ContractFact(
            kind="docstamp",
            skill="demo",
            path=Path("SKILL.md"),
            line=1,
            module="traigent",
            target="x",
            name="literal",
        )
        assert _docstamp_fact_in_bucket(no_floor, _FakeConfig("0.0.1")) is True


def test_docstamp_floor_not_below_skill_floor(
    all_contract_facts: tuple[ContractFact, ...], sync_map: dict, repo_root: Path
) -> None:
    """A stamp's ``@ SDK`` below the skill's own ``min_sdk_version`` is a no-op:
    every bucket that skill runs in is already at or above its floor, so the
    per-stamp floor never excludes anything and misleadingly reads as "verified
    at version X" when no such bucket is ever tested."""
    violations = []
    for fact in all_contract_facts:
        if fact.kind != "docstamp" or not fact.stamped_sdk_version:
            continue
        floor = skill_floor(sync_map, fact.skill)
        try:
            stamped, skill_min = Version(fact.stamped_sdk_version), Version(floor)
        except InvalidVersion:
            continue
        if stamped < skill_min:
            violations.append(
                f"{fact.rel_path(repo_root)}:{fact.line} @ SDK {fact.stamped_sdk_version}"
                f" is below {fact.skill}'s own min_sdk_version {floor} (a no-op floor)"
            )
    assert not violations, "\n".join(violations)
