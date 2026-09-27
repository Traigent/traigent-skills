"""Function-side cost reporting must reach `results.total_cost`.

Runs the optimize-run `traigent.with_usage` snippet, its tuple form, and the
structural-spine form (custom accuracy metric reading the wrapper's text) on the
installed SDK. Each must report per-example cost x dataset size. Also keeps the
Python skills from teaching reserved cost keys in the function's metrics.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.version import Version

from .extract import _iter_fenced_blocks
from .test_runnable_snippets import _offline_mock_env


ROOT = Path(__file__).resolve().parents[2]
RUN_SKILL = ROOT / "skills" / "traigent-optimize-run" / "SKILL.md"
SPINE = (
    ROOT / "skills" / "traigent-optimize-config-space" / "references" / "structural-spine.md"
)
DATASET = (
    '{"input": {"question": "What is 2+2?"}, "output": "4"}\n'
    '{"input": {"question": "Capital of France?"}, "output": "Paris"}\n'
    '{"input": {"question": "Color of the sky?"}, "output": "blue"}\n'
)

DRIVER = r'''
import json
import traigent
import traigent.testing

traigent.testing.enable_mock_mode_for_quickstart()
import snippet

out = {}
r = snippet.answer.optimize_sync(max_trials=1, algorithm="grid")
out["documented"] = {"total_cost": r.total_cost, "trial_cost": r.trials[0].metrics.get("cost"),
                     "accuracy": r.trials[0].metrics.get("accuracy")}


@traigent.optimize(eval_dataset="qa_test.jsonl", objectives=["accuracy", "cost"], offline=True,
                   configuration_space={"prompt_style": ["short"]})
def tuple_form(question: str):
    traigent.get_config()
    return traigent.with_usage("4", total_cost=0.01), {"latency_ms": 5.0}


r = tuple_form.optimize_sync(max_trials=1, algorithm="grid")
out["tuple"] = {"total_cost": r.total_cost, "latency_ms": r.trials[0].metrics.get("latency_ms"),
                "accuracy": r.trials[0].metrics.get("accuracy")}


spine_received = []


def accuracy_metric(output, expected, **kwargs):
    spine_received.append(type(output).__name__)
    text = output["text"] if isinstance(output, dict) else output
    return 0.9 if text == expected else 0.0   # 0.9, not 1.0: tells it apart from built-in


@traigent.optimize(eval_dataset="qa_test.jsonl", objectives=["accuracy", "cost"], offline=True,
                   configuration_space={"prompt_style": ["short"]},
                   metric_functions={"accuracy": accuracy_metric})
def spine_form(question: str):
    traigent.get_config()
    return traigent.with_usage("4", total_cost=0.01)


r = spine_form.optimize_sync(max_trials=1, algorithm="grid")
out["spine"] = {"total_cost": r.total_cost, "accuracy": r.trials[0].metrics.get("accuracy"),
                "received": sorted(set(spine_received))}
out["outside"] = snippet.call_my_endpoint("q", "short")[0] == traigent.with_usage("4", total_cost=0.01)
print("PROBE_JSON=" + json.dumps(out))
'''

CAP_DRIVER = r'''
import json
import traigent
import traigent.testing

traigent.testing.enable_mock_mode_for_quickstart()


@traigent.optimize(eval_dataset="qa_test.jsonl", objectives=["accuracy", "cost"], offline=True,
                   configuration_space={"prompt_style": ["a", "b", "c", "d", "e"]})
def answer(question: str):
    traigent.get_config()
    return traigent.with_usage("4", total_cost=0.01)


r = answer.optimize_sync(max_trials=5, algorithm="grid")
print("PROBE_JSON=" + json.dumps({"stop_reason": r.stop_reason, "trials": len(r.trials)}))
'''


def _with_usage_snippet() -> str:
    blocks = [
        block.text
        for block in _iter_fenced_blocks(RUN_SKILL.read_text(encoding="utf-8").splitlines())
        if block.language == "python" and "traigent.with_usage(" in block.text
    ]
    assert blocks, "optimize-run SKILL.md documents no traigent.with_usage snippet"
    return blocks[0]


def _run(tmp_path: Path, driver: str, extra_env: dict[str, str] | None = None) -> dict:
    (tmp_path / "qa_test.jsonl").write_text(DATASET, encoding="utf-8")
    (tmp_path / "driver.py").write_text(driver, encoding="utf-8")
    env = _offline_mock_env()
    env["HOME"] = str(tmp_path)
    env.update(extra_env or {})
    completed = subprocess.run(
        [sys.executable, "driver.py"], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(r for r in completed.stdout.splitlines() if r.startswith("PROBE_JSON="))
    return json.loads(line.split("=", 1)[1])


@pytest.fixture()
def sdk_027(sdk_version_label: str) -> None:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.27.0"):
        pytest.skip("function-side cost behaviour verified on SDK 0.27.0+")


def test_documented_cost_forms_reach_results_total_cost(tmp_path: Path, sdk_027) -> None:
    (tmp_path / "snippet.py").write_text(_with_usage_snippet(), encoding="utf-8")
    data = _run(tmp_path, DRIVER)
    expected_total = 0.01 * 3
    assert data["documented"]["total_cost"] == pytest.approx(expected_total)
    assert data["documented"]["trial_cost"] == pytest.approx(expected_total)
    assert data["documented"]["accuracy"] == pytest.approx(1 / 3)
    assert data["tuple"]["total_cost"] == pytest.approx(expected_total)
    assert data["tuple"]["latency_ms"] == pytest.approx(5.0)
    assert data["tuple"]["accuracy"] == pytest.approx(1 / 3)
    assert data["spine"]["total_cost"] == pytest.approx(expected_total)
    # The custom metric ran (0.9 per match, not the built-in 1.0) on the wrapper dict,
    # which is why the docs say to score output["text"].
    assert data["spine"]["received"] == ["dict"]
    assert data["spine"]["accuracy"] == pytest.approx(0.9 / 3)
    # Outside an optimization run `with_usage` hands back the plain text.
    assert data["outside"] is True


def test_function_side_cost_reaches_the_cost_cap(tmp_path: Path, sdk_027) -> None:
    data = _run(tmp_path, CAP_DRIVER, {"TRAIGENT_RUN_COST_LIMIT": "0.05"})
    assert data["stop_reason"] == "cost_limit"
    assert data["trials"] < 5


def test_python_skills_do_not_teach_reserved_cost_keys() -> None:
    run_text = RUN_SKILL.read_text(encoding="utf-8")
    assert "per-trial metrics using `total_cost`, `cost`" not in run_text
    spine_text = SPINE.read_text(encoding="utf-8")
    assert '"cost": cost_metric' not in spine_text
    assert "traigent.with_usage(answer, total_cost=" in spine_text
