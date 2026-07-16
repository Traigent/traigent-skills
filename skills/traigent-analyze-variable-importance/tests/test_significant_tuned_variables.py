from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "significant_tuned_variables.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("significant_tuned_variables", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register before exec so dataclass annotation resolution can find the module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def _trial(module, objective: float, config: dict, cost=None):
    return module.Trial(objective=objective, config=config, cost=cost, raw={})


def test_pure_noise_knob_is_not_labeled_significant() -> None:
    """Issue #230: a knob with zero real effect must not be called `significant`.

    Accuracy is drawn independently of the knob value, so the max-min spread is
    pure noise. The old gate (bootstrap CI lower bound of the non-negative spread
    > 0) fires on this; the permutation-null gate must label it `directional`.
    """
    module = _load_module()
    # Interleaved increasing objective with a round-robin knob assignment: groups
    # are near-balanced, so the ~2pp spread is an artifact of the interleave, not
    # a real effect. Deterministic (no RNG in the fixture) to stay non-flaky.
    trials = [
        _trial(module, 0.50 + 0.01 * i, {"noise_knob": ["a", "b", "c"][i % 3]})
        for i in range(30)
    ]

    row = module.analyze_knob(
        trials=trials,
        knob="noise_knob",
        confidence=0.9,
        bootstrap_draws=500,
        total_n=len(trials),
    )
    assert row is not None
    # The old gate would have misfired: the non-negative spread's CI clears 0 ...
    assert row.ci_low > 0.0
    # ... but the label-shuffled null shows the spread is ordinary noise.
    assert row.label == "directional"
    assert module.permutation_spread_pvalue(trials, "noise_knob", draws=500) > 0.1


def test_real_effect_knob_is_labeled_significant() -> None:
    """A knob that genuinely moves the objective still clears the null."""
    module = _load_module()
    trials = [
        _trial(module, 0.8 if i % 2 == 0 else 0.4, {"real_knob": "on" if i % 2 == 0 else "off"})
        for i in range(40)
    ]

    row = module.analyze_knob(
        trials=trials,
        knob="real_knob",
        confidence=0.9,
        bootstrap_draws=500,
        total_n=len(trials),
    )
    assert row is not None
    assert row.label == "significant"
    assert module.permutation_spread_pvalue(trials, "real_knob", draws=500) < 0.1


def test_video_card_uses_per_knob_effect_not_run_level_delta(tmp_path: Path) -> None:
    """Issue #231: per-knob accuracy_pp is the knob's own effect, not the run delta."""
    module = _load_module()
    trials = []
    for i in range(30):
        schema = "linked" if i % 2 == 0 else "raw"
        style = ["terse", "verbose", "json"][i % 3]
        accuracy = (0.65 if schema == "linked" else 0.50) + (0.001 if style == "json" else 0.0)
        trials.append(_trial(module, accuracy, {"schema": schema, "style": style}, cost=0.02))

    rows = module.analyze_importance(
        trials=trials, config_space=None, confidence=0.9, bootstrap_draws=300
    )
    by_knob = {row.knob: row for row in rows}
    # Whole-run heldout delta is +18pp, unrelated to any single knob's spread.
    heldout = {
        "baseline": {"accuracy": 0.50},
        "optimized": {"accuracy": 0.68},
        "delta": {"accuracy": 0.18},
    }

    payload = module.write_video_card_json(
        path=tmp_path / "video_card.json",
        rows=rows,
        top_k=4,
        n_trials=len(trials),
        objective="accuracy",
        heldout=heldout,
    )

    top = {entry["knob"]: entry for entry in payload["top_variables"]}
    # Each knob reports its OWN spread, not the shared run-level +18.0.
    for knob, entry in top.items():
        assert entry["accuracy_pp"] == module.round_float(by_knob[knob].spread * 100.0)
        assert entry["accuracy_pp"] != 18.0
    # The 'schema' knob (real effect) must differ from 'style' (noise).
    assert top["schema"]["accuracy_pp"] != top["style"]["accuracy_pp"]
    # Run-level delta is preserved once, at card level.
    assert payload["heldout_accuracy_pp"] == 18.0
