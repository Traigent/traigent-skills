"""Mock mode does not bypass runtime cost enforcement; the env var is deprecated.

Pins versioned mock-mode admission and reported-cost enforcement on the installed
SDK. The observed-mean policy first admits a trial and distinguishes reported
zero cost from unknown cost. Positive controls report synthetic telemetry, never
provider spend. Lints the optimize skill files so
a `TRAIGENT_MOCK_LLM=true` recipe always sits next to its deprecation note.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.version import Version

from .test_runnable_snippets import _offline_mock_env


ROOT = Path(__file__).resolve().parents[2]
# Optimize-skill files that mention the env var. Other skills that teach it are
# covered by their own fixes; extend this list as they land.
LINTED = [
    ROOT / "skills" / "traigent-optimize-run" / "SKILL.md",
    ROOT / "skills" / "traigent-optimize-run" / "references" / "cost-management.md",
]
NEAR_LINES = 3
# Any way of SETTING the env var: `X=1`, `X="true"`, `os.environ["X"] = ...`,
# `setenv("X", ...)`, `environ.setdefault("X", ...)`. A bare mention (the
# "check it is unset" guardrail) is not an assignment.
ASSIGN_RE = re.compile(
    r"""TRAIGENT_MOCK_LLM\s*=(?!=)"""
    r"""|TRAIGENT_MOCK_LLM['"]\s*\]\s*=(?!=)"""
    r"""|(?:setenv|setdefault|putenv)\(\s*['"]TRAIGENT_MOCK_LLM['"]"""
)

PROBE = r'''
import json
import os
import traigent
from pathlib import Path

if os.environ.get("USE_IN_CODE_MOCK") == "1":
    import traigent.testing
    traigent.testing.enable_mock_mode_for_quickstart()
Path("qa.jsonl").write_text('{"input": {"question": "q"}, "output": "4"}\n')

@traigent.optimize(eval_dataset="qa.jsonl", objectives=["accuracy"], offline=True,
                   configuration_space={"model": ["gpt-4o-mini", "gpt-4o"],
                                        "temperature": [0.1, 0.5]})
def f(question: str) -> str:
    traigent.get_config()
    return "4"

r = f.optimize_sync(max_trials=4, algorithm="grid")
print("PROBE_JSON=" + json.dumps({"stop_reason": r.stop_reason, "trials": len(r.trials)}))
'''


def _uses_observed_mean_admission(sdk_version_label: str) -> bool:
    """SDK #2561: observed mean replaces the seeded estimate after 0.30.0."""
    return sdk_version_label == "develop" or Version(sdk_version_label) >= Version("0.31.0.dev0")


TRACKED_COST_PROBE = r'''
import json
import os
import socket

def deny_network(*args, **kwargs):
    raise RuntimeError("mock-cost contract probe refuses network")

socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network
socket.getaddrinfo = deny_network

import traigent
from traigent.evaluators.base import Dataset, EvaluationExample, ExampleResult
from traigent.utils.exceptions import OptimizationError

if os.environ.get("USE_IN_CODE_MOCK") == "1":
    from traigent.testing import enable_mock_mode_for_quickstart
    enable_mock_mode_for_quickstart()

case = os.environ["COST_CASE"]
seen = []

def evaluator(func, config, example):
    seen.append(config["variant"])
    metrics = {"accuracy": 1.0}
    if case != "unknown":
        # Deterministic reported telemetry, not billed provider usage.
        metrics["cost"] = 0.00006 if case == "positive" else 0.0
    return ExampleResult(
        example_id="one", input_data=example.input_data,
        expected_output=example.expected_output, actual_output="4",
        metrics=metrics, execution_time=0.001, success=True,
    )

@traigent.optimize(
    eval_dataset=Dataset([EvaluationExample({"question": "q"}, "4")]),
    objectives=["accuracy"], offline=True, injection_mode="parameter",
    custom_evaluator=evaluator, configuration_space={"variant": [0, 1, 2, 3]},
)
def f(question, config):
    return "4"

try:
    r = f.optimize_sync(max_trials=4, algorithm="grid")
except OptimizationError as exc:
    print("PROBE_JSON=" + json.dumps({"error": type(exc).__name__,
        "message": str(exc), "seen": seen}))
else:
    print("PROBE_JSON=" + json.dumps({"stop_reason": r.stop_reason,
        "trials": len(r.trials), "seen": seen,
        "trial_costs": [t.metrics.get("total_cost") for t in r.trials]}))
'''


