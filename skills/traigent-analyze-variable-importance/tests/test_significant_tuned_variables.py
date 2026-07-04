from __future__ import annotations

import csv
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "significant_tuned_variables.py"
)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def run_cli(
    trials: Path, output_dir: Path, *extra: str
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--trials",
        str(trials),
        "--objective",
        "accuracy",
        "--top-k",
        "4",
        "--confidence",
        "0.9",
        "--output-dir",
        str(output_dir),
        *extra,
    ]
    return subprocess.run(command, check=True, text=True, capture_output=True)


def synthetic_trials(count: int) -> list[dict]:
    rows = []
    for index in range(count):
        dominant = "strong" if index % 2 == 0 else "weak"
        secondary = "blue" if index % 4 in (0, 1) else "green"
        nuisance = "left" if index % 3 == 0 else "right"
        accuracy = 0.9 if dominant == "strong" else 0.4
        if secondary == "blue":
            accuracy += 0.02
        rows.append(
            {
                "trial_index": index,
                "accuracy": accuracy,
                "mock_cost": 0.01 + (0.002 if dominant == "strong" else 0.0),
                "correct": int(round(accuracy * 100)),
                "total": 100,
                "config": {
                    "dominant_knob": dominant,
                    "secondary_knob": secondary,
                    "nuisance_knob": nuisance,
                },
            }
        )
    return rows


def test_dominant_knob_ranks_first_and_is_significant_with_enough_trials(
    tmp_path: Path,
) -> None:
    trials_path = tmp_path / "trials.jsonl"
    output_dir = tmp_path / "out"
    write_jsonl(trials_path, synthetic_trials(80))

    run_cli(trials_path, output_dir)

    ranking = json.loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    assert ranking[0]["knob"] == "dominant_knob"
    assert ranking[0]["label"] == "significant"
    assert ranking[0]["ci_low"] > 0


def test_dominant_knob_is_directional_with_few_trials(tmp_path: Path) -> None:
    trials_path = tmp_path / "few_trials.jsonl"
    output_dir = tmp_path / "out"
    write_jsonl(trials_path, synthetic_trials(8))

    run_cli(trials_path, output_dir)

    ranking = json.loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    assert ranking[0]["knob"] == "dominant_knob"
    assert ranking[0]["label"] == "directional"


def test_outputs_are_written_and_parseable(tmp_path: Path) -> None:
    trials_path = tmp_path / "trials.jsonl"
    output_dir = tmp_path / "out"
    write_jsonl(trials_path, synthetic_trials(80))

    run_cli(trials_path, output_dir, "--slice-label", "this fixed Spider slice")

    expected = {
        "importance.json",
        "importance.csv",
        "significant_variables.svg",
        "insights.md",
        "video_card.json",
    }
    assert expected == {path.name for path in output_dir.iterdir()}

    ranking = json.loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    assert ranking[0]["knob"] == "dominant_knob"

    with (output_dir / "importance.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["knob"] == "dominant_knob"

    ET.parse(output_dir / "significant_variables.svg")
    assert "dominant_knob" in (output_dir / "significant_variables.svg").read_text(
        encoding="utf-8"
    )

    video_card = json.loads(
        (output_dir / "video_card.json").read_text(encoding="utf-8")
    )
    assert video_card["top_variables"][0]["knob"] == "dominant_knob"
    assert video_card["n_trials"] == 80
    assert "fixed Spider slice" in video_card["caption"]

    insights = (output_dir / "insights.md").read_text(encoding="utf-8")
    assert "Honesty rule" in insights
