from __future__ import annotations

from pathlib import Path

import pytest

from .extract import collect_file
from .facts import ContractFact
from .verifier import verify_docstamp_fact


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


def test_docstamp_contract_fact_matches_sdk_source(
    docstamp_fact: ContractFact,
    repo_root: Path,
    sdk_version_label: str,
) -> None:
    verify_docstamp_fact(
        docstamp_fact, repo_root=repo_root, sdk_version=sdk_version_label
    )


def test_docstamp_asserter_rejects_wrong_literal_fixture(tmp_path: Path) -> None:
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
