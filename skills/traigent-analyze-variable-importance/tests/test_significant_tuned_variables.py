from __future__ import annotations

import csv
import importlib
import itertools
import json
import math
import os
import random
import re
import subprocess
import sys
import types
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


def _finite_float(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f"number literal {text!r} overflows to {number!r}")
    return number


def _reject_constant(token: str):
    raise ValueError(f"non-standard JSON constant {token!r}")


def strict_json_loads(text: str):
    """Parse as a strict consumer (a JS renderer, jq) would: no NaN/Infinity."""
    return json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float)


def stdout_card(stdout: str) -> dict:
    """The video card is the trailing JSON object on stdout, after the text summary."""
    return strict_json_loads(stdout[stdout.index("\n{\n") + 1 :])


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
        "sdk_cross_check.json",
    }
    assert expected == {path.name for path in output_dir.iterdir()}

    ranking = strict_json_loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    assert ranking[0]["knob"] == "dominant_knob"
    strict_json_loads((output_dir / "sdk_cross_check.json").read_text(encoding="utf-8"))

    with (output_dir / "importance.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["knob"] == "dominant_knob"

    ET.parse(output_dir / "significant_variables.svg")
    assert "dominant_knob" in (output_dir / "significant_variables.svg").read_text(
        encoding="utf-8"
    )

    video_card = strict_json_loads(
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


def test_non_completed_trials_are_skipped_not_scored_as_zero(tmp_path: Path) -> None:
    """Issue #312: a failed SDK trial carries accuracy 0.0 but no measurement."""
    trials_path = tmp_path / "trials.jsonl"
    output_dir = tmp_path / "out"
    write_jsonl(
        trials_path,
        [
            {"status": "completed", "config": {"model": "small"}, "metrics": {"accuracy": 0.5}},
            {"status": "completed", "config": {"model": "large"}, "metrics": {"accuracy": 1.0}},
            {"status": "failed", "config": {"model": "broken"}, "metrics": {"accuracy": 0.0}},
            {"status": "PRUNED", "config": {"model": "large"}, "metrics": {"accuracy": 0.1}},
        ],
    )

    completed = run_cli(trials_path, output_dir)

    ranking = json.loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    assert ranking[0]["knob"] == "model"
    assert ranking[0]["spread"] == 0.5
    assert ranking[0]["best_value"] == "large"
    assert "skipped 2 non-completed trial(s)" in completed.stdout
    video_card = json.loads((output_dir / "video_card.json").read_text(encoding="utf-8"))
    assert video_card["skipped_non_completed"] == 2
    assert video_card["n_trials"] == 2
    insights = (output_dir / "insights.md").read_text(encoding="utf-8")
    assert "2 non-completed trial(s)" in insights


def test_rows_without_status_are_read_as_before(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "trials.jsonl"
    write_jsonl(
        path,
        [
            {"config": {"k": "a"}, "accuracy": 0.0},
            {"config": {"k": "b"}, "metrics": {"accuracy": 1.0}},
        ],
    )
    trials, skipped = module.read_trial_file(path, "accuracy")
    assert [trial.objective for trial in trials] == [0.0, 1.0]
    assert skipped == 0
    assert module.read_trials(path, "accuracy") == trials


def test_only_non_completed_trials_is_an_explicit_error(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "trials.jsonl"
    write_jsonl(path, [{"status": "failed", "config": {"k": "a"}, "accuracy": 0.0}])
    with pytest.raises(ValueError, match=r"1 non-completed trial\(s\) skipped"):
        module.read_trials(path, "accuracy")


def _pure_noise_trials(module, seed: int) -> list:
    rng = random.Random(seed)
    return [
        _trial(module, rng.gauss(0.6, 0.08), {"noise": rng.randrange(3)})
        for _ in range(60)
    ]


def test_confidence_is_display_only_and_never_loosens_significance() -> None:
    """Issue #317 A: --confidence used to set alpha = 1 - confidence."""
    module = _load_module()
    hits = {0.5: 0, 0.9: 0}
    for seed in range(40):
        trials = _pure_noise_trials(module, seed)
        labels = {}
        for confidence in hits:
            row = module.analyze_importance(
                trials, None, confidence=confidence, bootstrap_draws=500,
                sampling_design="randomized",
            )[0]
            labels[confidence] = row.label
            hits[confidence] += row.label == "significant"
        assert labels[0.5] == labels[0.9], f"seed {seed}: confidence changed the label"
    # Default alpha 0.05 over 40 null datasets: expect ~2; 18/40 was the old
    # --confidence 0.5 behaviour.
    assert hits[0.5] == hits[0.9] <= 6, hits


def test_alpha_is_bounded_and_written_to_outputs(tmp_path: Path) -> None:
    trials_path = tmp_path / "trials.jsonl"
    write_jsonl(trials_path, synthetic_trials(80))

    run_cli(trials_path, tmp_path / "default")
    ranking = json.loads((tmp_path / "default" / "importance.json").read_text(encoding="utf-8"))
    assert {row["alpha"] for row in ranking} == {0.05}
    card = json.loads((tmp_path / "default" / "video_card.json").read_text(encoding="utf-8"))
    assert card["alpha"] == 0.05
    with (tmp_path / "default" / "importance.csv").open(encoding="utf-8", newline="") as handle:
        assert {row["alpha"] for row in csv.DictReader(handle)} == {"0.05"}

    run_cli(trials_path, tmp_path / "loose", "--alpha", "0.1")
    card = json.loads((tmp_path / "loose" / "video_card.json").read_text(encoding="utf-8"))
    assert card["alpha"] == 0.1

    for bad in ("0", "0.2", "0.5"):
        with pytest.raises(subprocess.CalledProcessError):
            run_cli(trials_path, tmp_path / f"bad{bad}", "--alpha", bad)


def _coupled_trials(module, seed: int) -> list:
    rng = random.Random(seed)
    rows = []
    for _ in range(60):
        m = rng.randrange(2)
        fewshot = rng.choice([4, 8]) if m else rng.choice([0, 0, 0, 4])
        rows.append(
            _trial(
                module,
                0.5 + 0.15 * m + rng.gauss(0, 0.08),
                {"model": ["cheap", "strong"][m], "fewshot": fewshot},
            )
        )
    return rows


def test_knob_coupled_to_another_knob_is_not_labelled_significant() -> None:
    """Issue #317 B: a no-effect knob tied to the model by a constrained space."""
    module = _load_module()
    for seed in range(40):
        rows = module.analyze_importance(
            _coupled_trials(module, seed), None, confidence=0.9,
            bootstrap_draws=500, sampling_design="randomized",
        )
        by_knob = {row.knob: row for row in rows}
        assert by_knob["fewshot"].label == "directional", seed
        assert by_knob["fewshot"].inference_status == "knobs_not_independent", seed


def test_independent_knobs_rarely_trip_the_dependence_screen() -> None:
    module = _load_module()
    rng = random.Random(317)
    flagged = 0
    datasets = 300
    for _ in range(datasets):
        knobs = [f"k{j}" for j in range(4)]
        trials = [
            _trial(module, 0.5, {knob: rng.randrange(3) for knob in knobs})
            for _ in range(60)
        ]
        flagged += bool(module.dependent_knobs(trials, knobs))
    # Simulated rate at the 0.001 per-pair level is about 0.5% for 6 pairs.
    assert flagged <= 0.03 * datasets, flagged


@pytest.mark.parametrize(
    ("statistic", "dof", "expected"),
    [
        (3.841458820694124, 1, 0.05),
        (5.991464547107979, 2, 0.05),
        (10.827566170662733, 1, 0.001),
        (16.918977604620448, 9, 0.05),
        (0.0, 3, 1.0),
    ],
)
def test_chi2_survival_matches_reference_quantiles(statistic, dof, expected) -> None:
    module = _load_module()
    assert module.chi2_survival(statistic, dof) == pytest.approx(expected, rel=1e-9, abs=1e-12)


def test_sdk_cross_check_claim_is_backed_by_an_output_file(tmp_path: Path) -> None:
    """Issue #317 C: the cross-check numbers must be inspectable.

    Skips (never passes vacuously) where the SDK analyzer cannot be imported.
    """
    pytest.importorskip("traigent.utils.importance")
    trials_path = tmp_path / "trials.jsonl"
    output_dir = tmp_path / "out"
    write_jsonl(trials_path, synthetic_trials(80))
    run_cli(trials_path, output_dir)

    insights = (output_dir / "insights.md").read_text(encoding="utf-8")
    cross_check = json.loads((output_dir / "sdk_cross_check.json").read_text(encoding="utf-8"))
    claims_computed = "variance-based output was computed" in insights
    assert claims_computed, "with the SDK installed, 80 trials must yield a cross-check"
    assert cross_check["computed"] is claims_computed
    assert bool(cross_check["results"]) is claims_computed
    assert ("## SDK cross-check" in insights) is claims_computed
    if claims_computed:
        for name, result in cross_check["results"].items():
            assert f"`{name}`" in insights
            assert set(result) >= {"importance_score", "confidence_interval", "sample_size"}


def test_insights_renders_sdk_cross_check_table(tmp_path: Path) -> None:
    module = _load_module()
    trials = [_trial(module, 0.9 if i % 2 else 0.2, {"knob": i % 2}) for i in range(40)]
    rows = module.analyze_importance(trials, None, confidence=0.9, bootstrap_draws=500)
    payload = {
        "knob": {
            "importance_score": 0.75,
            "confidence_interval": [0.5, 0.9],
            "method": "variance",
            "sample_size": 40,
        }
    }
    path = tmp_path / "insights.md"
    module.write_insights_md(
        path, rows, n_trials=40, objective="accuracy", confidence=0.9,
        heldout=None, sdk_note="computed", sdk_payload=payload,
    )
    text = path.read_text(encoding="utf-8")
    assert "## SDK cross-check" in text
    assert "| `knob` | 0.75 | [0.5, 0.9] | 40 |" in text


def _six_knob_factorial(count: int = 128) -> list[dict]:
    """Two replicates of a full 2^6 factorial: every knob exactly independent."""
    rows = []
    for index in range(count):
        config = {f"k{j}": (index >> j) & 1 for j in range(6)}
        # A real effect on k0 only, plus a small deterministic wobble.
        accuracy = (0.8 if config["k0"] else 0.4) + 0.01 * ((index * 7) % 5)
        rows.append({"accuracy": accuracy, "config": config})
    return rows


def test_default_draws_resolve_a_six_knob_family(tmp_path: Path) -> None:
    """Review of #317: at the default alpha the default draws must cover a 6-knob family."""
    trials_path = tmp_path / "trials.jsonl"
    output_dir = tmp_path / "out"
    write_jsonl(trials_path, _six_knob_factorial())
    subprocess.run(
        [
            sys.executable, str(SCRIPT), "--trials", str(trials_path),
            "--output-dir", str(output_dir), "--sampling-design", "randomized",
        ],
        check=True, text=True, capture_output=True,
    )
    ranking = json.loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    by_knob = {row["knob"]: row for row in ranking}
    assert by_knob["k0"]["family_size"] == 6
    assert by_knob["k0"]["inference_status"] == "tested"
    assert by_knob["k0"]["label"] == "significant"


def test_resolution_shortfall_names_the_draws_flag(tmp_path: Path) -> None:
    trials_path = tmp_path / "trials.jsonl"
    output_dir = tmp_path / "out"
    write_jsonl(trials_path, _six_knob_factorial())
    subprocess.run(
        [
            sys.executable, str(SCRIPT), "--trials", str(trials_path),
            "--output-dir", str(output_dir), "--sampling-design", "randomized",
            "--bootstrap-draws", "500",
        ],
        check=True, text=True, capture_output=True,
    )
    ranking = json.loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    assert {row["inference_status"] for row in ranking} == {
        "insufficient_permutation_resolution"
    }
    insights = (output_dir / "insights.md").read_text(encoding="utf-8")
    assert "--bootstrap-draws 1200" in insights


def test_worked_example_lists_every_randomized_condition() -> None:
    text = " ".join(
        (SCRIPTS_DIR.parent / "SKILL.md").read_text(encoding="utf-8").split()
    )
    assert "all three conditions" not in text
    assert "verifies all four conditions" in text
    assert "each knob was assigned independently of the others" in text


def _missing_objective_rows(objective: str, status: str | None) -> tuple[list[dict], list[dict]]:
    """30 eligible rows, 10 of them without ``objective``, plus 2 failed rows."""
    all_rows, measured = [], []
    for index in range(30):
        model = "strong" if index % 2 == 0 else "weak"
        row: dict = {"trial_index": index, "config": {"model": model, "temp": index % 3}}
        if status is not None:
            row["status"] = status
        if index % 3 == 2:
            # Every way the objective can be absent: no key, null at top level, null nested.
            absent = (index // 3) % 3
            if absent == 0:
                row["metrics"] = {"error_rate": 1.0}
            elif absent == 1:
                row[objective] = None
            else:
                row["metrics"] = {objective: None}
        else:
            # A measured zero is a measurement, not a missing objective.
            score = 0.0 if index == 0 else (0.8 if model == "strong" else 0.4) + 0.01 * (index % 5)
            row["metrics"] = {objective: score, "cost": 0.01}
            measured.append(row)
        all_rows.append(row)
    for _ in range(2):
        all_rows.append(
            {"status": "failed", "config": {"model": "strong", "temp": 0}, "metrics": {objective: 0.0}}
        )
    return all_rows, measured


@pytest.mark.parametrize("status", ["completed", None])
@pytest.mark.parametrize("objective", ["accuracy", "exec_accuracy"])
def test_missing_objective_count_reaches_every_report_surface(
    tmp_path: Path, status, objective
) -> None:
    """Issue #390: completed rows without the objective were dropped uncounted."""
    all_rows, measured = _missing_objective_rows(objective, status)
    write_jsonl(tmp_path / "all.jsonl", all_rows)
    write_jsonl(tmp_path / "measured.jsonl", measured)
    args = ("--objective", objective, "--bootstrap-draws", "200")

    completed = run_cli(tmp_path / "all.jsonl", tmp_path / "all", *args)
    run_cli(tmp_path / "measured.jsonl", tmp_path / "measured", *args)

    card = strict_json_loads((tmp_path / "all" / "video_card.json").read_text(encoding="utf-8"))
    assert card["n_trials"] == 20
    assert card["skipped_non_completed"] == 2
    assert card["skipped_missing_objective"] == 10
    assert stdout_card(completed.stdout) == card
    assert "skipped 2 non-completed trial(s)" in completed.stdout
    assert (
        "skipped 10 completed or status-unspecified trial(s) with no value for "
        f"objective '{objective}'"
    ) in completed.stdout
    insights = (tmp_path / "all" / "insights.md").read_text(encoding="utf-8")
    assert (
        "10 completed or status-unspecified trial(s) were skipped because they carry "
        f"no value for {objective}; the ranking rests on the remaining 20 measured trial(s)."
    ) in insights
    # Counting the skips leaves the statistics exactly as for the measured rows alone.
    assert (tmp_path / "all" / "importance.json").read_text(encoding="utf-8") == (
        tmp_path / "measured" / "importance.json"
    ).read_text(encoding="utf-8")


def test_card_reports_zero_missing_objective_and_legacy_readers_keep_shape(
    tmp_path: Path,
) -> None:
    module = _load_module()
    trials_path = tmp_path / "trials.jsonl"
    write_jsonl(trials_path, synthetic_trials(40))

    completed = run_cli(trials_path, tmp_path / "out", "--bootstrap-draws", "200")

    card = strict_json_loads((tmp_path / "out" / "video_card.json").read_text(encoding="utf-8"))
    assert card["skipped_missing_objective"] == 0
    assert list(card).index("skipped_missing_objective") == list(card).index("skipped_non_completed") + 1
    assert "with no value for objective" not in completed.stdout
    trials, skipped = module.read_trial_file(trials_path, "accuracy")
    assert skipped == 0
    assert module.read_trials(trials_path, "accuracy") == trials


def test_no_measured_trials_error_reports_both_skip_counts(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "trials.jsonl"
    write_jsonl(
        path,
        [
            {"status": "completed", "config": {"k": "a"}, "metrics": {"error_rate": 1.0}},
            {"status": "completed", "config": {"k": "b"}, "metrics": {"exec_accuracy": None}},
            {"config": {"k": "a"}, "exec_accuracy": None},
            {"status": "failed", "config": {"k": "b"}, "metrics": {"exec_accuracy": 0.0}},
        ],
    )
    with pytest.raises(ValueError) as excinfo:
        module.read_trials(path, "exec_accuracy")
    message = str(excinfo.value)
    assert "1 non-completed trial(s) skipped" in message
    assert (
        "3 completed or status-unspecified trial(s) with no value for 'exec_accuracy' skipped"
    ) in message


@pytest.mark.parametrize("count", [10, 30])
@pytest.mark.parametrize("with_heldout", [False, True])
def test_empty_ranking_card_and_svg_say_nothing_was_ranked(
    tmp_path: Path, count, with_heldout
) -> None:
    """Issue #390: all([]) made an empty ranking read 'directional only'."""
    trials_path = tmp_path / "trials.jsonl"
    write_jsonl(
        trials_path,
        [
            {"status": "completed", "accuracy": 0.5 + 0.01 * i, "config": {"model": "only"}}
            for i in range(count)
        ],
    )
    extra: list[str] = []
    if with_heldout:
        heldout = tmp_path / "heldout.json"
        heldout.write_text(
            json.dumps(
                {
                    "baseline": {"accuracy": 0.5},
                    "optimized": {"accuracy": 0.68},
                    "delta": {"accuracy": 0.18},
                }
            ),
            encoding="utf-8",
        )
        extra = ["--heldout", str(heldout)]
    output_dir = tmp_path / "out"

    completed = run_cli(trials_path, output_dir, *extra)

    assert "Wrote 0 ranked tuned variables" in completed.stdout
    card = strict_json_loads((output_dir / "video_card.json").read_text(encoding="utf-8"))
    assert card["top_variables"] == []
    caption = card["caption"]
    assert "no tuned variable could be ranked" in caption
    assert "directional only" not in caption
    assert "mixed confidence" not in caption
    # Genuine heldout context stays, as run-level context only.
    assert card["heldout_accuracy_pp"] == (18.0 if with_heldout else None)
    assert ("run-level heldout optimized-vs-baseline +18.00 pp" in caption) is with_heldout
    footer = [
        node.text or ""
        for node in ET.parse(output_dir / "significant_variables.svg").iter(
            "{http://www.w3.org/2000/svg}text"
        )
        if node.get("y") == "655"
    ]
    assert len(footer) == 1
    assert "no tuned variable could be ranked" in footer[0]
    assert "fewer than 20 trials" not in footer[0]
    assert "significant requires" not in footer[0]


NONFINITE_LITERALS = ["NaN", "Infinity", "-Infinity", "1e400"]


def _is_literal(value, literal: str) -> bool:
    if literal == "NaN":
        return isinstance(value, float) and math.isnan(value)
    return value == (-math.inf if literal.startswith("-") else math.inf)


@pytest.mark.parametrize("literal", NONFINITE_LITERALS)
@pytest.mark.parametrize(
    "config_template",
    ['{"model": "a", "temperature": @}', '{"model": "a", "temperature": {"limits": [0.1, @]}}'],
    ids=["scalar", "nested"],
)
@pytest.mark.parametrize(
    "row_tail",
    [
        '"status": "completed", "accuracy": 0.5',
        '"status": "failed", "accuracy": 0.0',
        '"status": "completed", "metrics": {}',
    ],
    ids=["completed", "failed", "missing-objective"],
)
def test_nonfinite_knob_values_are_read_as_given(
    tmp_path: Path, literal, config_template, row_tail
) -> None:
    """Issue #393: a NaN/Infinity knob value is a value, read like any other."""
    module = _load_module()
    path = tmp_path / "trials.jsonl"
    path.write_text(
        '{"config": {"model": "b", "temperature": 0.0}, "accuracy": 0.6}\n'
        "\n"
        f'{{"config": {config_template.replace("@", literal)}, {row_tail}}}\n',
        encoding="utf-8",
    )
    trials, skipped_non_completed, skipped_missing_objective = (
        module._read_trial_file_with_counts(path, "accuracy")
    )
    if row_tail.startswith('"status": "failed"'):
        assert (len(trials), skipped_non_completed, skipped_missing_objective) == (1, 1, 0)
    elif "metrics" in row_tail:
        assert (len(trials), skipped_non_completed, skipped_missing_objective) == (1, 0, 1)
    else:
        assert (len(trials), skipped_non_completed, skipped_missing_objective) == (2, 0, 0)
        value = trials[1].config["temperature"]
        if isinstance(value, dict):
            value = value["limits"][1]
        assert _is_literal(value, literal)


@pytest.mark.parametrize(
    "text",
    [
        '{"temperature": Infinity}',
        '{"temperature": [0.0, NaN]}',
        '{"temperature": [0.0, -Infinity]}',
        '{"model": ["a", "b"], "unobserved": [{"cap": 1e400}]}',
    ],
)
def test_nonfinite_config_space_values_are_accepted(tmp_path: Path, text) -> None:
    module = _load_module()
    space = tmp_path / "space.json"
    space.write_text(text, encoding="utf-8")
    knobs = list(json.loads(text))
    assert list(module.read_config_space(space)) == knobs
    trials_path = tmp_path / "trials.jsonl"
    write_jsonl(
        trials_path,
        [
            {"accuracy": 0.5 + 0.01 * i, "config": {"model": "ab"[i % 2], "temperature": 0.5 * (i % 3)}}
            for i in range(30)
        ],
    )
    output_dir = tmp_path / "out"
    run_cli(trials_path, output_dir, "--config-space", str(space), "--bootstrap-draws", "200")
    for name in ("importance.json", "video_card.json", "sdk_cross_check.json"):
        strict_json_loads((output_dir / name).read_text(encoding="utf-8"))


def _nonfinite_ranking_trials(module, nan_value, inf_value) -> list:
    """{0.0, NaN, inf} knob with distinct group means, plus an independent model knob."""
    base = {0: 0.5, 1: 0.7, 2: 0.6}
    values = {0: 0.0, 1: nan_value, 2: inf_value}
    return [
        _trial(
            module,
            base[i % 3] + 0.01 * (i % 7),
            {"x": values[i % 3], "model": "ab"[(i // 3) % 2]},
            cost=0.01 * (1 + i % 3),
        )
        for i in range(60)
    ]


def test_nonfinite_knob_values_rank_as_main_ranked_them() -> None:
    """Grouping keys keep NaN as one value, so the statistics match a finite stand-in."""
    module = _load_module()
    rows = module.analyze_importance(
        _nonfinite_ranking_trials(module, float("nan"), float("inf")), None, 0.9, 200, "randomized"
    )
    control = module.analyze_importance(
        _nonfinite_ranking_trials(module, -1e9, 1e9), None, 0.9, 200, "randomized"
    )
    fields = (
        "knob", "spread", "variance_share", "ci_low", "ci_high", "p_value", "p_adjusted",
        "label", "relevant_trials", "min_group_size", "cost_effect", "cost_effect_pct",
    )
    assert [[getattr(row, f) for f in fields] for row in rows] == [
        [getattr(row, f) for f in fields] for row in control
    ]
    by_knob = {row.knob: row for row in rows}
    assert math.isnan(by_knob["x"].best_value)
    assert by_knob["x"].worst_value == 0.0
    assert {row.knob: row for row in control}["x"].best_value == -1e9
    assert module.canonical_value(float("inf")) != module.canonical_value("Infinity")


NONFINITE_CLI_CASES = [
    # (knob, best value as written, other value as written, best_value in JSON, CSV cell)
    ("temperature", "NaN", "0.0", "NaN", "NaN"),
    ("temperature", "Infinity", "0.0", "Infinity", "Infinity"),
    ("temperature", "-Infinity", "0.0", "-Infinity", "-Infinity"),
    ("temperature", "1e400", "0.0", "Infinity", "Infinity"),
    ("stop", "[1, Infinity]", "[1, 2]", [1, "Infinity"], "[1, Infinity]"),
]


@pytest.mark.parametrize(
    ("knob", "best_text", "other_text", "best_json", "csv_cell"),
    NONFINITE_CLI_CASES,
    ids=["nan", "inf", "neg-inf", "overflow", "nested"],
)
def test_nonfinite_knob_values_reach_strict_json_as_strings(
    tmp_path: Path, knob, best_text, other_text, best_json, csv_cell
) -> None:
    """Issue #393 repro: a non-finite knob value reached the card as bare Infinity/NaN."""
    trials_path = tmp_path / "trials.jsonl"
    trials_path.write_text(
        "".join(
            f'{{"status": "completed", "accuracy": {(0.8 if index % 2 else 0.5) + 0.01 * (index % 5)}, '
            f'"cost": 0.01, "config": {{"{knob}": {best_text if index % 2 else other_text}, '
            f'"model": "{"ab"[(index // 2) % 2]}"}}}}\n'
            for index in range(60)
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"
    completed = run_cli(
        trials_path, output_dir, "--sampling-design", "randomized", "--bootstrap-draws", "200"
    )

    ranking = strict_json_loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    card = strict_json_loads((output_dir / "video_card.json").read_text(encoding="utf-8"))
    strict_json_loads((output_dir / "sdk_cross_check.json").read_text(encoding="utf-8"))
    assert stdout_card(completed.stdout) == card
    assert {row["knob"]: row["best_value"] for row in ranking}[knob] == best_json
    assert {row["knob"]: row["best_value"] for row in card["top_variables"]}[knob] == best_json
    with (output_dir / "importance.csv").open(encoding="utf-8", newline="") as handle:
        cells = {row["knob"]: row["best_value"] for row in csv.DictReader(handle)}
    assert cells[knob] == csv_cell
    assert (
        f"30 measured trial(s) carry a NaN or Infinity knob value ({knob}); wherever such a "
        'value appears in JSON outputs, it is written as the string "NaN", "Infinity" or '
        '"-Infinity"'
    ) in completed.stdout
    insights = (output_dir / "insights.md").read_text(encoding="utf-8")
    assert f"30 measured trial(s) carry a NaN or Infinity knob value (`{knob}`)" in insights
    assert "share one spelling" not in completed.stdout + insights
    # The "leave the key out" advice is about NaN only.
    assert ("Every NaN value is grouped as one value" in insights) == ("NaN" in best_text)


def test_unranked_nonfinite_knob_is_not_claimed_to_be_in_json_outputs(tmp_path: Path) -> None:
    """A single-value knob is never ranked, so no JSON artifact carries its Infinity."""
    trials_path = tmp_path / "trials.jsonl"
    write_jsonl(
        trials_path,
        [
            {
                "status": "completed",
                "accuracy": [0.2, 0.9][i % 2] + 0.001 * (i % 5),
                "config": {"max_tokens": float("inf"), "k": i % 2},
            }
            for i in range(40)
        ],
    )
    output_dir = tmp_path / "out"
    completed = run_cli(trials_path, output_dir, "--bootstrap-draws", "200")

    outputs = [
        (output_dir / name).read_text(encoding="utf-8")
        for name in ("importance.json", "video_card.json", "sdk_cross_check.json")
    ]
    assert not any("Infinity" in text for text in outputs)
    insights = (output_dir / "insights.md").read_text(encoding="utf-8")
    assert "wherever such a value appears in JSON outputs" in completed.stdout
    assert "wherever such a value appears in JSON outputs" in insights
    assert "JSON outputs write it" not in completed.stdout + insights
    assert "NaN value is grouped" not in insights


def test_number_and_string_infinity_stay_separate_values(tmp_path: Path) -> None:
    """A float infinity and the string "Infinity" are two arms; merging them hides the effect."""
    accuracy = {0: 0.5, 1: 0.9, 2: 0.2}
    trials_path = tmp_path / "trials.jsonl"
    write_jsonl(
        trials_path,
        [
            {
                "status": "completed",
                "accuracy": accuracy[i % 3] + 0.001 * (i % 5),
                "cost": 0.01,
                "config": {"max_tokens": [256, float("inf"), "Infinity"][i % 3]},
            }
            for i in range(60)
        ],
    )
    output_dir = tmp_path / "out"
    completed = run_cli(
        trials_path, output_dir, "--sampling-design", "randomized", "--bootstrap-draws", "200"
    )

    (row,) = strict_json_loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    assert row["spread"] == pytest.approx(0.70, abs=0.01)
    assert row["relevant_trials"] == 60
    assert row["min_group_size"] == 20
    assert row["p_value"] < 0.05
    card = strict_json_loads((output_dir / "video_card.json").read_text(encoding="utf-8"))
    strict_json_loads((output_dir / "sdk_cross_check.json").read_text(encoding="utf-8"))
    assert stdout_card(completed.stdout) == card
    assert (
        "knob 'max_tokens': a number and a string share one spelling in the outputs; "
        "they are ranked as separate values"
    ) in completed.stdout
    insights = (output_dir / "insights.md").read_text(encoding="utf-8")
    assert (
        "On `max_tokens`, a number and a string share one spelling in the outputs; "
        "they are ranked as separate values."
    ) in insights


def test_failed_rows_with_nonfinite_knob_values_do_not_stop_the_run(tmp_path: Path) -> None:
    """A provider rejecting max_tokens=inf fails those trials; the rest is still a run."""
    trials_path = tmp_path / "trials.jsonl"
    write_jsonl(
        trials_path,
        [
            {
                "status": "failed" if i % 3 == 2 else "completed",
                "config": {"max_tokens": [256, 512, float("inf")][i % 3]},
                "accuracy": 0.0 if i % 3 == 2 else 0.5 + 0.1 * (i % 3) + 0.01 * (i % 5),
                "cost": 0.01,
            }
            for i in range(48)
        ],
    )
    output_dir = tmp_path / "out"
    completed = run_cli(trials_path, output_dir, "--bootstrap-draws", "200")

    card = strict_json_loads((output_dir / "video_card.json").read_text(encoding="utf-8"))
    assert card["n_trials"] == 32
    assert card["skipped_non_completed"] == 16
    assert stdout_card(completed.stdout) == card
    strict_json_loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    strict_json_loads((output_dir / "sdk_cross_check.json").read_text(encoding="utf-8"))
    insights = (output_dir / "insights.md").read_text(encoding="utf-8")
    assert "NaN or Infinity knob value" not in completed.stdout + insights


@pytest.mark.parametrize(
    ("skipped_row", "counter"),
    [
        ({"status": "failed", "accuracy": 0.0}, "skipped_non_completed"),
        ({"status": "completed"}, "skipped_missing_objective"),
    ],
    ids=["failed", "no-objective"],
)
def test_a_skipped_row_with_text_that_is_not_unicode_does_not_stop_the_run(
    tmp_path: Path, skipped_row: dict, counter: str
) -> None:
    """A row the ranking skips never reaches a report, so its config is not checked."""
    trials_path = tmp_path / "trials.jsonl"
    rows = [
        {
            "status": "completed",
            "config": {"model": ["a", "b"][i % 2]},
            "accuracy": 0.5 + 0.1 * (i % 2) + 0.01 * (i % 5),
        }
        for i in range(40)
    ]
    skipped = json.dumps({**skipped_row, "config": {"model": "PLACEHOLDER"}})
    trials_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
        + skipped.replace("PLACEHOLDER", "\\ud800")
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"
    run_cli(trials_path, output_dir, "--bootstrap-draws", "200")

    card = strict_json_loads((output_dir / "video_card.json").read_text(encoding="utf-8"))
    assert card["n_trials"] == 40
    assert card[counter] == 1


@pytest.mark.parametrize(
    ("case", "json_path"),
    [
        ("cost", 'video_card.json["top_variables"][0]["cost_delta_pct"]'),
        ("heldout", 'video_card.json["heldout_accuracy_pp"]'),
    ],
)
def test_overflowing_derived_value_publishes_nothing_and_names_the_field(
    tmp_path: Path, case, json_path
) -> None:
    """Finite inputs can still overflow a derived number; the previous report stays whole."""
    trials_path = tmp_path / "trials.jsonl"
    extra: list[str] = []
    if case == "cost":
        rows = [
            {"status": "completed", "config": {"k": i % 2}, "accuracy": [0.2, 0.9][i % 2],
             "cost": [1e-300, 1e300][i % 2]}
            for i in range(40)
        ]
    else:
        rows = synthetic_trials(40)
        heldout = tmp_path / "heldout.json"
        heldout.write_text(
            json.dumps({"baseline": {"accuracy": -1.7e308}, "optimized": {"accuracy": 1.7e308}}),
            encoding="utf-8",
        )
        extra = ["--heldout", str(heldout)]
    write_jsonl(trials_path, rows)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    names = (
        "importance.json", "sdk_cross_check.json", "importance.csv",
        "significant_variables.svg", "insights.md", "video_card.json",
    )
    for name in names:
        (output_dir / name).write_text(f"previous run: {name}\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--trials", str(trials_path),
            "--output-dir", str(output_dir), "--bootstrap-draws", "200", *extra,
        ],
        text=True, capture_output=True,
    )

    assert completed.returncode != 0
    assert f"{json_path} is inf" in completed.stderr
    assert f"No report file in {output_dir} was written or replaced." in completed.stderr
    # No hidden entry is left behind either.
    assert sorted(path.name for path in output_dir.iterdir()) == sorted(names)
    for name in names:
        assert (output_dir / name).read_text(encoding="utf-8") == f"previous run: {name}\n"


REPORT_NAMES = (
    "importance.json", "sdk_cross_check.json", "importance.csv",
    "significant_variables.svg", "insights.md", "video_card.json",
)
WRITERS = (
    "write_importance_json", "write_sdk_cross_check_json", "write_importance_csv",
    "write_svg", "write_insights_md", "write_video_card_json",
)


def _spy_on_writers(module, monkeypatch, output_dir: Path) -> list[tuple[str, Path, list[str]]]:
    """Record each writer's target directory and what --output-dir held at that moment."""
    calls: list[tuple[str, Path, list[str]]] = []
    for name in WRITERS:
        original = getattr(module, name)

        def spy(path, *args, _name=name, _original=original, **kwargs):
            calls.append(
                (_name, Path(path).parent, sorted(p.name for p in output_dir.iterdir()))
            )
            return _original(path, *args, **kwargs)

        monkeypatch.setattr(module, name, spy)
    return calls


def test_reports_are_written_in_place_with_no_hidden_entry(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The six files are written straight into --output-dir; nothing else appears there."""
    module = _load_module()
    _install_sdk_stub(monkeypatch, {})
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    calls = _spy_on_writers(module, monkeypatch, output_dir)

    _run_main(module, monkeypatch, capsys, tmp_path)

    assert [name for name, _, _ in calls] == list(WRITERS)
    for name, target_dir, listing in calls:
        assert target_dir == output_dir, name
        assert not [entry for entry in listing if entry.startswith(".")], (name, listing)
    assert sorted(p.name for p in output_dir.iterdir()) == sorted(REPORT_NAMES)


def test_overflowing_derived_value_calls_no_writer(tmp_path: Path, monkeypatch) -> None:
    """The JSON outputs are checked before any writer runs, not after a scratch write."""
    module = _load_module()
    _install_sdk_stub(monkeypatch, {})
    trials_path = tmp_path / "trials.jsonl"
    write_jsonl(
        trials_path,
        [
            {"status": "completed", "config": {"k": i % 2}, "accuracy": [0.2, 0.9][i % 2],
             "cost": [1e-300, 1e300][i % 2]}
            for i in range(40)
        ],
    )
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    calls = _spy_on_writers(module, monkeypatch, output_dir)
    monkeypatch.setattr(
        sys, "argv",
        [str(SCRIPT), "--trials", str(trials_path), "--output-dir", str(output_dir),
         "--bootstrap-draws", "200"],
    )

    with pytest.raises(ValueError, match="No report file in .* was written or replaced"):
        module.main()

    assert calls == []
    assert list(output_dir.iterdir()) == []


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0,
    reason="POSIX permission bits; root ignores them",
)
def test_existing_report_permissions_are_kept(tmp_path: Path) -> None:
    """A report the user restricted to 0600 stays 0600 when a new run rewrites it."""
    trials_path = tmp_path / "trials.jsonl"
    write_jsonl(trials_path, synthetic_trials(40))
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    for name in REPORT_NAMES:
        (output_dir / name).write_text("previous\n", encoding="utf-8")
        (output_dir / name).chmod(0o600)

    previous_umask = os.umask(0o022)
    try:
        run_cli(trials_path, output_dir, "--bootstrap-draws", "200")
    finally:
        os.umask(previous_umask)

    for name in REPORT_NAMES:
        assert (output_dir / name).read_text(encoding="utf-8") != "previous\n", name
        assert (output_dir / name).stat().st_mode & 0o777 == 0o600, name


@pytest.mark.skipif(os.name != "posix", reason="symlinks need privileges on Windows")
def test_symlinked_report_files_are_written_through(tmp_path: Path) -> None:
    """A report file that is a symlink keeps the link; its target gets the new content."""
    trials_path = tmp_path / "trials.jsonl"
    write_jsonl(trials_path, synthetic_trials(40))
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    targets = tmp_path / "published"
    targets.mkdir()
    for name in REPORT_NAMES:
        (targets / name).write_text("previous\n", encoding="utf-8")
        (output_dir / name).symlink_to(targets / name)

    run_cli(trials_path, output_dir, "--bootstrap-draws", "200")

    for name in REPORT_NAMES:
        assert (output_dir / name).is_symlink(), name
        assert os.readlink(output_dir / name) == str(targets / name), name
        assert (targets / name).read_text(encoding="utf-8") != "previous\n", name
    assert sorted(p.name for p in targets.iterdir()) == sorted(REPORT_NAMES)


def test_string_sentinels_and_finite_nested_values_are_still_accepted(tmp_path: Path) -> None:
    """Compatibility: a sentinel written as a JSON string stays its own category."""
    module = _load_module()
    path = tmp_path / "trials.jsonl"
    write_jsonl(
        path,
        [
            {
                "accuracy": 0.9 if i % 2 else 0.2,
                "config": {"max_tokens": ["Infinity", 256][i % 2], "stop": {"after": [1.5, None, "NaN"]}},
            }
            for i in range(40)
        ],
    )
    trials = module.read_trials(path, "accuracy")
    rows = module.analyze_importance(trials, {"max_tokens": ["Infinity", 256]}, 0.9, 200)
    by_knob = {row.knob: row for row in rows}
    assert set(by_knob) == {"max_tokens"}
    assert by_knob["max_tokens"].best_value == 256
    assert by_knob["max_tokens"].worst_value == "Infinity"
    assert set(by_knob["max_tokens"].group_sizes) == {"256", "Infinity"}


def _run_into_previous_reports(
    tmp_path: Path, trials_text: str, *extra: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    trials_path = tmp_path / "trials.jsonl"
    trials_path.write_text(trials_text, encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    for name in REPORT_NAMES:
        (output_dir / name).write_bytes(f"previous run: {name}\n".encode())
    completed = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--trials", str(trials_path),
            "--output-dir", str(output_dir), "--bootstrap-draws", "200", *extra,
        ],
        text=True, capture_output=True,
    )
    return completed, output_dir


@pytest.mark.parametrize(
    ("config_text", "message"),
    [
        # A lone-surrogate knob name with an infinite value: the non-finite notice
        # used to carry the name into insights.md, which then failed to encode.
        ('{{"k": {k}, "\\ud800": 1e400}}', 'config["\\ud800"] names a key that is not valid Unicode text'),
        # A lone-surrogate knob value that is the best value: importance.json failed to encode.
        ('{{"k": {value}}}', 'config["k"] must be valid Unicode text, got "\\ud800x"'),
    ],
    ids=["knob-name", "knob-value"],
)
def test_knob_text_that_is_not_unicode_is_rejected_before_any_report_is_written(
    tmp_path: Path, config_text, message
) -> None:
    """json.loads accepts a lone surrogate escape; no report file can encode one as UTF-8."""
    values = ['"\\ud800x"', '"plain"']
    trials_text = "".join(
        f'{{"status": "completed", "metrics": {{"accuracy": {[0.8, 0.4][i % 2]}}}, '
        f'"config": {config_text.format(k=i % 2, value=values[i % 2])}}}\n'
        for i in range(40)
    )
    completed, output_dir = _run_into_previous_reports(tmp_path, trials_text)

    assert sorted(path.name for path in output_dir.iterdir()) == sorted(REPORT_NAMES)
    # Name each changed file with its new size, so a truncated (0-byte) report shows.
    changed = {
        name: len((output_dir / name).read_bytes())
        for name in REPORT_NAMES
        if (output_dir / name).read_bytes() != f"previous run: {name}\n".encode()
    }
    assert changed == {}
    assert completed.returncode != 0
    assert f"{tmp_path / 'trials.jsonl'}:1: {message}" in completed.stderr


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"model": ["a", "\\ud800"]}', 'config_space["model"][1] must be valid Unicode text, got "\\ud800"'),
        ('{"\\udfff": ["a", "b"]}', 'config_space["\\udfff"] names a key that is not valid Unicode text'),
        ('{"stop": {"\\ud800": 1}}', 'config_space["stop"]["\\ud800"] names a key that is not valid Unicode text'),
    ],
    ids=["value", "knob-name", "nested-key"],
)
def test_config_space_text_that_is_not_unicode_is_rejected(tmp_path: Path, text, message) -> None:
    module = _load_module()
    space = tmp_path / "space.json"
    space.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError) as raised:
        module.read_config_space(space)
    assert str(raised.value) == f"{space}: {message}"
    str(raised.value).encode("utf-8")  # the message itself can be printed


def test_non_ascii_knob_names_and_values_are_still_accepted(tmp_path: Path) -> None:
    """Compatibility: valid non-ASCII text (accents, emoji) reaches every report as written."""
    trials_path = tmp_path / "trials.jsonl"
    trials_path.write_text(
        "".join(
            json.dumps(
                {
                    "status": "completed",
                    "accuracy": [0.2, 0.9][i % 2] + 0.001 * (i % 5),
                    "config": {"température": ["bas", "élevé"][i % 2], "🎛️ mode": ["🔥", "❄️"][(i // 2) % 2]},
                },
                ensure_ascii=bool(i % 3),
            )
            + "\n"
            for i in range(40)
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"
    completed = run_cli(trials_path, output_dir, "--bootstrap-draws", "200")

    ranking = strict_json_loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    best = {row["knob"]: row["best_value"] for row in ranking}
    assert best["température"] == "élevé"
    assert best["🎛️ mode"] in {"🔥", "❄️"}
    card = strict_json_loads((output_dir / "video_card.json").read_text(encoding="utf-8"))
    assert stdout_card(completed.stdout) == card
    assert card["top_variables"][0]["knob"] == "température"
    with (output_dir / "importance.csv").open(encoding="utf-8", newline="") as handle:
        cells = {row["knob"]: row["best_value"] for row in csv.DictReader(handle)}
    assert cells["température"] == "élevé"
    for name in ("insights.md", "significant_variables.svg"):
        assert "température" in (output_dir / name).read_text(encoding="utf-8"), name
    assert "best=élevé" in completed.stdout


@pytest.mark.parametrize("writer", ["importance", "video_card", "sdk_cross_check"])
@pytest.mark.parametrize(
    ("bad", "suffix"),
    [(float("nan"), ""), ({"cap": [0.1, float("inf")]}, '["cap"][1]')],
    ids=["scalar", "nested"],
)
def test_json_writers_refuse_nonfinite_payloads_and_leave_the_file_untouched(
    tmp_path: Path, writer, bad, suffix
) -> None:
    module = _load_module()
    trials = [_trial(module, 0.9 if i % 2 else 0.2, {"knob": i % 2}) for i in range(40)]
    row = module.analyze_importance(trials, None, 0.9, 200)[0]
    row.p_value = bad
    path = tmp_path / f"{writer}.json"
    path.write_text("previous\n", encoding="utf-8")
    json_path = {
        "importance": 'importance.json[0]["p_value"]',
        "video_card": 'video_card.json["top_variables"][0]["p_value"]',
        "sdk_cross_check": 'sdk_cross_check.json["results"]["knob"]["importance_score"]',
    }[writer] + suffix
    with pytest.raises(ValueError, match=re.escape(f"{json_path} is ")):
        if writer == "importance":
            module.write_importance_json(path, [row])
        elif writer == "video_card":
            module.write_video_card_json(
                path, [row], top_k=1, n_trials=40, objective="accuracy", heldout=None
            )
        else:
            module.write_sdk_cross_check_json(
                path,
                "note",
                {"knob": {"importance_score": bad, "confidence_interval": [0.1, 0.2]}},
            )
    assert path.read_text(encoding="utf-8") == "previous\n"


def _sdk_result(score=0.5, interval=(0.4, 0.6), method="variance_based", sample_size=80):
    return types.SimpleNamespace(
        importance_score=score,
        confidence_interval=interval,
        method=method,
        sample_size=sample_size,
    )


def _install_sdk_stub(monkeypatch, results: dict) -> None:
    """Stand in for the optional SDK analyzer, so no SDK install is needed."""

    class StubAnalyzer:
        def __init__(self, objective: str) -> None:
            self.objective = objective

        def analyze_variance_based(self, trials):
            return results

    importance = types.ModuleType("traigent.utils.importance")
    importance.ParameterImportanceAnalyzer = StubAnalyzer
    utils = types.ModuleType("traigent.utils")
    utils.importance = importance
    package = types.ModuleType("traigent")
    package.utils = utils
    monkeypatch.setitem(sys.modules, "traigent", package)
    monkeypatch.setitem(sys.modules, "traigent.utils", utils)
    monkeypatch.setitem(sys.modules, "traigent.utils.importance", importance)


def _run_main(module, monkeypatch, capsys, tmp_path: Path) -> tuple[Path, str]:
    trials_path = tmp_path / "trials.jsonl"
    output_dir = tmp_path / "out"
    write_jsonl(trials_path, synthetic_trials(80))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT), "--trials", str(trials_path), "--output-dir", str(output_dir),
            "--bootstrap-draws", "200",
        ],
    )
    assert module.main() == 0
    return output_dir, capsys.readouterr().out


INVALID_SDK_RESULTS = {
    # case: (the second knob's name and result, what the fallback note must name)
    "nan-score": ("secondary_knob", _sdk_result(score=float("nan")), "secondary_knob: importance_score"),
    "infinite-endpoint": (
        "secondary_knob", _sdk_result(interval=(0.4, float("inf"))), "secondary_knob: confidence_interval[1]"
    ),
    "boolean-score": ("secondary_knob", _sdk_result(score=True), "secondary_knob: importance_score"),
    "missing-score": ("secondary_knob", _sdk_result(score=None), "secondary_knob: importance_score"),
    "missing-interval": ("secondary_knob", _sdk_result(interval=None), "secondary_knob: confidence_interval"),
    "one-endpoint": ("secondary_knob", _sdk_result(interval=(0.4,)), "secondary_knob: confidence_interval"),
    "unserializable-method": ("secondary_knob", _sdk_result(method=object()), "secondary_knob: method"),
    "nonfinite-sample-size": (
        "secondary_knob", _sdk_result(sample_size=float("nan")), "secondary_knob: sample_size"
    ),
    "non-string-knob-name": (7, _sdk_result(), "knob name 7 is not a string"),
}


@pytest.mark.parametrize("case", sorted(INVALID_SDK_RESULTS))
def test_invalid_sdk_output_falls_back_explicitly_and_keeps_the_report(
    tmp_path: Path, monkeypatch, capsys, case
) -> None:
    module = _load_module()
    name, result, named = INVALID_SDK_RESULTS[case]
    _install_sdk_stub(monkeypatch, {"dominant_knob": _sdk_result(), name: result})

    output_dir, stdout = _run_main(module, monkeypatch, capsys, tmp_path)

    cross_check = strict_json_loads(
        (output_dir / "sdk_cross_check.json").read_text(encoding="utf-8")
    )
    assert cross_check["computed"] is False
    assert cross_check["results"] == {}
    assert "returned output this report cannot use" in cross_check["note"]
    assert f"SDK output error: ValueError: {named}" in cross_check["note"]
    insights = (output_dir / "insights.md").read_text(encoding="utf-8")
    assert cross_check["note"] in insights
    assert "## SDK cross-check" not in insights
    ranking = strict_json_loads((output_dir / "importance.json").read_text(encoding="utf-8"))
    assert ranking[0]["knob"] == "dominant_knob"
    assert stdout_card(stdout) == strict_json_loads(
        (output_dir / "video_card.json").read_text(encoding="utf-8")
    )


def test_valid_sdk_output_is_still_reported_as_a_cross_check(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Compatibility: the validation must not drop a well-formed SDK result."""
    module = _load_module()
    _install_sdk_stub(monkeypatch, {"dominant_knob": _sdk_result(0.75, (0.5, 0.9))})

    output_dir, _ = _run_main(module, monkeypatch, capsys, tmp_path)

    cross_check = strict_json_loads(
        (output_dir / "sdk_cross_check.json").read_text(encoding="utf-8")
    )
    assert cross_check["computed"] is True
    assert cross_check["results"] == {
        "dominant_knob": {
            "importance_score": 0.75,
            "confidence_interval": [0.5, 0.9],
            "method": "variance_based",
            "sample_size": 80,
        }
    }
    insights = (output_dir / "insights.md").read_text(encoding="utf-8")
    assert "| `dominant_knob` | 0.75 | [0.5, 0.9] | 80 |" in insights


@pytest.mark.parametrize("flag", ["--slice-label", "--objective"])
def test_invalid_cli_text_preserves_all_existing_reports(tmp_path: Path, flag: str) -> None:
    # POSIX argv decodes an invalid UTF-8 byte through surrogateescape.
    trials = '{"config":{"k":0},"metrics":{"accuracy":0.8,"\\udc80":0.8}}\n'
    completed, output = _run_into_previous_reports(tmp_path, trials, flag, "\udc80")
    assert completed.returncode != 0
    assert "valid Unicode text" in completed.stderr
    assert "Traceback" not in completed.stderr
    for name in REPORT_NAMES:
        assert (output / name).read_bytes() == f"previous run: {name}\n".encode()


@pytest.mark.parametrize("depth", [150, 1500])
def test_deep_knob_input_has_readable_refusal_and_preserves_reports(
    tmp_path: Path, depth: int
) -> None:
    nested = "[" * depth + "0" + "]" * depth
    trials = '{"config":{"k":' + nested + '},"metrics":{"accuracy":0.8}}\n'
    completed, output = _run_into_previous_reports(tmp_path, trials)
    assert completed.returncode != 0
    assert "nesting" in completed.stderr
    assert "Traceback" not in completed.stderr
    for name in REPORT_NAMES:
        assert (output / name).read_bytes() == f"previous run: {name}\n".encode()


def test_json_output_refuses_invalid_text_before_opening_file(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "sdk_cross_check.json"
    output.write_text("previous report\n")
    output.chmod(0o600)
    with pytest.raises(ValueError, match="valid Unicode text"):
        module.write_sdk_cross_check_json(output, "\ud800", {})
    assert output.read_text() == "previous report\n"
    assert output.stat().st_mode & 0o777 == 0o600

