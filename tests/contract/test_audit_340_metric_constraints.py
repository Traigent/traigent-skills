"""Metric-aware constraints are post-trial checks on the current trial.

Every `metrics.get("<key>"` taught in the config-space constraint docs must be a
key a two-argument constraint actually receives on the installed SDK, so no
documented cap silently passes on a missing key.
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
DOCS = [
    ROOT / "skills" / "traigent-optimize-config-space" / "SKILL.md",
    ROOT / "skills" / "traigent-optimize-config-space" / "references" / "constraints.md",
]
KEY_RE = re.compile(r"""metrics\.get\(\s*["']([^"']+)["']""")

PROBE = r'''
import json
import time
import traigent
import traigent.testing
from pathlib import Path

traigent.testing.enable_mock_mode_for_quickstart()
Path("qa.jsonl").write_text(
    '{"input": {"question": "What is 2+2?"}, "output": "4"}\n'
    '{"input": {"question": "Capital of France?"}, "output": "Paris"}\n'
    '{"input": {"question": "Color of the sky?"}, "output": "blue"}\n'
)
calls = []
examples_run = []

def guard(config, metrics):
    calls.append({"keys": sorted(metrics), "examples_before": len(examples_run)})
    return metrics.get("response_time_ms", float("inf")) <= 5   # 5 ms cap vs ~50 ms

@traigent.optimize(eval_dataset="qa.jsonl", objectives=["accuracy"], offline=True,
                   configuration_space={"model": ["a", "b", "c"]}, constraints=[guard])
def f(question: str) -> str:
    traigent.get_config()
    examples_run.append(question)
    time.sleep(0.05)
    return "4"

r = f.optimize_sync(max_trials=3, algorithm="grid")
print("PROBE_JSON=" + json.dumps({
    "calls": calls,
    "completed": len(r.successful_trials),
    "failed": len(r.failed_trials),
}))
'''


@pytest.fixture(scope="module")
def probe(tmp_path_factory: pytest.TempPathFactory, pytestconfig: pytest.Config) -> dict:
    from .conftest import _sdk_version_label

    label = _sdk_version_label(pytestconfig)
    if label != "develop" and Version(label) < Version("0.27.0"):
        pytest.skip("post-trial constraint behaviour verified on SDK 0.27.0+")
    tmp_path = tmp_path_factory.mktemp("metric_constraints")
    (tmp_path / "probe.py").write_text(PROBE, encoding="utf-8")
    env = _offline_mock_env()
    env["HOME"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "probe.py"], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(r for r in completed.stdout.splitlines() if r.startswith("PROBE_JSON="))
    return json.loads(line.split("=", 1)[1])


def test_documented_metric_keys_reach_post_trial_constraints(probe: dict) -> None:
    received = set(probe["calls"][0]["keys"])
    documented = set()
    for path in DOCS:
        documented |= set(KEY_RE.findall(path.read_text(encoding="utf-8")))
    assert documented, "no metric-aware constraint example found"
    missing = sorted(documented - received)
    assert not missing, f"documented keys never reach a metrics constraint: {missing}"


def test_metric_constraint_runs_after_each_trial_and_fails_it(probe: dict) -> None:
    # Called once per trial, after that trial's examples ran (3 examples each).
    assert [call["examples_before"] for call in probe["calls"]] == [3, 6, 9]
    assert probe["completed"] == 0
    assert probe["failed"] == 3


def test_docs_describe_a_post_trial_fail_closed_check() -> None:
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        assert "past trials" not in text and "previous trials" not in text, path
        assert "post-trial" in text, path
        for line in text.splitlines():
            if "lambda config, metrics:" in line:
                assert 'float("inf")' in line, (path, line)
