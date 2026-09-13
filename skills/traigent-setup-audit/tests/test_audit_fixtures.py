"""Per-fixture expected findings for the Tier 1 audit.

Each fixture project is a small, self-contained tree under ``tests/fixtures``.
They are pure standard library and are never imported by the audit: the agent
modules are read with ``ast``, and only ``scorer.py`` is executed, in the
guarded probe subprocess.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "audit_project.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run_audit(root: Path, out_dir: Path, *extra: str):
    report_path = out_dir / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--json",
            str(report_path),
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return report, completed.stdout


@pytest.fixture(scope="module")
def healthy(tmp_path_factory):
    return run_audit(FIXTURES / "healthy", tmp_path_factory.mktemp("healthy"))


@pytest.fixture(scope="module")
def weak(tmp_path_factory):
    return run_audit(FIXTURES / "weak", tmp_path_factory.mktemp("weak"))


@pytest.fixture(scope="module")
def bare(tmp_path_factory):
    return run_audit(FIXTURES / "bare", tmp_path_factory.mktemp("bare"))


# --------------------------------------------------------------------------
# healthy
# --------------------------------------------------------------------------


def test_healthy_agent_has_every_knob_read(healthy) -> None:
    report, _ = healthy
    assert report["areas"]["agent"]["status"] == "ok"
    entry = report["entry_points"][0]
    assert entry["function"] == "answer_question"
    assert {knob["name"]: knob["status"] for knob in entry["knobs"]} == {
        "model": "read",
        "temperature": "read",
        "top_k": "read",
    }


def test_healthy_dataset_meets_the_documented_minimums(healthy) -> None:
    report, _ = healthy
    dataset = report["datasets"][0]
    assert dataset["rows"] == 70
    assert dataset["splits"] == {"holdout": 30, "tune": 40}
    assert dataset["holdout_rows"] == 30
    assert dataset["holdout_overlap_rows"] == []
    assert dataset["missing_gold_rows"] == []
    assert dataset["duplicate_groups"] == []
    assert dataset["near_duplicate_pairs"] == []
    assert dataset["findings"] == []
    assert report["areas"]["dataset"]["status"] == "ok"


def test_healthy_scorer_is_repeatable_and_ordered(healthy) -> None:
    report, _ = healthy
    probe = report["scorer_probe"]
    assert probe["ran"] is True
    assert probe["payload_source"] == "dataset"
    assert len(set(probe["scores"]["good"])) == 1
    assert probe["scores"]["good"][0] > probe["scores"]["bad"][0]
    assert probe["errors"] == []
    assert report["areas"]["scorer"]["status"] == "ok"


def test_healthy_collects_model_ids_without_validating_them(healthy) -> None:
    report, card = healthy
    assert report["setup"]["model_ids_declared"] == [
        "claude-haiku-4-5-20251001",
        "gpt-4o-mini",
    ]
    assert "not validated here" in card


# --------------------------------------------------------------------------
# weak
# --------------------------------------------------------------------------


def test_weak_reports_the_knob_that_is_never_read_with_a_file_and_line(weak) -> None:
    report, card = weak
    knobs = {knob["name"]: knob for knob in report["entry_points"][0]["knobs"]}
    assert knobs["temperature"]["status"] == "declared, never read"
    assert knobs["temperature"]["file"] == "agent.py"
    assert knobs["temperature"]["line"] == 9
    assert knobs["model"]["status"] == "read"
    assert report["areas"]["agent"]["status"] == "attention"
    assert "agent.py:9" in card


def test_weak_dataset_findings_are_counted_evidence(weak) -> None:
    report, _ = weak
    dataset = report["datasets"][0]
    assert dataset["rows"] == 8
    assert dataset["missing_gold_rows"] == [6]
    assert dataset["duplicate_groups"] == [[0, 1]]
    assert dataset["splits"] == {}
    assert dataset["holdout_rows"] == 0
    findings = " | ".join(dataset["findings"])
    assert "8 rows is under the 10-row smoke minimum" in findings
    assert "1 row(s) carry no gold key" in findings
    assert "no split marker on any row" in findings
    assert report["areas"]["dataset"]["status"] == "attention"


def test_weak_scorer_is_reported_as_not_repeatable(weak) -> None:
    report, card = weak
    probe = report["scorer_probe"]
    assert probe["ran"] is True
    assert len(set(probe["scores"]["good"])) > 1
    assert report["areas"]["scorer"]["status"] == "attention"
    assert "different scores" in card


# --------------------------------------------------------------------------
# bare
# --------------------------------------------------------------------------


def test_bare_reports_what_was_searched_for_rather_than_what_is_absent(bare) -> None:
    report, card = bare
    for area in ("agent", "dataset", "scorer"):
        assert report["areas"][area]["status"] == "not-found"
    joined = " | ".join(
        item
        for area in ("agent", "dataset", "scorer")
        for item in report["areas"][area]["evidence"]
    )
    assert "searched for `@traigent.optimize` in 1 Python file(s), found none" in joined
    assert "found none" in joined
    assert "you do not have" not in card.lower()
    assert "you don't have" not in card.lower()


def test_bare_still_finds_the_provider_call_site(bare) -> None:
    report, _ = bare
    sites = report["llm_call_sites"]
    assert sites and sites[0]["function"] == "ask"
    assert sites[0]["providers"] == ["openai"]


def test_bare_runs_no_scorer_probe(bare) -> None:
    report, _ = bare
    assert report["scorer_probe"] is None


# --------------------------------------------------------------------------
# card shape, safety and exit codes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["healthy", "weak", "bare", "netscorer"])
def test_every_card_carries_the_four_areas_and_both_honesty_sections(
    name: str, tmp_path: Path
) -> None:
    _, card = run_audit(FIXTURES / name, tmp_path)
    for heading in ("## Agent — ", "## Dataset — ", "## Scorer — ", "## Setup — "):
        assert heading in card
    assert "## What code alone could not tell you" in card
    assert "## What this audit does not establish" in card
    assert "No lift is promised." in card


@pytest.mark.parametrize("name", ["healthy", "weak", "bare", "netscorer"])
def test_every_run_reports_the_guard_as_active(name: str, tmp_path: Path) -> None:
    report, card = run_audit(FIXTURES / name, tmp_path)
    assert report["network_guard"] == "active"
    assert "`network_guard: active`" in card


def test_a_key_value_never_reaches_the_card_or_the_json(tmp_path: Path) -> None:
    """Canary: put a sentinel in a .env and assert only the NAME is reported."""
    sentinel = "canary-value-must-not-appear"
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / "healthy", root)
    (root / ".env").write_text(
        f"TRAIGENT_API_KEY={sentinel}\nOPENAI_API_KEY={sentinel}\n", encoding="utf-8"
    )
    report, card = run_audit(root, tmp_path / "out")
    assert sentinel not in card
    assert sentinel not in json.dumps(report)
    declared = report["setup"]["keys"]["names_declared_in_env_files"][".env"]
    assert declared == ["TRAIGENT_API_KEY", "OPENAI_API_KEY"]
    assert ".env" in card


def test_a_missing_root_is_a_usage_error(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path / "nope")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 2


def test_a_bad_scorer_selector_is_a_usage_error(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(FIXTURES / "healthy"),
            "--scorer",
            "scorer.py",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 2
    assert "FILE.py:FUNCTION" in completed.stderr


def test_an_explicit_scorer_selector_is_honoured(tmp_path: Path) -> None:
    report, _ = run_audit(
        FIXTURES / "healthy",
        tmp_path,
        "--scorer",
        "scorer.py:score",
        "--repeats",
        "3",
    )
    assert report["scorer_probe"]["ran"] is True
    assert len(report["scorer_probe"]["scores"]["good"]) == 3


def test_an_explicit_dataset_is_honoured(tmp_path: Path) -> None:
    report, _ = run_audit(
        FIXTURES / "weak",
        tmp_path,
        "--dataset",
        str(FIXTURES / "healthy" / "dataset.jsonl"),
    )
    assert len(report["datasets"]) == 1
    assert report["datasets"][0]["rows"] == 70


def test_the_report_carries_the_thresholds_it_judged_against(healthy) -> None:
    report, _ = healthy
    assert report["dataset_minimums"] == {
        "smoke_check": 10,
        "first_tuning_slice": 30,
        "holdout_slice": 30,
        "high_variance_task": 100,
        "source": "skills/traigent-dataset-curate/SKILL.md",
    }
