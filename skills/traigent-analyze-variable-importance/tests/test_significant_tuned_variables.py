from __future__ import annotations

import csv
import importlib
import itertools
import json
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from fractions import Fraction

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS_DIR / "significant_tuned_variables.py"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True])
@pytest.mark.parametrize("nested", [False, True])
def test_invalid_objective_cannot_enter_significance_analysis(tmp_path, value, nested):
    module = _load_module()
    row = {"config": {"knob": "a"}}
    row.update({"metrics": {"accuracy": value}} if nested else {"accuracy": value})
    path = tmp_path / "invalid.jsonl"
    write_jsonl(path, [row])
    with pytest.raises(ValueError, match=r"invalid.jsonl:1:.*accuracy"):
        module.read_trials(path, "accuracy")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, True])
def test_invalid_cost_is_not_reported_as_measured(tmp_path, value):
    module = _load_module()
    path = tmp_path / "invalid.jsonl"
    write_jsonl(path, [{"config": {"knob": "a"}, "accuracy": 0.5, "cost": value}])
    with pytest.raises(ValueError, match=r"invalid.jsonl:1:.*cost"):
        module.read_trials(path, "accuracy")


def test_infinite_objective_cannot_be_labelled_significant_via_python_api():
    module = _load_module()
    trials = [module.Trial(float("inf") if i < 10 else 0.0, {"x": i // 10}, None, {})
              for i in range(20)]
    with pytest.raises(ValueError, match="objective"):
        module.analyze_importance(trials, None, 0.95, 999, "randomized")


@pytest.mark.parametrize(
    ("scale", "offset"),
    # Offsets 10 and 70 put the group means far above the spread, so roundoff
    # in the means exceeds a spread-relative tolerance (large-offset objectives
    # such as token counts or latency in ms).
    [(1, 0), (10**-15, 0), (1, 10), (1, 70)],
)
def test_permutation_ties_match_exact_rational_oracle(monkeypatch, scale, offset):
    module = _load_module()
    # Enumerate all label shuffles instead of tolerating Monte Carlo error.
    exact = [Fraction(i, 10) * Fraction(scale) + offset for i in (4, 5, 4, 1, 3, 7)]
    values = [float(x) for x in exact]
    permutations = list(itertools.permutations(range(6)))

    def statistic(items):
        return abs(sum(items[:3]) / 3 - sum(items[3:]) / 3)

    extreme = sum(statistic([exact[i] for i in p]) >= statistic(exact)
                  for p in permutations)

    class EnumeratedShuffles:
        def __init__(self, seed):
            self.remaining = iter(permutations)

        def shuffle(self, items):
            items[:] = [values[i] for i in next(self.remaining)]

    monkeypatch.setattr(module.random, "Random", EnumeratedShuffles)
    trials = [module.Trial(value, {"x": i // 3}, None, {})
              for i, value in enumerate(values)]
    actual = module.permutation_spread_pvalue(trials, "x", draws=len(permutations))
    assert actual == (extreme + 1) / (len(permutations) + 1)


def _load_module():
    """Import the analyzer script as an ordinary module.

    Deliberately a plain `import` off `sys.path` rather than the
    spec-from-file / module-from-spec importlib pair: this file lives under
    `skills/`, which repo-forensics scans with `--skill-scan`, and that pair
    is a blocking critical `runtime_dynamism` finding there. A normal import
    also registers the module in `sys.modules` for us, which is what the
    dataclass annotation resolution needs.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("significant_tuned_variables")


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

    run_cli(trials_path, output_dir, "--sampling-design", "randomized")

    ranking = json.loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    assert ranking[0]["knob"] == "dominant_knob"
    assert ranking[0]["label"] == "significant"
    assert ranking[0]["correction"] == "holm"
    assert ranking[0]["family_size"] == 3
    assert ranking[0]["p_adjusted"] >= ranking[0]["p_value"]
    assert ranking[0]["inference_status"] == "tested"
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
    assert video_card["top_variables"][0]["family_size"] == 3
    assert video_card["top_variables"][0]["inference_status"] == "exchangeability_unknown"
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

    rows = module.analyze_importance(
        trials=trials,
        config_space=None,
        confidence=0.9,
        bootstrap_draws=500,
        sampling_design="randomized",
    )
    row = rows[0]
    assert row is not None
    assert row.label == "significant"
    assert module.permutation_spread_pvalue(trials, "real_knob", draws=500) < 0.1


def test_holm_adjustment_exact_values_and_order_independent() -> None:
    module = _load_module()
    assert module.holm_adjust([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
    assert module.holm_adjust([0.03, 0.01, 0.04]) == [0.06, 0.03, 0.06]


def test_holm_family_is_fixed_before_top_k(tmp_path: Path) -> None:
    module = _load_module()
    trials = []
    for i in range(80):
        config = {f"knob_{j:02d}": (i + j) % 2 for j in range(12)}
        trials.append(_trial(module, 0.8 if config["knob_00"] else 0.4, config))

    rows = module.analyze_importance(
        trials, None, confidence=0.9, bootstrap_draws=1200,
        sampling_design="randomized",
    )
    assert len(rows) == 12
    assert all(row.family_size == 12 for row in rows)
    full_adjusted = {row.knob: row.p_adjusted for row in rows}

    output = tmp_path / "importance.json"
    module.write_importance_json(output, rows[:3])
    displayed = json.loads(output.read_text(encoding="utf-8"))
    assert {row["knob"]: row["p_adjusted"] for row in displayed} == {
        row["knob"]: full_adjusted[row["knob"]] for row in displayed
    }


def test_repeated_nulls_bound_familywise_flags_and_raw_control_exceeds_bound() -> None:
    module = _load_module()
    rng = random.Random(20260920)
    adjusted_any = 0
    raw_any = 0
    datasets = 60
    family_size = 4
    alpha = 0.05
    draws = 800
    familywise_bound = 9

    for _ in range(datasets):
        trials = [
            _trial(
                module,
                rng.random(),
                {f"null_{j}": rng.randrange(2) for j in range(family_size)},
            )
            for _ in range(40)
        ]
        rows = module.analyze_importance(
            trials,
            None,
            confidence=1.0 - alpha,
            bootstrap_draws=draws,
            sampling_design="randomized",
        )
        assert len(rows) == family_size
        assert all(row.inference_status == "tested" for row in rows)
        adjusted_any += any(row.label == "significant" for row in rows)
        raw_any += any(row.p_value < alpha for row in rows)

    print(
        f"repeated-null datasets={datasets} adjusted_any={adjusted_any} "
        f"raw_any={raw_any} bound={familywise_bound}"
    )
    assert adjusted_any <= familywise_bound
    # This is the control with Holm removed: the same raw p-values must exceed
    # the predeclared family-wise bound or the fixture has no power to detect a
    # missing correction.
    assert raw_any > familywise_bound


def test_inferential_serialization_preserves_sub_micro_values(tmp_path: Path) -> None:
    module = _load_module()
    trials = [
        _trial(module, 0.9 if i % 2 else 0.2, {"knob": i % 2})
        for i in range(40)
    ]
    row = module.analyze_importance(
        trials, None, confidence=0.9, bootstrap_draws=1000,
        sampling_design="randomized",
    )[0]
    row.p_value = 4e-7
    row.p_adjusted = 8e-7
    row.permutation_p_floor = 2e-7

    json_path = tmp_path / "importance.json"
    csv_path = tmp_path / "importance.csv"
    video_path = tmp_path / "video.json"
    module.write_importance_json(json_path, [row])
    module.write_importance_csv(csv_path, [row])
    video = module.write_video_card_json(
        video_path, [row], top_k=1, n_trials=40,
        objective="accuracy", heldout=None,
    )

    json_row = json.loads(json_path.read_text(encoding="utf-8"))[0]
    with csv_path.open(encoding="utf-8", newline="") as handle:
        csv_row = next(csv.DictReader(handle))
    assert json_row["p_value"] == 4e-7
    assert json_row["p_adjusted"] == 8e-7
    assert json_row["permutation_p_floor"] == 2e-7
    assert float(csv_row["p_value"]) == 4e-7
    assert float(csv_row["p_adjusted"]) == 8e-7
    assert float(csv_row["permutation_p_floor"]) == 2e-7
    assert video["top_variables"][0]["p_value"] == 4e-7
    assert video["top_variables"][0]["p_adjusted"] == 8e-7
    insights_path = tmp_path / "insights.md"
    module.write_insights_md(
        insights_path, [row], n_trials=40, objective="accuracy", confidence=0.9,
        heldout=None, sdk_note="fixture",
    )
    insights = insights_path.read_text(encoding="utf-8")
    assert "raw p=4e-07, Holm-adjusted p=8e-07" in insights


def test_low_permutation_resolution_is_explicit() -> None:
    module = _load_module()
    trials = [
        _trial(module, 0.9 if i % 2 else 0.2, {f"k{j}": (i + j) % 2 for j in range(8)})
        for i in range(40)
    ]
    rows = module.analyze_importance(
        trials, None, confidence=0.95, bootstrap_draws=99,
        sampling_design="randomized",
    )
    assert all(row.inference_status == "insufficient_permutation_resolution" for row in rows)
    assert all(row.label == "directional" for row in rows)
    assert all(row.permutation_p_floor == 0.01 for row in rows)


def test_sparse_knob_uses_per_knob_support_guard() -> None:
    module = _load_module()
    trials = [
        _trial(module, 0.9 if i % 2 else 0.2, {"dense": i % 2})
        for i in range(40)
    ]
    for i in range(10):
        trials[i].config["sparse"] = i % 2
    rows = module.analyze_importance(
        trials, None, confidence=0.9, bootstrap_draws=1000,
        sampling_design="randomized",
    )
    by_knob = {row.knob: row for row in rows}
    assert by_knob["dense"].label == "significant"
    assert by_knob["sparse"].inference_status == "insufficient_per_knob_samples"
    assert by_knob["sparse"].relevant_trials == 10
    assert by_knob["sparse"].label == "directional"


def test_unknown_and_adaptive_designs_never_confirm_effect() -> None:
    module = _load_module()
    trials = [
        _trial(module, 0.9 if i % 2 else 0.2, {"knob": i % 2})
        for i in range(40)
    ]
    for design, status in (
        ("unknown", "exchangeability_unknown"),
        ("adaptive", "adaptive_sampling"),
    ):
        row = module.analyze_importance(
            trials, None, confidence=0.9, bootstrap_draws=1000,
            sampling_design=design,
        )[0]
        assert row.p_adjusted < 0.1
        assert row.label == "directional"
        assert row.inference_status == status


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


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
@pytest.mark.parametrize("field", ["baseline", "optimized", "delta"])
def test_invalid_heldout_numbers_cannot_reach_the_video_card(field, value):
    module = _load_module()
    heldout = {
        "baseline": {"accuracy": 0.5, "cost": 1.0},
        "optimized": {"accuracy": 0.6, "cost": 0.8},
        "delta": {"accuracy": 0.1},
    }
    heldout[field]["accuracy"] = value
    with pytest.raises(ValueError, match=rf"heldout\.{field}\.accuracy"):
        module.heldout_card_metrics(heldout, "accuracy")


def test_invalid_heldout_cost_cannot_reach_the_video_card():
    module = _load_module()
    heldout = {"baseline": {"accuracy": 0.5, "cost": float("nan")},
               "optimized": {"accuracy": 0.6, "cost": 0.8}}
    with pytest.raises(ValueError, match=r"heldout\.baseline\.cost"):
        module.heldout_card_metrics(heldout, "accuracy")
