"""Equivalent task answers do not prove a scorer broken; ties still need attention."""

from pathlib import Path

import pytest
from conftest import run_tier2
from test_next_step import _gold_dataset, _run, _variant
from tier2_fake_backend import RUN_ID

CASES = {
    "text": (
        lambda i: ["Paris", "paris"][i % 2],
        "def score(output, expected):\n"
        "    return float(output.casefold().strip() == expected.casefold().strip())\n",
    ),
    "number": (
        lambda i: [3.14, 3.141][i % 2],
        "def score(output, expected):\n"
        "    return float(abs(output - expected) < 0.01)\n",
    ),
    "object": (
        lambda i: {"id": i, "category": "billing"},
        "def score(output, expected):\n"
        "    return float(output['category'] == expected['category'])\n",
    ),
    "constant": (
        lambda i: f"city {i}",
        "def score(output, expected):\n    return 1.0\n",
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_tied_probe_retains_attention_without_claiming_a_proven_bad_answer(
    case: str, tmp_path: Path
) -> None:
    gold, scorer = CASES[case]
    root = _variant(tmp_path, scorer)
    _gold_dataset(root, gold)
    report, card = _run(root, tmp_path)
    assert report["scorer_probe"]["scores"]["good"] == [1.0] * 5
    assert report["scorer_probe"]["scores"]["bad"] == [1.0]
    assert report["areas"]["scorer"]["status"] == "attention"
    assert report["next_step"]["branch"] == "d"
    assert "task-verified incorrect answer" in report["next_step"]["line"]
    assert "contrast candidate" in card
    assert "may be equivalent for this task" in card
    assert "returns different numbers for the same pair" not in card
    assert "known-bad" not in card
    assert "all check out" not in card
    tier2 = run_tier2("--from-audit", str(tmp_path / "report.json"), "--run-id", RUN_ID)
    assert tier2.returncode == 0, tier2.stderr
    evaluator = tier2.stdout.split("APPROVAL CARD — evaluator-quality", 1)[1]
    evaluator = evaluator.split("APPROVAL CARD", 1)[0]
    assert "contrast candidate" in evaluator
    assert "task-verified incorrect answer" in evaluator
    assert "NOT reliable" not in evaluator


def test_a_nonconstant_scorer_with_a_separated_candidate_still_passes(
    tmp_path: Path,
) -> None:
    root = _variant(
        tmp_path,
        "def score(output, expected):\n    return float(output == expected)\n",
    )
    _gold_dataset(root, lambda i: f"city {i}")
    report, _ = _run(root, tmp_path)
    assert report["scorer_probe"]["scores"]["bad"] == [0.0]
    assert report["areas"]["scorer"]["status"] == "ok"
    assert report["next_step"]["branch"] == "g"


def test_a_partial_ordering_failure_is_described_without_a_false_pair_claim(
    tmp_path: Path,
) -> None:
    root = _variant(
        tmp_path,
        "def score(output, expected):\n"
        "    if output == expected:\n        return 1.0\n"
        "    return 2.0 if output == 'city' else 0.0\n",
    )
    _gold_dataset(root, lambda i: f"city {i}")
    report, card = _run(root, tmp_path)
    assert report["scorer_probe"]["scores"] == {
        "good": [1.0] * 5,
        "partial": [2.0],
        "bad": [0.0],
    }
    assert report["next_step"]["branch"] == "d"
    assert "expected probe ordering" in report["next_step"]["line"]
    assert "partial 2" in report["next_step"]["line"]
    assert "any partial probe's expected position" in report["next_step"]["line"]
    assert "task-verified probes still fail the expected ordering" in report["next_step"]["line"]
    assert "does not outrank the contrast candidate" not in card
    assert "returns different numbers for the same pair" not in card
