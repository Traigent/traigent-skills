"""Pin what the trial reader, the permutation test, the per-knob and run-level
analysis, the SDK cross-check validator, the heldout card metrics and the
insights writer return, raise and write.

Each case below is run and its observation compared, ordering included, with
the recorded observation in ``pins/importance_pins.json``. The record was
written from the code before these functions were restructured, so any
difference is a behaviour change rather than a style change. Regenerate it
only for an intended change, and review the diff of the JSON file:

    python tests/test_importance_pins.py --write

``--dump PATH`` writes the observations without comparing, so two copies of
the script can be run over the same cases and their outputs diffed.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
PINS = TESTS_DIR / "pins" / "importance_pins.json"

# A plain import off sys.path, as the analyzer's own tests do (see their
# `_load_module`): it registers the module for dataclass annotation lookup.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import significant_tuned_variables as stv  # noqa: E402


# --------------------------------------------------------------------------
# serialising observations
# --------------------------------------------------------------------------


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(item) for item in value), key=repr)
    if isinstance(value, float) and not math.isfinite(value):
        return f"<float {value!r}>"
    if isinstance(value, float):
        return float.hex(value)
    if isinstance(value, Path):
        return f"<path {value.as_posix()}>"
    return value


def _text(value: object) -> str:
    """Canonical, order-preserving text of one observation. Floats are kept as
    their exact hex spelling, so a last-bit difference is a difference."""
    return json.dumps(_jsonable(value), ensure_ascii=True, allow_nan=False)


def _call(function: Callable[..., object], *args: object, **kwargs: object) -> dict:
    """The return value, or the raised type and message."""
    try:
        return {"returned": _jsonable(function(*args, **kwargs))}
    except Exception as exc:  # noqa: BLE001 - the raised type is pinned
        return {"raised": type(exc).__name__, "message": str(exc)}


# --------------------------------------------------------------------------
# trial files
# --------------------------------------------------------------------------


def _line(record: object) -> str:
    return json.dumps(record) + "\n"


def _trial_files() -> dict[str, str]:
    good = _line({"config": {"k": "a"}, "accuracy": 0.5})
    return {
        "measured_mix": "\n"
        + good
        + "   \n"
        + _line({"config": {"k": "b"}, "metrics": {"accuracy": 0.25, "cost": 0.5}})
        + _line({"config": {"k": "c"}, "accuracy": 1, "mock_cost": 2})
        + _line({"config": {"k": "d"}, "status": "Completed", "accuracy": 0.75,
                 "metrics": {"mock_cost": 0.1}})
        + _line({"config": {"k": "e"}, "status": "failed", "accuracy": 0.0})
        + _line({"config": {"k": "f"}, "status": "PRUNED"})
        + _line({"config": {"k": "g"}, "status": 3, "accuracy": 0.1})
        + _line({"config": {"k": "h"}, "accuracy": None, "metrics": {"other": 1}})
        + _line({"config": {"k": "i"}})
        + _line({"config": {"k": "j"}, "metrics": "not a dict"})
        + _line({"config": {"k": {"nested": [1, 2]}}, "accuracy": 0.3, "cost": 0}),
        "invalid_json": good + "{broken\n",
        "not_an_object": good + "[1, 2]\n",
        "config_missing": good + _line({"accuracy": 0.2}),
        "config_not_object": good + _line({"config": [1], "accuracy": 0.2}),
        "metric_boolean": _line({"config": {"k": "a"}, "accuracy": True}),
        "metric_nan": '{"config": {"k": "a"}, "metrics": {"accuracy": NaN}}\n',
        "cost_negative": _line({"config": {"k": "a"}, "accuracy": 0.5, "cost": -1}),
        "cost_invalid_on_unmeasured_row": _line({"config": {"k": "a"}, "cost": "x"}) + good,
        "deep_config": _line({"config": {"k": json.loads("[" * 102 + "]" * 102)},
                              "accuracy": 0.5}),
        "deep_config_unmeasured": _line({"config": {"k": json.loads("[" * 102 + "]" * 102)}})
        + good,
        "lone_surrogate_value": '{"config": {"k": "\\ud800"}, "accuracy": 0.5}\n',
        "lone_surrogate_key": '{"config": {"\\udc00": 1}, "accuracy": 0.5}\n',
        "nothing_measured": _line({"config": {"k": "a"}, "status": "failed"})
        + _line({"config": {"k": "b"}}),
        "empty": "",
        "json_too_deep": "[" * 100000 + "]" * 100000 + "\n",
    }


def _observe_trial_file(name: str, text: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{name}.jsonl"
        path.write_text(text, encoding="utf-8")
        result = _call(stv._read_trial_file_with_counts, path, "accuracy")
    return json.loads(_text(result).replace(tmp, "<tmp>"))


# --------------------------------------------------------------------------
# trials for the statistics
# --------------------------------------------------------------------------


def _trial(objective: float, config: dict, cost: float | None = None) -> object:
    return stv.Trial(objective=objective, config=config, cost=cost, raw={})


def _effect_trials(n: int, effect: float, *, seed: int = 7, offset: float = 0.0,
                   values: tuple = ("a", "b"), knob: str = "k",
                   cost: Callable[[int], float | None] | None = None) -> list:
    rng = random.Random(seed)
    trials = []
    for i in range(n):
        value = values[i % len(values)]
        objective = offset + rng.random() * 0.1 + (effect if value == values[0] else 0.0)
        trials.append(_trial(objective, {knob: value}, None if cost is None else cost(i)))
    return trials


def _permutation_cases() -> dict[str, tuple[list, str, int]]:
    shared = _effect_trials(20, 0.5)
    return {
        "one_trial": ([_trial(1.0, {"k": "a"})], "k", 99),
        "zero_draws": (shared, "k", 0),
        "single_value": ([_trial(i / 10, {"k": "a"}) for i in range(6)], "k", 99),
        "no_spread": ([_trial(0.5, {"k": v}) for v in "abab"], "k", 99),
        "strong_effect": (shared, "k", 199),
        "noise": (_effect_trials(30, 0.0, seed=3), "k", 199),
        "large_offset": (_effect_trials(24, 0.01, offset=1e6), "k", 199),
        "tiny_scale": ([_trial(v * 1e-15, {"k": "ab"[i % 2]})
                        for i, v in enumerate([1, 0, 1, 0, 1, 1, 0, 0, 1, 0])], "k", 199),
        "knob_missing_in_some": (shared + [_trial(0.9, {"other": 1})] * 5, "k", 199),
        "three_values": (_effect_trials(30, 0.2, values=("x", "y", "z")), "k", 199),
        "binary_ties": ([_trial(float(i % 3 == 0), {"k": "ab"[i % 2]}) for i in range(12)],
                        "k", 199),
        "other_seed": (shared, "k", 50),
    }


def _knob_cases() -> dict[str, tuple[list, str]]:
    return {
        "one_group": ([_trial(0.1 * i, {"k": "a"}) for i in range(5)], "k"),
        "absent_knob": ([_trial(0.1, {"j": "a"}), _trial(0.2, {"j": "b"})], "k"),
        "costs_both": (_effect_trials(12, 0.3, cost=lambda i: 0.01 * (i + 1)), "k"),
        "worst_cost_zero": (_effect_trials(12, 0.3, cost=lambda i: 0.0 if i % 2 else 0.5),
                            "k"),
        "costs_one_side": (_effect_trials(12, 0.3, cost=lambda i: None if i % 2 else 0.2),
                           "k"),
        "no_costs": (_effect_trials(12, 0.3), "k"),
        "tied_means": ([_trial(0.5, {"k": v}) for v in "abcabc"], "k"),
        "structured_values": ([_trial(0.1 * i, {"k": [{"a": i % 3}, float("inf")][i % 2]})
                               for i in range(9)], "k"),
    }


def _importance_cases() -> dict[str, dict]:
    strong = _effect_trials(40, 0.5)
    coupled = [_trial(t.objective, {"x": t.config["k"], "y": t.config["k"] + "!"})
               for t in strong]
    two = [_trial(t.objective, {"k": t.config["k"], "z": ["p", "q"][(i // 2) % 2]})
           for i, t in enumerate(strong)]
    return {
        "alpha_zero": {"trials": strong, "alpha": 0.0},
        "alpha_too_high": {"trials": strong, "alpha": 0.2},
        "design_unknown_value": {"trials": strong, "design": "bogus"},
        "objective_infinite": {"trials": [_trial(float("inf"), {"k": "a"})]},
        "objective_none": {"trials": [_trial(0.5, {"k": "a"}), _trial(None, {"k": "b"})]},
        "cost_negative": {"trials": [_trial(0.5, {"k": "a"}, -1.0)]},
        "cost_boolean": {"trials": [_trial(0.5, {"k": "a"}, True)]},
        "no_trials": {"trials": []},
        "single_value_knob": {"trials": [_trial(0.1 * i, {"k": "a"}) for i in range(5)]},
        "too_few_samples": {"trials": _effect_trials(10, 0.5), "design": "randomized"},
        "small_group": {"trials": strong + [_trial(0.2, {"k": "rare"})] * 3,
                        "design": "randomized"},
        "low_resolution": {"trials": strong, "design": "randomized", "draws": 99},
        # One knob at alpha 0.05 needs draws + 1 >= 200: 199 draws is exactly
        # enough and 198 is one short.
        "resolution_exactly_enough": {"trials": strong, "design": "randomized",
                                      "draws": 199},
        "resolution_one_short": {"trials": strong, "design": "randomized", "draws": 198},
        "adaptive": {"trials": strong, "design": "adaptive"},
        "unknown": {"trials": strong, "design": "unknown"},
        "coupled_knobs": {"trials": coupled, "design": "randomized", "draws": 499},
        "tested_significant": {"trials": strong, "design": "randomized"},
        "tested_directional": {"trials": _effect_trials(40, 0.0, seed=11),
                               "design": "randomized"},
        "two_knobs_randomized": {"trials": two, "design": "randomized", "draws": 499},
        "config_space_extra_knob": {"trials": strong, "space": {"k": ["a", "b"],
                                                                 "unused": [1, 2]},
                                    "design": "randomized"},
        "zero_spread_tested": {"trials": [_trial(0.5, {"k": "ab"[i % 2]}) for i in range(40)],
                               "design": "randomized"},
        "alpha_tenth": {"trials": strong, "design": "randomized", "alpha": 0.1},
    }


def _observe_importance(spec: dict) -> dict:
    return _call(
        stv.analyze_importance,
        spec["trials"],
        spec.get("space"),
        0.9,
        spec.get("draws", 299),
        spec.get("design", "unknown"),
        spec.get("alpha", 0.05),
    )


# --------------------------------------------------------------------------
# SDK cross-check, heldout card metrics
# --------------------------------------------------------------------------


def _sdk(score: object = 0.4, interval: object = (0.1, 0.7), method: object = "variance",
         size: object = 30, drop: str | None = None) -> SimpleNamespace:
    fields = {"importance_score": score, "confidence_interval": interval,
              "method": method, "sample_size": size}
    if drop is not None:
        del fields[drop]
    return SimpleNamespace(**fields)


def _sdk_cases() -> dict[str, dict]:
    return {
        "valid_sorted": {"zeta": _sdk(), "alpha": _sdk(score=1, interval=[0, 2], size=0)},
        "empty": {},
        "name_not_string": {1: _sdk()},
        "name_not_string_later": {"a": _sdk(), ("t",): _sdk()},
        "score_missing": {"a": _sdk(drop="importance_score")},
        "interval_missing": {"a": _sdk(drop="confidence_interval")},
        "interval_not_pair": {"a": _sdk(interval=(0.1, 0.2, 0.3))},
        "interval_not_sequence": {"a": _sdk(interval="0.1,0.2")},
        "score_nan": {"a": _sdk(score=float("nan"))},
        "score_boolean": {"a": _sdk(score=True)},
        "score_none": {"a": _sdk(score=None)},
        "low_infinite": {"a": _sdk(interval=(float("-inf"), 1.0))},
        "high_none": {"a": _sdk(interval=[0.0, None])},
        "method_missing": {"a": _sdk(drop="method")},
        "method_not_string": {"a": _sdk(method=3)},
        "size_missing": {"a": _sdk(drop="sample_size")},
        "size_boolean": {"a": _sdk(size=True)},
        "size_negative": {"a": _sdk(size=-1)},
        "size_float": {"a": _sdk(size=2.0)},
        "second_invalid": {"a": _sdk(), "b": _sdk(method=None)},
    }


def _heldout_cases() -> dict[str, object]:
    return {
        "none": None,
        "empty": {},
        "delta_reported": {"delta": {"accuracy": 0.05}, "baseline": {"accuracy": 0.5},
                           "optimized": {"accuracy": 0.7}},
        "delta_computed": {"baseline": {"accuracy": 0.5}, "optimized": {"accuracy": 0.625}},
        "baseline_only": {"baseline": {"accuracy": 0.5}},
        "sections_not_objects": {"baseline": 3, "optimized": [1], "delta": "x"},
        "cost_pair": {"baseline": {"cost": 2.0}, "optimized": {"cost": 1.5}},
        "cost_base_zero": {"baseline": {"cost": 0.0}, "optimized": {"cost": 1.0},
                           "delta": {"cost": 1.0}},
        "cost_delta_only": {"baseline": {"cost": 4.0}, "delta": {"cost": -1.0}},
        "cost_base_only": {"baseline": {"cost": 4.0}},
        "cost_optimized_only": {"optimized": {"cost": 4.0},
                                "baseline": {"mock_cost": 2.0}, "delta": {"mock_cost": 1}},
        "mock_cost_only": {"baseline": {"mock_cost": 2.0}, "optimized": {"mock_cost": 3.0}},
        "mock_cost_delta": {"baseline": {"mock_cost": 2.0}, "delta": {"mock_cost": 0.5}},
        "both_costs": {"baseline": {"cost": 1.0, "mock_cost": 9.0},
                       "optimized": {"cost": 2.0, "mock_cost": 1.0}},
        "accuracy_boolean": {"baseline": {"accuracy": True}},
        "unused_delta_invalid": {"delta": {"accuracy": 0.1}, "optimized": {"accuracy": "x"}},
        "cost_negative": {"baseline": {"cost": -1.0}},
        "cost_delta_negative_ok": {"baseline": {"cost": 1.0}, "delta": {"cost": -0.5}},
        "mock_cost_nan": {"optimized": {"mock_cost": float("nan")}},
        "other_objective": {"delta": {"accuracy": 0.1, "f1": 0.2}},
    }


# --------------------------------------------------------------------------
# insights.md
# --------------------------------------------------------------------------


def _row(knob: str, **overrides: object) -> object:
    fields = dict(
        knob=knob, spread=0.125, variance_share=0.25, ci_low=0.0625, ci_high=0.1875,
        label="directional", best_value="a", best_value_mean_acc=0.75,
        cost_effect=None, cost_effect_pct=None, worst_value="b",
        worst_value_mean_acc=0.625, value_means={"a": 0.75, "b": 0.625},
        group_sizes={"a": 10, "b": 10}, p_value=0.01, p_adjusted=0.02,
        correction="holm", family_size=2, inference_status="tested",
        sampling_design="randomized", relevant_trials=20, min_group_size=10,
        permutation_draws=999, permutation_p_floor=0.001,
    )
    fields.update(overrides)
    return stv.KnobImportance(**fields)


def _insights_cases() -> dict[str, tuple[list, dict]]:
    rows = [
        _row("model", label="significant", cost_effect=-0.0123, best_value={"m": [1]}),
        _row("temperature", spread=0.0, inference_status="adaptive_sampling",
             best_value=0.7),
    ]
    short = [_row("a", inference_status="insufficient_permutation_resolution",
                  family_size=3),
             _row("b", inference_status="insufficient_permutation_resolution",
                  family_size=3)]
    sdk_payload = {"model": {"importance_score": 0.5, "confidence_interval": [0.1, 0.9],
                             "method": "variance", "sample_size": 20},
                   "temperature": {"importance_score": 1e-07,
                                   "confidence_interval": [0.0, 1234567.0],
                                   "method": "variance", "sample_size": 0}}
    return {
        "empty": ([], {}),
        "ranked_plain": (rows, {}),
        "everything": (rows, {
            "heldout": {"baseline": {"accuracy": 0.5, "cost": 2.0},
                        "optimized": {"accuracy": 0.6, "cost": 1.0}},
            "slice_label": "this HotpotQA slice", "skipped_non_completed": 3,
            "alpha": 0.1, "sdk_payload": sdk_payload, "skipped_missing_objective": 2,
            "nonfinite_trials": 4, "nonfinite_knobs": ["model", "t"],
            "nonfinite_collisions": ["model", "t"], "nonfinite_has_nan": True,
        }),
        "nonfinite_without_nan": (rows, {"nonfinite_trials": 1, "nonfinite_knobs": ["t"]}),
        "heldout_accuracy_only": (rows, {"heldout": {"delta": {"accuracy": -0.02}}}),
        "heldout_cost_only": (rows, {"heldout": {"baseline": {"mock_cost": 1.0},
                                                 "delta": {"mock_cost": 0.5}}}),
        "heldout_without_numbers": (rows, {"heldout": {"baseline": {"other": 1}}}),
        "short_resolution": (short, {"alpha": 0.05}),
        "empty_sdk_payload": (rows, {"sdk_payload": {}}),
        "confidence_display": (rows, {"confidence": 0.951}),
    }


def _observe_insights(rows: list, options: dict) -> dict:
    options = dict(options)
    confidence = options.pop("confidence", 0.9)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "insights.md"
        result = _call(stv.write_insights_md, path, rows, 40, "accuracy", confidence,
                       options.pop("heldout", None), "SDK note line.", **options)
        result["written"] = path.read_text(encoding="utf-8") if path.exists() else None
    return result


# --------------------------------------------------------------------------
# collection, the record, and the tests
# --------------------------------------------------------------------------


def collect() -> dict[str, object]:
    observed: dict[str, object] = {}
    for name, text in _trial_files().items():
        observed[f"_read_trial_file_with_counts/{name}"] = _observe_trial_file(name, text)
    for name, (trials, knob, draws) in _permutation_cases().items():
        observed[f"permutation_spread_pvalue/{name}"] = _call(
            stv.permutation_spread_pvalue, trials, knob, draws)
    for name, (trials, knob) in _knob_cases().items():
        observed[f"analyze_knob/{name}"] = _call(
            stv.analyze_knob, trials, knob, 0.9, 199, len(trials), "randomized")
    for name, spec in _importance_cases().items():
        observed[f"analyze_importance/{name}"] = _observe_importance(spec)
    for name, results in _sdk_cases().items():
        observed[f"sdk_cross_check_payload/{name}"] = _call(stv.sdk_cross_check_payload,
                                                            results)
    for name, heldout in _heldout_cases().items():
        for objective in ("accuracy", "f1"):
            observed[f"heldout_card_metrics/{name}/{objective}"] = _call(
                stv.heldout_card_metrics, heldout, objective)
    for name, (rows, options) in _insights_cases().items():
        observed[f"write_insights_md/{name}"] = _observe_insights(rows, options)
    return {key: json.loads(_text(value)) for key, value in observed.items()}


def _recorded() -> dict:
    return json.loads(PINS.read_text(encoding="utf-8"))


_OBSERVED: dict | None = None


def _observed() -> dict:
    global _OBSERVED
    if _OBSERVED is None:
        _OBSERVED = collect()
    return _OBSERVED


def _case_ids() -> list[str]:
    # A missing record is a failure of the completeness test below, not an
    # import error that would also stop `--write` from creating it.
    return sorted(_recorded()) if PINS.exists() else []


def test_every_case_has_a_record_and_every_record_a_case() -> None:
    assert sorted(_observed()) == _case_ids()


@pytest.mark.parametrize("case_id", _case_ids())
def test_behaviour_matches_the_record(case_id: str) -> None:
    observed = _observed()
    assert case_id in observed, f"{case_id} is recorded but no longer produced"
    assert _text(observed[case_id]) == _text(_recorded()[case_id])


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true",
                       help="rewrite the record from the code as it stands")
    group.add_argument("--dump", metavar="PATH", help="write observations to PATH")
    options = parser.parse_args(argv)
    observed = collect()
    # One case per line, so a behaviour change shows as a one-line diff.
    text = (
        "{\n"
        + ",\n".join(
            f"{json.dumps(key)}: {_text(value)}" for key, value in observed.items()
        )
        + "\n}\n"
    )
    target = PINS if options.write else Path(options.dump)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"{len(observed)} case(s) written to {target}")
    print(f"significant_tuned_variables: {stv.__file__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
