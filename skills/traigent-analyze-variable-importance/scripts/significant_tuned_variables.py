#!/usr/bin/env python3
"""Rank tuned variables by observed optimization impact.

This script is intentionally dependency-light: stdlib only for the core method,
with an optional Traigent SDK variance-importance cross-check when available.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import math
import random
from collections import defaultdict
from contextlib import redirect_stderr
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BOOTSTRAP_SEED = 55
DEFAULT_BOOTSTRAP_DRAWS = 1000


@dataclass(frozen=True)
class Trial:
    objective: float
    config: dict[str, Any]
    cost: float | None
    raw: dict[str, Any]


@dataclass
class KnobImportance:
    knob: str
    spread: float
    variance_share: float
    ci_low: float
    ci_high: float
    label: str
    best_value: Any
    best_value_mean_acc: float
    cost_effect: float | None
    cost_effect_pct: float | None
    worst_value: Any
    worst_value_mean_acc: float
    value_means: dict[str, float]
    group_sizes: dict[str, int]

    def required_dict(self) -> dict[str, Any]:
        return {
            "knob": self.knob,
            "spread": round_float(self.spread),
            "variance_share": round_float(self.variance_share),
            "ci_low": round_float(self.ci_low),
            "ci_high": round_float(self.ci_high),
            "label": self.label,
            "best_value": self.best_value,
            "best_value_mean_acc": round_float(self.best_value_mean_acc),
            "cost_effect": round_float_or_none(self.cost_effect),
        }


def round_float(value: float) -> float:
    return round(float(value), 6)


def round_float_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round_float(value)


def canonical_value(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def display_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def extract_metric(record: dict[str, Any], objective: str) -> float | None:
    if objective in record and isinstance(record[objective], (int, float)):
        return float(record[objective])
    metrics = record.get("metrics")
    if isinstance(metrics, dict) and isinstance(metrics.get(objective), (int, float)):
        return float(metrics[objective])
    return None


def extract_cost(record: dict[str, Any]) -> float | None:
    for key in ("cost", "mock_cost"):
        value = record.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    metrics = record.get("metrics")
    if isinstance(metrics, dict):
        for key in ("cost", "mock_cost"):
            value = metrics.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    return None


def read_trials(path: Path, objective: str) -> list[Trial]:
    trials: list[Trial] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{line_number}: invalid JSONL record: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: trial must be a JSON object")
            config = record.get("config")
            if not isinstance(config, dict):
                raise ValueError(f"{path}:{line_number}: missing object field 'config'")
            metric = extract_metric(record, objective)
            if metric is None:
                continue
            trials.append(
                Trial(
                    objective=metric,
                    config=dict(config),
                    cost=extract_cost(record),
                    raw=record,
                )
            )
    if not trials:
        raise ValueError(
            f"No trials with numeric objective '{objective}' found in {path}"
        )
    return trials


def read_config_space(path: Path | None) -> dict[str, list[Any]] | None:
    if path is None:
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: config-space JSON must be an object")
    config_space: dict[str, list[Any]] = {}
    for key, values in data.items():
        if isinstance(values, list):
            config_space[str(key)] = values
        else:
            config_space[str(key)] = [values]
    return config_space


def infer_knobs(
    trials: list[Trial], config_space: dict[str, list[Any]] | None
) -> list[str]:
    seen: set[str] = set()
    knobs: list[str] = []
    if config_space:
        for knob in config_space:
            if knob not in seen:
                knobs.append(knob)
                seen.add(knob)
    for trial in trials:
        for knob in trial.config:
            if knob not in seen:
                knobs.append(knob)
                seen.add(knob)
    return knobs


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def grouped_trials(trials: list[Trial], knob: str) -> dict[str, list[Trial]]:
    groups: dict[str, list[Trial]] = defaultdict(list)
    for trial in trials:
        if knob in trial.config:
            groups[canonical_value(trial.config[knob])].append(trial)
    return groups


def spread_for_groups(groups: dict[str, list[Trial]]) -> float:
    means = [
        mean([trial.objective for trial in group]) for group in groups.values() if group
    ]
    if len(means) < 2:
        return 0.0
    return max(means) - min(means)


def variance_share_for_groups(groups: dict[str, list[Trial]]) -> float:
    values = [trial.objective for group in groups.values() for trial in group]
    if len(values) < 2:
        return 0.0
    overall = mean(values)
    total_ss = sum((value - overall) ** 2 for value in values)
    if total_ss <= 0.0:
        return 0.0
    between_ss = 0.0
    for group in groups.values():
        if not group:
            continue
        group_values = [trial.objective for trial in group]
        between_ss += len(group_values) * (mean(group_values) - overall) ** 2
    return max(0.0, min(1.0, between_ss / total_ss))


def bootstrap_spread_ci(
    trials: list[Trial],
    knob: str,
    confidence: float,
    draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    relevant = [trial for trial in trials if knob in trial.config]
    if len(relevant) < 2 or draws <= 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    spreads: list[float] = []
    n = len(relevant)
    for _ in range(draws):
        sample = [relevant[rng.randrange(n)] for _ in range(n)]
        spreads.append(spread_for_groups(grouped_trials(sample, knob)))
    alpha = 1.0 - confidence
    return (
        percentile(spreads, alpha / 2.0),
        percentile(spreads, 1.0 - alpha / 2.0),
    )


def permutation_spread_pvalue(
    trials: list[Trial],
    knob: str,
    draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> float:
    """Label-shuffled permutation p-value for a knob's per-value mean spread.

    The max-min spread is non-negative by construction, so asking whether its own
    resample CI clears 0 is not a test against a no-effect null. Instead, under the
    null the knob value is unrelated to the objective: hold the per-value group
    sizes fixed and shuffle the objective values across trials, recomputing the
    spread each draw. The p-value is the fraction of shuffled-null spreads that
    reach the observed spread (add-one smoothed). A small p-value means the observed
    spread is larger than label-shuffled noise; a large one means it is not.
    """
    relevant = [trial for trial in trials if knob in trial.config]
    if len(relevant) < 2 or draws <= 0:
        return 1.0
    labels = [canonical_value(trial.config[knob]) for trial in relevant]
    if len(set(labels)) < 2:
        return 1.0
    observed = spread_for_groups(grouped_trials(relevant, knob))
    if observed <= 0.0:
        return 1.0
    objectives = [trial.objective for trial in relevant]
    rng = random.Random(seed)
    at_or_above = 0
    for _ in range(draws):
        shuffled = objectives[:]
        rng.shuffle(shuffled)
        groups: dict[str, list[float]] = defaultdict(list)
        for label_key, value in zip(labels, shuffled):
            groups[label_key].append(value)
        group_means = [mean(values) for values in groups.values() if values]
        null_spread = (
            max(group_means) - min(group_means) if len(group_means) >= 2 else 0.0
        )
        if null_spread >= observed:
            at_or_above += 1
    return (at_or_above + 1) / (draws + 1)


def value_from_key(groups: dict[str, list[Trial]], key: str, knob: str) -> Any:
    return groups[key][0].config[knob]


def analyze_knob(
    trials: list[Trial],
    knob: str,
    confidence: float,
    bootstrap_draws: int,
    total_n: int,
) -> KnobImportance | None:
    groups = grouped_trials(trials, knob)
    groups = {key: group for key, group in groups.items() if group}
    if len(groups) < 2:
        return None

    group_means = {
        key: mean([trial.objective for trial in group]) for key, group in groups.items()
    }
    best_key = max(group_means, key=lambda key: (group_means[key], key))
    worst_key = min(group_means, key=lambda key: (group_means[key], key))
    best_group = groups[best_key]
    worst_group = groups[worst_key]
    best_costs = [trial.cost for trial in best_group if trial.cost is not None]
    worst_costs = [trial.cost for trial in worst_group if trial.cost is not None]
    cost_effect: float | None = None
    cost_effect_pct: float | None = None
    if best_costs and worst_costs:
        best_cost = mean(best_costs)
        worst_cost = mean(worst_costs)
        cost_effect = best_cost - worst_cost
        if worst_cost != 0.0:
            cost_effect_pct = (cost_effect / worst_cost) * 100.0

    spread = max(group_means.values()) - min(group_means.values())
    ci_low, ci_high = bootstrap_spread_ci(
        trials=trials,
        knob=knob,
        confidence=confidence,
        draws=bootstrap_draws,
    )
    # Significance is gated against a label-shuffled no-effect null, not the CI
    # lower bound of a non-negative spread (which is > 0 for pure noise). The
    # bootstrap CI is retained only as a scale/whisker annotation.
    p_value = permutation_spread_pvalue(
        trials=trials,
        knob=knob,
        draws=bootstrap_draws,
    )
    alpha = 1.0 - confidence
    label = (
        "significant"
        if total_n >= 20 and spread > 0.0 and p_value < alpha
        else "directional"
    )

    return KnobImportance(
        knob=knob,
        spread=spread,
        variance_share=variance_share_for_groups(groups),
        ci_low=max(0.0, ci_low),
        ci_high=max(0.0, ci_high),
        label=label,
        best_value=value_from_key(groups, best_key, knob),
        best_value_mean_acc=group_means[best_key],
        cost_effect=cost_effect,
        cost_effect_pct=cost_effect_pct,
        worst_value=value_from_key(groups, worst_key, knob),
        worst_value_mean_acc=group_means[worst_key],
        value_means={
            display_value(value_from_key(groups, key, knob)): round_float(value)
            for key, value in sorted(group_means.items())
        },
        group_sizes={
            display_value(value_from_key(groups, key, knob)): len(group)
            for key, group in sorted(groups.items())
        },
    )


def analyze_importance(
    trials: list[Trial],
    config_space: dict[str, list[Any]] | None,
    confidence: float,
    bootstrap_draws: int,
) -> list[KnobImportance]:
    total_n = len(trials)
    rows: list[KnobImportance] = []
    for knob in infer_knobs(trials, config_space):
        row = analyze_knob(
            trials=trials,
            knob=knob,
            confidence=confidence,
            bootstrap_draws=bootstrap_draws,
            total_n=total_n,
        )
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda row: (-row.spread, -row.variance_share, row.knob))
    return rows


def attempt_sdk_importance(
    trials: list[Trial], objective: str
) -> tuple[str, dict[str, Any]]:
    try:
        with redirect_stderr(io.StringIO()):
            from traigent.utils.importance import ParameterImportanceAnalyzer
    except Exception as exc:  # pragma: no cover - depends on external SDK env
        return (
            "Traigent SDK ParameterImportanceAnalyzer was unavailable; used the "
            f"skill variance/bootstrap method. Import error: {type(exc).__name__}: {exc}",
            {},
        )

    try:
        sdk_trials = [
            SimpleNamespace(
                status="completed",
                metrics={objective: trial.objective},
                config=trial.config,
            )
            for trial in trials
        ]
        analyzer = ParameterImportanceAnalyzer(objective=objective)
        results = analyzer.analyze_variance_based(sdk_trials)
    except Exception as exc:  # pragma: no cover - defensive around SDK internals
        return (
            "Traigent SDK ParameterImportanceAnalyzer could not be adapted cleanly; "
            f"used the skill variance/bootstrap method. SDK error: {type(exc).__name__}: {exc}",
            {},
        )

    if not results:
        return (
            "Traigent SDK ParameterImportanceAnalyzer returned no variance-based output "
            "(often because sample size or trial shape was insufficient); used the "
            "skill variance/bootstrap method, inspired by the SDK analyzer.",
            {},
        )

    payload = {
        name: {
            "importance_score": round_float(result.importance_score),
            "confidence_interval": [
                round_float(result.confidence_interval[0]),
                round_float(result.confidence_interval[1]),
            ],
            "method": result.method,
            "sample_size": result.sample_size,
        }
        for name, result in sorted(results.items())
    }
    return (
        "Traigent SDK ParameterImportanceAnalyzer variance-based output was computed "
        "as a cross-check; ranking and labels in this report use the skill's "
        "bootstrap spread method.",
        payload,
    )


def read_heldout(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: heldout report must be a JSON object")
    return data


def heldout_card_metrics(
    heldout: dict[str, Any] | None,
    objective: str,
) -> tuple[float | None, float | None]:
    if not heldout:
        return (None, None)

    baseline = heldout.get("baseline")
    optimized = heldout.get("optimized")
    delta = heldout.get("delta")
    if not isinstance(baseline, dict):
        baseline = {}
    if not isinstance(optimized, dict):
        optimized = {}
    if not isinstance(delta, dict):
        delta = {}

    acc_delta = delta.get(objective)
    if not isinstance(acc_delta, (int, float)):
        base_acc = baseline.get(objective)
        opt_acc = optimized.get(objective)
        if isinstance(base_acc, (int, float)) and isinstance(opt_acc, (int, float)):
            acc_delta = float(opt_acc) - float(base_acc)
        else:
            acc_delta = None
    accuracy_pp = (
        float(acc_delta) * 100.0 if isinstance(acc_delta, (int, float)) else None
    )

    cost_key = None
    for key in ("cost", "mock_cost"):
        if isinstance(baseline.get(key), (int, float)) or isinstance(
            optimized.get(key), (int, float)
        ):
            cost_key = key
            break
    cost_delta_pct = None
    if cost_key:
        base_cost = baseline.get(cost_key)
        opt_cost = optimized.get(cost_key)
        if isinstance(base_cost, (int, float)) and float(base_cost) != 0.0:
            if isinstance(opt_cost, (int, float)):
                cost_delta_pct = (
                    (float(opt_cost) - float(base_cost)) / float(base_cost)
                ) * 100.0
            elif isinstance(delta.get(cost_key), (int, float)):
                cost_delta_pct = (float(delta[cost_key]) / float(base_cost)) * 100.0

    return (accuracy_pp, cost_delta_pct)


def write_importance_json(path: Path, rows: list[KnobImportance]) -> None:
    payload = [row.required_dict() for row in rows]
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_importance_csv(path: Path, rows: list[KnobImportance]) -> None:
    fieldnames = [
        "knob",
        "spread",
        "variance_share",
        "ci_low",
        "ci_high",
        "label",
        "best_value",
        "best_value_mean_acc",
        "cost_effect",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = row.required_dict()
            payload["best_value"] = display_value(payload["best_value"])
            writer.writerow(payload)


def svg_text(value: Any) -> str:
    return html.escape(str(value), quote=False)


def write_svg(
    path: Path,
    rows: list[KnobImportance],
    top_k: int,
    n_trials: int,
    objective: str,
    confidence: float,
) -> None:
    width = 1280
    height = 720
    top_rows = rows[:top_k]
    max_extent = max(
        [row.ci_high for row in top_rows] + [row.spread for row in top_rows] + [0.01]
    )
    chart_x = 330
    chart_y = 170
    chart_w = 760
    row_h = 92
    bar_h = 28
    axis_w = chart_w
    caption = (
        f"directional (n={n_trials}): fewer than 20 trials to test against a null"
        if n_trials < 20
        else f"n={n_trials}; significant requires the spread to beat a label-shuffled null at {int(confidence * 100)}% (CI whiskers show scale only)"
    )

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Significant tuned variables">',
        "<defs>",
        '<linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">',
        '<stop offset="0%" stop-color="#38bdf8"/>',
        '<stop offset="100%" stop-color="#22c55e"/>',
        "</linearGradient>",
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">',
        '<feDropShadow dx="0" dy="10" stdDeviation="10" flood-color="#000000" flood-opacity="0.35"/>',
        "</filter>",
        "</defs>",
        '<rect width="1280" height="720" fill="#08111f"/>',
        '<rect x="34" y="34" width="1212" height="652" rx="26" fill="#0f172a" stroke="#243244" filter="url(#shadow)"/>',
        '<text x="80" y="92" fill="#e5f0ff" font-family="Inter, Arial, sans-serif" font-size="34" font-weight="700">Which tuned variables drove the gain?</text>',
        f'<text x="80" y="130" fill="#91a4bd" font-family="Inter, Arial, sans-serif" font-size="18">Objective: {svg_text(objective)}. Bars show mean spread; whiskers show bootstrap CI.</text>',
        f'<text x="80" y="655" fill="#91a4bd" font-family="Inter, Arial, sans-serif" font-size="17">{svg_text(caption)}</text>',
        f'<line x1="{chart_x}" y1="{chart_y - 28}" x2="{chart_x + axis_w}" y2="{chart_y - 28}" stroke="#334155" stroke-width="1"/>',
        f'<text x="{chart_x}" y="{chart_y - 42}" fill="#91a4bd" font-family="Inter, Arial, sans-serif" font-size="15">0 pp</text>',
        f'<text x="{chart_x + axis_w - 90}" y="{chart_y - 42}" fill="#91a4bd" font-family="Inter, Arial, sans-serif" font-size="15">{max_extent * 100:.1f} pp</text>',
    ]

    for index, row in enumerate(top_rows):
        y = chart_y + index * row_h
        bar_w = max(2.0, (row.spread / max_extent) * axis_w)
        ci_low_x = chart_x + (row.ci_low / max_extent) * axis_w
        ci_high_x = chart_x + (row.ci_high / max_extent) * axis_w
        bar_y = y + 18
        label_color = "#86efac" if row.label == "significant" else "#facc15"
        value_note = f"best: {display_value(row.best_value)} ({row.best_value_mean_acc * 100:.1f}%)"
        parts.extend(
            [
                f'<text x="80" y="{y + 28}" fill="#f8fafc" font-family="Inter, Arial, sans-serif" font-size="23" font-weight="700">{svg_text(row.knob)}</text>',
                f'<text x="80" y="{y + 56}" fill="#91a4bd" font-family="Inter, Arial, sans-serif" font-size="16">{svg_text(value_note)}</text>',
                f'<rect x="{chart_x}" y="{bar_y}" width="{bar_w:.2f}" height="{bar_h}" rx="8" fill="url(#bar)"/>',
                f'<line x1="{ci_low_x:.2f}" y1="{bar_y + bar_h + 14}" x2="{ci_high_x:.2f}" y2="{bar_y + bar_h + 14}" stroke="#dbeafe" stroke-width="3" stroke-linecap="round"/>',
                f'<line x1="{ci_low_x:.2f}" y1="{bar_y + bar_h + 7}" x2="{ci_low_x:.2f}" y2="{bar_y + bar_h + 21}" stroke="#dbeafe" stroke-width="3"/>',
                f'<line x1="{ci_high_x:.2f}" y1="{bar_y + bar_h + 7}" x2="{ci_high_x:.2f}" y2="{bar_y + bar_h + 21}" stroke="#dbeafe" stroke-width="3"/>',
                f'<text x="{chart_x + axis_w + 24}" y="{y + 34}" fill="#e5f0ff" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="700">{row.spread * 100:.1f} pp</text>',
                f'<text x="{chart_x + axis_w + 24}" y="{y + 61}" fill="{label_color}" font-family="Inter, Arial, sans-serif" font-size="15" font-weight="700">{svg_text(row.label.upper())}</text>',
            ]
        )

    if not top_rows:
        parts.append(
            '<text x="80" y="220" fill="#f8fafc" font-family="Inter, Arial, sans-serif" font-size="24">No multi-value tuned variables found.</text>'
        )

    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def format_pp(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f} pp"


def format_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def write_video_card_json(
    path: Path,
    rows: list[KnobImportance],
    top_k: int,
    n_trials: int,
    objective: str,
    heldout: dict[str, Any] | None,
    slice_label: str = "this evaluation slice",
) -> dict[str, Any]:
    heldout_accuracy_pp, heldout_cost_delta_pct = heldout_card_metrics(
        heldout, objective
    )
    # Per-knob fields carry the knob's OWN measured effect, never the run-level
    # heldout delta — copying the whole-run gain onto every top knob overclaims
    # per-knob attribution. The run-level delta stays a single card-level field.
    top_variables: list[dict[str, Any]] = []
    for row in rows[:top_k]:
        top_variables.append(
            {
                "knob": row.knob,
                "best_value": row.best_value,
                "accuracy_pp": round_float(row.spread * 100.0),
                "cost_delta_pct": round_float_or_none(row.cost_effect_pct),
                "label": row.label,
            }
        )

    if heldout_accuracy_pp is not None or heldout_cost_delta_pct is not None:
        delta_clause = (
            f"heldout optimized-vs-baseline {format_pp(heldout_accuracy_pp)}, "
            f"{format_pct(heldout_cost_delta_pct)} cost"
        )
    else:
        delta_clause = (
            "card deltas use optimization-slice spread and best-vs-worst cost"
        )

    label_clause = (
        "directional only"
        if all(row.label == "directional" for row in rows[:top_k])
        else "mixed confidence"
    )
    payload = {
        "top_variables": top_variables,
        "n_trials": n_trials,
        "objective": objective,
        "heldout_accuracy_pp": round_float_or_none(heldout_accuracy_pp),
        "heldout_cost_delta_pct": round_float_or_none(heldout_cost_delta_pct),
        "caption": (
            f"On {slice_label}, in this run: "
            f"{label_clause}; {delta_clause}. "
            "Per-knob deltas are that knob's own effect; the heldout delta is "
            "run-level. Variable ranking is observational, not a causal proof."
        ),
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return payload


def write_insights_md(
    path: Path,
    rows: list[KnobImportance],
    n_trials: int,
    objective: str,
    confidence: float,
    heldout: dict[str, Any] | None,
    sdk_note: str,
    slice_label: str = "this evaluation slice",
) -> None:
    heldout_accuracy_pp, heldout_cost_delta_pct = heldout_card_metrics(
        heldout, objective
    )
    lines = [
        "# Significant Tuned Variables",
        "",
        f"On {slice_label}, in this run, {len(rows)} tuned variables had at least two observed values across {n_trials} trials.",
        "",
        "Honesty rule: with fewer than 20 trials, importances are labelled `directional`, not statistically significant. A variable is called `significant` only when its per-value spread beats a label-shuffled permutation (no-effect) null at the configured confidence; the bootstrap CI is a scale annotation, not the significance test.",
        "",
    ]
    if heldout_accuracy_pp is not None or heldout_cost_delta_pct is not None:
        lines.extend(
            [
                f"Heldout optimized-vs-baseline context: {format_pp(heldout_accuracy_pp)} {objective}, {format_pct(heldout_cost_delta_pct)} cost.",
                "",
            ]
        )
    lines.extend(["## Ranking", ""])
    if rows:
        for index, row in enumerate(rows, 1):
            cost_clause = (
                "cost unavailable"
                if row.cost_effect is None
                else f"cost effect vs worst value {row.cost_effect:+.6f}"
            )
            lines.append(
                f"{index}. `{row.knob}`: {row.spread * 100:.2f} pp spread, "
                f"variance share {row.variance_share:.3f}, "
                f"{int(confidence * 100)}% CI [{row.ci_low * 100:.2f}, {row.ci_high * 100:.2f}] pp, "
                f"`{row.label}`. Best observed value: `{display_value(row.best_value)}` "
                f"({row.best_value_mean_acc:.3f} mean {objective}); {cost_clause}."
            )
    else:
        lines.append("No multi-value tuned variables were available to rank.")
    lines.extend(
        [
            "",
            "## Method Note",
            "",
            "The primary ranking uses per-value mean objective spread, with variance-decomposition share reported as a companion statistic. Bootstrap intervals resample trials with replacement using seed 55.",
            "",
            sdk_note,
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank tuned variables by observed optimization importance and emit a video-card SVG."
    )
    parser.add_argument("--trials", required=True, type=Path, help="Trials JSONL path")
    parser.add_argument(
        "--config-space", type=Path, help="Optional config_space JSON path"
    )
    parser.add_argument(
        "--heldout", type=Path, help="Optional heldout report JSON path"
    )
    parser.add_argument(
        "--objective", default="accuracy", help="Objective field to maximize"
    )
    parser.add_argument(
        "--top-k", type=int, default=4, help="Number of variables on the SVG/card"
    )
    parser.add_argument(
        "--confidence", type=float, default=0.9, help="Bootstrap CI confidence"
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="Directory for artifacts"
    )
    parser.add_argument(
        "--slice-label",
        default="this evaluation slice",
        help="Human label for the eval slice used in captions, e.g. 'this HotpotQA slice'",
    )
    parser.add_argument(
        "--bootstrap-draws",
        type=int,
        default=DEFAULT_BOOTSTRAP_DRAWS,
        help="Bootstrap draws per knob; default 1000",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not 0.0 < args.confidence < 1.0:
        raise ValueError("--confidence must be between 0 and 1")
    if args.top_k < 1:
        raise ValueError("--top-k must be at least 1")
    if args.bootstrap_draws < 1:
        raise ValueError("--bootstrap-draws must be at least 1")


def main() -> int:
    args = parse_args()
    validate_args(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    trials = read_trials(args.trials, args.objective)
    config_space = read_config_space(args.config_space)
    heldout = read_heldout(args.heldout)
    rows = analyze_importance(
        trials=trials,
        config_space=config_space,
        confidence=args.confidence,
        bootstrap_draws=args.bootstrap_draws,
    )
    sdk_note, _sdk_payload = attempt_sdk_importance(trials, args.objective)

    write_importance_json(args.output_dir / "importance.json", rows)
    write_importance_csv(args.output_dir / "importance.csv", rows)
    write_svg(
        args.output_dir / "significant_variables.svg",
        rows=rows,
        top_k=args.top_k,
        n_trials=len(trials),
        objective=args.objective,
        confidence=args.confidence,
    )
    write_insights_md(
        args.output_dir / "insights.md",
        rows=rows,
        n_trials=len(trials),
        objective=args.objective,
        confidence=args.confidence,
        heldout=heldout,
        sdk_note=sdk_note,
        slice_label=args.slice_label,
    )
    video_card = write_video_card_json(
        args.output_dir / "video_card.json",
        rows=rows,
        top_k=args.top_k,
        n_trials=len(trials),
        objective=args.objective,
        heldout=heldout,
        slice_label=args.slice_label,
    )

    print(f"Wrote {len(rows)} ranked tuned variables to {args.output_dir}")
    if rows:
        for index, row in enumerate(rows[: args.top_k], 1):
            print(
                f"{index}. {row.knob}: spread={row.spread:.6f}, "
                f"variance_share={row.variance_share:.6f}, "
                f"ci=[{row.ci_low:.6f}, {row.ci_high:.6f}], "
                f"label={row.label}, best={display_value(row.best_value)}"
            )
    print(json.dumps(video_card, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
