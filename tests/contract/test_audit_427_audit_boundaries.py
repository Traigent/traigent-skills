"""Issue #427: setup-audit must state what it reads and when a receipt is durable."""

from __future__ import annotations

from pathlib import Path

SKILL = (
    Path(__file__).resolve().parents[2] / "skills" / "traigent-setup-audit" / "SKILL.md"
)


def test_no_blanket_claim_that_key_values_are_never_read() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "No key value is read" not in text
    assert "A key value is never read" not in text
    assert "read the text of the declared `.env`" in " ".join(text.split())


def test_receipt_file_is_described_as_optional() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "writes a receipt of every request and every process" not in text
    assert "every approved\n  run writes a receipt" not in text
    assert "only when you pass `--receipt <path>`" in " ".join(text.split())
    assert "written to disk only when `--receipt <path>` is passed" in text


def test_readme_matches_the_corrected_credential_read_disclosure() -> None:
    readme = " ".join((SKILL.parents[2] / "README.md").read_text(encoding="utf-8").split())
    assert "free local tier does not read credentials" not in readme
    assert "reads `.env` text in memory only to detect which key names are set" in readme
