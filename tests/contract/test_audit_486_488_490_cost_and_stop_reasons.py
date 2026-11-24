"""Issues #486, #488, #490: stop-reason table coverage and None-safe cost snippets.

Since SDK 0.31.0 ``ExperimentStats.total_cost`` / ``cost_per_configuration`` (and, since 0.32.0,
``OptimizationResult.total_cost``) are ``None`` whenever any trial cost is unmeasured. A snippet that
applies a float format spec to them raises ``TypeError`` after a paid run. These tests
execute the documented snippets against a stub result with unmeasured cost, so no SDK
install and no provider call is needed.
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
ANALYZE = ROOT / "skills" / "traigent-analyze-results"
OPTIMIZE_RUN = ROOT / "skills" / "traigent-optimize-run"
LITELLM = ROOT / "skills" / "traigent-setup-integrations" / "references" / "litellm.md"

# SDK `traigent.api.types.StopReason` literal (develop, includes the two values of #486).
SDK_STOP_REASONS = {
    "max_trials_reached",
    "max_samples_reached",
    "timeout",
    "cost_limit",
    "execution_budget",
    "metric_limit",
    "optimizer",
    "plateau",
    "convergence",
    "semantic_saturation",
    "safety_constraint",
    "safety_constraint_insufficient_evidence",
    "no_usage_captured",
    "user_cancelled",
    "condition",
    "error",
    "vendor_error",
    "network_error",
}


# Every page that tabulates stop reasons: (path, section heading, end of the section).
STOP_REASON_TABLES = [
    pytest.param(ANALYZE / "SKILL.md", "## Stop Reasons", "\n```python", id="analyze-results"),
    pytest.param(OPTIMIZE_RUN / "SKILL.md", "## Stop Conditions", "\n```python", id="optimize-run"),
    pytest.param(
        ANALYZE / "references" / "optimization-result-api.md",
        "## StopReason Values",
        "\n---",
        id="optimization-result-api",
    ),
]


def _stop_reason_rows(
    path: Path = ANALYZE / "SKILL.md",
    heading: str = "## Stop Reasons",
    end: str = "\n```python",
) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    parts = text.split(heading, 1)
    assert len(parts) == 2, f"{path.name}: {heading!r} section moved"
    section = parts[1].split(end, 1)[0]
    rows: dict[str, str] = {}
    for line in section.splitlines():
        match = re.match(r'\| `"([a-z_]+)"` \|(.*)\|\s*$', line)
        if match:
            rows[match.group(1)] = match.group(2)
    return rows


@pytest.mark.parametrize(("path", "heading", "end"), STOP_REASON_TABLES)
def test_stop_reason_table_covers_every_sdk_value(path: Path, heading: str, end: str) -> None:
    rows = _stop_reason_rows(path, heading, end)
    assert SDK_STOP_REASONS - set(rows) == set(), path
    assert set(rows) - SDK_STOP_REASONS == set(), path


@pytest.mark.parametrize(("path", "heading", "end"), STOP_REASON_TABLES)
def test_stop_reason_table_matches_installed_sdk_when_present(
    path: Path, heading: str, end: str
) -> None:
    types_mod = pytest.importorskip("traigent.api.types")
    import typing

    sdk = set(typing.get_args(types_mod.StopReason))
    assert sdk - set(_stop_reason_rows(path, heading, end)) == set(), path


@pytest.mark.parametrize(("path", "heading", "end"), STOP_REASON_TABLES)
def test_safety_constraint_row_is_version_qualified(path: Path, heading: str, end: str) -> None:
    # Since SDK 0.31.0 "too little evidence" is its own reason; the plain row must say
    # the old meaning held only on 0.28.0-0.30.0.
    row = _stop_reason_rows(path, heading, end)["safety_constraint"]
    assert "0.31.0" in row, path
    assert re.search(r"0\.28\.0\s*[-\u2013]\s*0\.30\.0", row), path


def test_insufficient_evidence_row_says_not_checked_not_violated() -> None:
    row = _stop_reason_rows()["safety_constraint_insufficient_evidence"]
    assert "not proven" in row
    assert "not a violation" in row


def test_no_usage_captured_row_names_strict_cost_and_error_result() -> None:
    row = _stop_reason_rows()["no_usage_captured"]
    assert "UnknownModelError" in row and "err.result" in row


def _python_blocks(path: Path) -> list[str]:
    return re.findall(r"```python\n(.*?)```", path.read_text(encoding="utf-8"), re.S)


_SNIPPETS = [
    (OPTIMIZE_RUN / "references" / "cost-management.md", "Stopped at cost limit"),
    (OPTIMIZE_RUN / "references" / "cost-management.md", "Per-trial objective values"),
    (ANALYZE / "SKILL.md", "Aggregated experiment statistics"),
    (LITELLM, "Traigent aggregates cost across all trials"),
]


def _stub_results(floor: float | None = 0.05) -> SimpleNamespace:
    """A run with two unmeasured trials. ``floor`` is the known spend: the SDK
    reports ``cost_floor_usd=0.0`` and ``cost_lower_bound=None`` when every
    trial is unmeasured, and ``cost_unmeasured_trials`` in ``metrics`` is a float."""
    trial = SimpleNamespace(
        trial_id="t1",
        metrics={"accuracy": 0.9},
        config={"model": "m", "max_tokens": 64},
        get_metric=lambda name, default=None: {"accuracy": 0.9}.get(name, default),
    )
    stats = SimpleNamespace(
        total_duration=1.0,
        total_cost=None,
        unique_configurations=2,
        average_trial_duration=0.5,
        cost_per_configuration=None,
        cost_unmeasured_trials=2,
        cost_lower_bound=floor or None,
        trial_counts={"total": 2},
    )
    results = SimpleNamespace(
        total_cost=None,
        total_tokens=None,
        stop_reason="cost_limit",
        metrics={
            "cost_unmeasured_trials": 2.0,
            **({} if floor is None else {"cost_floor_usd": floor}),
        },
        trials=[trial],
        successful_trials=[trial],
        best_config={"model": "m", "max_tokens": 64},
        best_score=0.9,
        experiment_stats=stats,
        best_metrics={"accuracy": 0.9},
    )
    return results


@pytest.mark.parametrize(
    "floor",
    [0.05, 0.0031, 0.00001, 0.0, None],
    ids=["floor", "sub-cent-floor", "sub-resolution-floor", "zero-floor", "no-floor"],
)
@pytest.mark.parametrize(("path", "marker"), _SNIPPETS)
def test_cost_snippet_runs_with_unmeasured_cost(
    path: Path, marker: str, floor: float | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocks = [b for b in _python_blocks(path) if marker in b]
    assert len(blocks) == 1, (path, marker)
    results = _stub_results(floor)
    exceptions = types.ModuleType("traigent.utils.exceptions")
    exceptions.CostLimitExceeded = type("CostLimitExceeded", (Exception,), {})  # type: ignore[attr-defined]
    exceptions.OptimizationError = type("OptimizationError", (Exception,), {})  # type: ignore[attr-defined]
    for name in ("traigent", "traigent.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "traigent.utils.exceptions", exceptions)
    func = SimpleNamespace(optimize_sync=lambda **_: results)
    namespace = {"func": func, "answer": func, "results": results}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(blocks[0], str(path), "exec"), namespace)  # noqa: S102
    printed = out.getvalue()
    # An unmeasured cost must never be shown as a dollar amount of zero.
    assert not re.search(r"\$0\.0+(?!\d)", printed), printed
    # A trial count is a whole number even when the SDK stores it as a float.
    assert "2.0 trial" not in printed, printed
    # A positive floor is never rounded down to a dollar amount that reads as zero:
    # either its real digits appear, or the text says it is below the print resolution.
    if floor and re.search(r"cost_floor_usd|cost_lower_bound", blocks[0]):
        assert f"{floor:.4f}" in printed or "under $0.0001" in printed, printed
        assert not re.search(r"\$0\.0+(?!\d)", printed), printed


def _litellm_summary_snippet() -> str:
    block = next(b for b in _python_blocks(LITELLM) if "# Analyze results" in b)
    return block.split("# Analyze results", 1)[1].split("# Apply best config", 1)[0]


@pytest.mark.parametrize(
    ("total_cost", "expect"),
    [
        (None, "not measured"),
        # A live run maps a non-positive total to None (SDK core/orchestrator.py), but a persisted
        # result reloads total_cost verbatim, so 0.0 must still read as not measured.
        (0.0, "not measured"),
        (0.0123, "$0.0123"),
    ],
)
def test_litellm_summary_tells_unmeasured_from_zero(total_cost: float | None, expect: str) -> None:
    results = _stub_results()
    results.total_cost = total_cost
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(_litellm_summary_snippet(), str(LITELLM), "exec"), {"results": results})  # noqa: S102
    printed = out.getvalue()
    assert expect in printed, printed
    assert not re.search(r"\$0\.0+(?!\d)", printed), printed


API_DOC = ANALYZE / "references" / "optimization-result-api.md"


def _field_rows(heading: str) -> dict[str, str]:
    """Field-table rows of one ``## <heading>`` section of the API reference."""
    text = API_DOC.read_text(encoding="utf-8")
    parts = re.split(rf"^## {re.escape(heading)}\s*$", text, maxsplit=1, flags=re.M)
    assert len(parts) == 2, f"{heading!r} section moved"
    section = re.split(r"^## ", parts[1], maxsplit=1, flags=re.M)[0]
    rows: dict[str, str] = {}
    for line in section.splitlines():
        match = re.match(r"\| `([a-z_]+)` \|(.*)\|\s*$", line)
        if match:
            rows.setdefault(match.group(1), match.group(2))
    return rows


def test_experiment_stats_table_marks_total_cost_nullable() -> None:
    row = _field_rows("ExperimentStats")["total_cost"]
    assert "float \\| None" in row
    assert "unmeasured" in row


def test_experiment_stats_table_lists_the_unmeasured_cost_fields() -> None:
    rows = _field_rows("ExperimentStats")
    assert "`int`" in rows["cost_unmeasured_trials"]
    assert "float \\| None" in rows["cost_lower_bound"]


def test_optimization_result_total_cost_names_unmeasured_case() -> None:
    row = _field_rows("OptimizationResult")["total_cost"]
    assert "0.32.0" in row and "unmeasured" in row
    assert "cost_floor_usd" in row