def _run(
    tmp_path: Path, extra_env: dict[str, str], probe: str = PROBE
) -> tuple[dict, str]:
    (tmp_path / "probe.py").write_text(probe, encoding="utf-8")
    env = _offline_mock_env()
    env.update({"HOME": str(tmp_path), "TRAIGENT_RUN_COST_LIMIT": "0.0001"})
    env.update(extra_env)
    completed = subprocess.run(
        [sys.executable, "-W", "always::DeprecationWarning", "probe.py"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(r for r in completed.stdout.splitlines() if r.startswith("PROBE_JSON="))
    return json.loads(line.split("=", 1)[1]), completed.stderr


@pytest.mark.parametrize(
    "extra_env",
    [{"USE_IN_CODE_MOCK": "1"}, {"TRAIGENT_MOCK_LLM": "true"}],
    ids=["in-code-mock", "legacy-env-var"],
)
def test_mock_zero_cost_admission_matches_sdk_version(
    tmp_path: Path, sdk_version_label: str, extra_env: dict[str, str]
) -> None:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.27.0"):
        pytest.skip("mock-mode cost enforcement verified on SDK 0.27.0+")
    data, stderr = _run(tmp_path, extra_env)
    expected = (
        {"stop_reason": "max_trials_reached", "trials": 4}
        if _uses_observed_mean_admission(sdk_version_label)
        else {"stop_reason": "cost_limit", "trials": 0}
    )
    assert data == expected
    if "TRAIGENT_MOCK_LLM" in extra_env:
        assert "TRAIGENT_MOCK_LLM is deprecated" in stderr


@pytest.mark.parametrize(
    "extra_env",
    [{"USE_IN_CODE_MOCK": "1"}, {"TRAIGENT_MOCK_LLM": "true"}],
    ids=["in-code-mock", "legacy-env-var"],
)
@pytest.mark.parametrize("case", ["zero", "positive", "unknown"])
def test_mock_reported_cost_admission_contract(
    tmp_path: Path, sdk_version_label: str, extra_env: dict[str, str], case: str
) -> None:
    data, stderr = _run(tmp_path, {**extra_env, "COST_CASE": case}, TRACKED_COST_PROBE)
    if not _uses_observed_mean_admission(sdk_version_label):
        # Preserve the released SDK's seeded cold-start rejection.
        assert data == {"stop_reason": "cost_limit", "trials": 0,
                        "seen": [], "trial_costs": []}
    elif case == "unknown":
        assert data["error"] == "OptimizationError"
        assert "completed without a reported cost" in data["message"]
        assert data["seen"] == [0]
    elif case == "positive":
        # One observed 0.00006 cost plus the same next-trial mean exceeds 0.0001.
        assert data == {"stop_reason": "cost_limit", "trials": 1,
                        "seen": [0], "trial_costs": [0.00006]}
    else:
        assert data == {"stop_reason": "max_trials_reached", "trials": 4,
                        "seen": [0, 1, 2, 3], "trial_costs": [0.0] * 4}
    if "TRAIGENT_MOCK_LLM" in extra_env and (
        sdk_version_label == "develop" or Version(sdk_version_label) >= Version("0.27.0")
    ):
        assert "TRAIGENT_MOCK_LLM is deprecated" in stderr


@pytest.mark.parametrize(
    ("label", "expected"),
    [("0.30.0", False), ("0.31.0.dev0", True), ("0.31.0", True), ("develop", True)],
)
def test_observed_mean_admission_version_boundary(label: str, expected: bool) -> None:
    assert _uses_observed_mean_admission(label) is expected


def test_skill_files_do_not_claim_a_mock_cost_bypass() -> None:
    text = (ROOT / "skills" / "traigent-optimize-run" / "references" / "cost-management.md").read_text(
        encoding="utf-8"
    )
    assert "cost tracking is bypassed" not in text
    assert "No permits are issued" not in text
    assert "still bypasses cost tracking" not in text
    assert "bypass cost tracking in mock mode" not in text
    assert 'stop_reason="cost_limit"` apply in mock runs too' in text


def test_mock_env_var_recipes_carry_a_deprecation_note() -> None:
    for path in LINTED:
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not ASSIGN_RE.search(line):
                continue
            window = lines[max(0, index - NEAR_LINES): index + NEAR_LINES + 1]
            assert any("deprecated" in item.lower() for item in window), (
                f"{path.relative_to(ROOT)}:{index + 1}: TRAIGENT_MOCK_LLM is set "
                "without a nearby deprecation note"
            )
