"""Custom scorers DO run on the `(output, metrics)` tuple path.

Pins the SDK behaviour the composite-knobs skill documents: a `scoring_function`
or a 3-arg `metric_functions` entry receives the unpacked string output and its
value becomes the objective; a non-reserved tuple key can be an objective; a
reserved tuple key is dropped with a WARNING. Also keeps the skill from
re-teaching the retired "scorer is not invoked" warning.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.version import Version

from .test_runnable_snippets import _offline_mock_env


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "traigent-optimize-composite-knobs" / "SKILL.md"

PROBE = r'''
import json
import traigent
import traigent.testing
from pathlib import Path
from traigent.core.objectives import create_default_objectives
from traigent.evaluators.metrics_tracker import RESERVED_METRIC_KEYS

traigent.testing.enable_mock_mode_for_quickstart()
Path("qa.jsonl").write_text(
    '{"input": {"question": "What is 2+2?"}, "output": "4"}\n'
    '{"input": {"question": "Capital of France?"}, "output": "Paris"}\n'
    '{"input": {"question": "Color of the sky?"}, "output": "blue"}\n'
)
received = []

def scorer(output, expected, **kwargs):
    received.append(type(output).__name__)
    return 0.11 if isinstance(output, tuple) else 0.77

def custom(output, expected, input_data=None):
    received.append(type(output).__name__)
    return 0.66

def custom_objective(name):
    # Custom objective names need an explicit orientation on newer SDKs; this is
    # setup only and the same schema is accepted on 0.27.0.
    return create_default_objectives([name], orientations={name: "maximize"})

def run(objectives, fn_return, **deco):
    @traigent.optimize(eval_dataset="qa.jsonl", objectives=objectives, offline=True,
                       configuration_space={"model": ["m"]}, **deco)
    def answer(question: str):
        return fn_return
    return answer.optimize_sync(max_trials=1, algorithm="grid").trials[0].metrics

out = {}
m = run(["accuracy"], ("4", {"side_metric": 1.0}), scoring_function=scorer)
out["scorer"] = {"accuracy": m["accuracy"], "side": m.get("side_metric"), "received": sorted(set(received))}
received.clear()
m = run(custom_objective("custom"), ("4", {"side_metric": 1.0}), metric_functions={"custom": custom})
out["metric_fn"] = {"custom": m["custom"], "received": sorted(set(received))}
m = run(custom_objective("custom_match"), ("4", {"custom_match": 0.42}))
out["tuple_key"] = {"custom_match": m.get("custom_match")}
m = run(["accuracy"], ("wrong", {"accuracy": 0.99}))
out["reserved"] = {"accuracy": m["accuracy"]}
out["reserved_keys"] = sorted(RESERVED_METRIC_KEYS)
print("PROBE_JSON=" + json.dumps(out, sort_keys=True))
'''


@pytest.fixture(scope="module")
def probe(tmp_path_factory: pytest.TempPathFactory, pytestconfig: pytest.Config):
    from .conftest import _sdk_version_label

    label = _sdk_version_label(pytestconfig)
    if label != "develop" and Version(label) < Version("0.24.0"):
        pytest.skip("scorer-on-tuple behaviour verified on SDK 0.24.0+")
    tmp_path = tmp_path_factory.mktemp("tuple_scoring")
    (tmp_path / "probe.py").write_text(PROBE, encoding="utf-8")
    env = _offline_mock_env()
    env.update({"HOME": str(tmp_path), "TRAIGENT_RUN_APPROVED": "1"})
    completed = subprocess.run(
        [sys.executable, "probe.py"], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(r for r in completed.stdout.splitlines() if r.startswith("PROBE_JSON="))
    return json.loads(line.split("=", 1)[1]), completed.stdout + completed.stderr


def test_scoring_function_receives_unpacked_output_and_sets_objective(probe) -> None:
    data, _ = probe
    assert data["scorer"]["received"] == ["str"]
    assert data["scorer"]["accuracy"] == pytest.approx(0.77)
    assert data["scorer"]["side"] == pytest.approx(1.0)


def test_three_arg_metric_function_receives_unpacked_output(probe) -> None:
    data, _ = probe
    assert data["metric_fn"]["received"] == ["str"]
    assert data["metric_fn"]["custom"] == pytest.approx(0.66)


def test_non_reserved_tuple_key_can_be_an_objective(probe) -> None:
    data, _ = probe
    assert data["tuple_key"]["custom_match"] == pytest.approx(0.42)


def test_reserved_tuple_key_is_dropped_with_a_warning(probe) -> None:
    data, logs = probe
    assert data["reserved"]["accuracy"] == pytest.approx(0.0)
    assert "Skipping user metric 'accuracy'" in logs


def test_skill_names_only_real_reserved_keys(probe) -> None:
    data, _ = probe
    for key in ("accuracy", "cost", "latency", "score", "success"):
        assert key in data["reserved_keys"], key


def test_skill_does_not_teach_the_retired_not_invoked_warning() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "NOT invoked" not in text
    assert "is also 0.0" not in text
    assert "known SDK\nissue" not in text and "known SDK issue" not in text
    # The still-true reserved-key rule stays.
    assert "RESERVED_METRIC_KEYS" in text
    assert "Skipping user metric" in text
