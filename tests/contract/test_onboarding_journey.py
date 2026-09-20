"""Local documented journey: real SDK, canned provider, no live portal proof.

Run snippets in a fresh process so mock patches, credentials and SDK state cannot
leak between cases. The socket hook is a tripwire, not OS network isolation.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from packaging.version import Version

from .extract import _iter_fenced_blocks
from .test_runnable_snippets import _offline_mock_env


ROOT = Path(__file__).resolve().parents[2]


def _python_blocks(relative: str) -> list[str]:
    return [
        block.text
        for block in _iter_fenced_blocks((ROOT / relative).read_text().splitlines())
        if block.language == "python"
    ]


@pytest.fixture()
def journey(tmp_path: Path, sdk_version_label: str):
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.24.0"):
        pytest.skip("the documented promotion workflow requires SDK 0.24.0+")
    quickstart = next(
        block for block in _python_blocks("skills/traigent-setup-quickstart/SKILL.md")
        if "def classify_query(" in block
    )
    gate = next(
        block for block in _python_blocks(
            "skills/traigent-ci-safety-gate/references/gate-workflow.md"
        ) if "def metric_series(" in block
    )
    holdout = next(
        block for block in _python_blocks(
            "skills/traigent-ci-safety-gate/references/gate-workflow.md"
        ) if "def evaluate_one(" in block
    )
    (tmp_path / "quickstart.py").write_text(quickstart)
    (tmp_path / "gate.py").write_text(gate)
    (tmp_path / "holdout.py").write_text(holdout)
    env = _offline_mock_env()
    env.update({"TRAIGENT_DATASET_ROOT": str(tmp_path), "TRAIGENT_RUN_APPROVED": "1"})

    def run(body: str) -> subprocess.CompletedProcess[str]:
        runner = tmp_path / "journey.py"
        runner.write_text(
            "import asyncio, json, socket, sys\n"
            "from pathlib import Path\n"
            "attempts = []\n"
            "def deny_connect(*args, **kwargs):\n"
            "    attempts.append('network attempt')\n"
            "    raise AssertionError('unexpected network attempt in local journey')\n"
            "socket.socket.connect = deny_connect\n"
            "socket.socket.connect_ex = deny_connect\n"
            "import quickstart, gate, holdout\n" + body + "\n"
            "assert not attempts, attempts\n"
        )
        completed = subprocess.run(
            [sys.executable, str(runner)], cwd=tmp_path, env=env,
            text=True, capture_output=True, timeout=120, check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return completed

    return run


def test_documented_mock_journey_reaches_holdout_gate_without_promotion(journey) -> None:
    result = journey('''
from traigent.integrations.utils.mock_adapter import MockAdapter
provider_calls = []
mock_completion = MockAdapter.get_mock_response
def observe_mock_completion(*args, **kwargs):
    provider_calls.append(1)
    return mock_completion(*args, **kwargs)
MockAdapter.get_mock_response = staticmethod(observe_mock_completion)
result = asyncio.run(quickstart.main())
assert provider_calls, "journey did not reach the provider boundary"
assert result.best_config is not None
assert len(result.trials) == 6
assert result.cloud_url is None
assert Path("eval_queries.jsonl").is_file()
# The actual SDK writes the config artifact consumed by the next workflow.
quickstart.classify_query.export_config("candidate.json")
assert json.loads(Path("candidate.json").read_text())
# Execute the documented holdout adapter in mock mode against a separate file.
# Its canned measurements prove wiring, not a quality improvement.
Path("incumbent.json").write_text(Path("candidate.json").read_text())
Path("holdout.jsonl").write_text("".join(json.dumps({"input": f"unseen question {i}", "expected_output": "billing"}) + "\\n" for i in range(20)))
for name in ("incumbent", "candidate"):
    sys.argv = ["holdout.py", "--mode", "mock", "--config", name + ".json", "--holdout", "holdout.jsonl", "--output", name + "-holdout.json"]
    holdout.main()
# Equal candidate/incumbent scores must not authorize promotion.
sys.argv = ["gate.py", "--incumbent", "incumbent-holdout.json", "--candidate", "candidate-holdout.json", "--max-cost", "0.01", "--max-latency-ms", "1200", "--require-promote"]
assert gate.main() != 0
''')
    assert "demo only" in result.stdout.lower()
    assert "promotion_decision=" in result.stdout


@pytest.mark.parametrize("cost", [None, -1.0, float("nan"), float("inf")])
def test_documented_gate_refuses_unmeasured_or_invalid_cost(journey, cost) -> None:
    literal = repr(cost) if cost is None or cost == -1.0 else f"float({str(cost)!r})"
    journey(f'''
try:
    gate.cost({{"total_cost": {literal}}})
except SystemExit:
    pass
else:
    raise AssertionError("invalid cost authorized promotion")
''')


def test_documented_journey_exhausted_budget_stops_before_provider(journey, sdk_version_label) -> None:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.26.0"):
        pytest.skip("ExecutionBudget was added in SDK 0.26.0")
    journey('''
from traigent import ExecutionBudget
from traigent.integrations.utils.mock_adapter import MockAdapter
budget = ExecutionBudget(max_cost_usd=0.01)
budget.debit_trial(cost=0.01)
calls = []
def unexpected_provider(*args, **kwargs):
    calls.append(1)
    raise AssertionError("exhausted budget entered provider")
MockAdapter.get_mock_response = staticmethod(unexpected_provider)
result = quickstart.classify_query.optimize_sync(max_trials=6, budget=budget)
assert result.stop_reason == "execution_budget", result.stop_reason
assert not result.trials
assert result.best_config is None
assert not calls
''')


def test_documented_journey_with_failed_trials_does_not_apply_a_winner(journey) -> None:
    result = journey('''
import traigent
@traigent.optimize(eval_dataset="eval_queries.jsonl", objectives=["accuracy"],
                   algorithm="grid", offline=True, temperature=traigent.Choices([0.0, 1.0]))
def failing_agent(query):
    raise ValueError("intentional provider failure fixture")
quickstart.classify_query = failing_agent
calls = []
def unexpected_apply(*args, **kwargs):
    calls.append(1)
    raise AssertionError("failed run applied a configuration")
failing_agent.apply_best_config = unexpected_apply
result = asyncio.run(quickstart.main())
assert result.best_config is None
assert not calls
''')
    assert "No eligible winner" in result.stdout
