"""Execute the documented gate's input boundaries against the installed SDK."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.version import Version

from .extract import _iter_fenced_blocks


@pytest.fixture()
def scripts(sdk_version_label):
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.24.0"):
        pytest.skip("the documented promotion workflow requires SDK 0.24.0+")
    source = (Path(__file__).resolve().parents[2] / "skills/traigent-ci-safety-gate"
              / "references/gate-workflow.md")
    result = {}
    for block in _iter_fenced_blocks(source.read_text().splitlines()):
        if block.language == "python":
            namespace = {"__name__": "gate_workflow_under_test"}
            exec(compile(block.text, str(source), "exec"), namespace)
            result["gate" if "metric_series" in namespace else "holdout"] = SimpleNamespace(**namespace)
    return SimpleNamespace(**result)


@pytest.mark.parametrize("name", ["accuracy", "latency_ms"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, True, "bad"])
def test_gate_refuses_invalid_measurements(scripts, name, value):
    with pytest.raises(SystemExit, match=name):
        scripts.gate.metric_series({"metrics": {name: [value]}}, name)


@pytest.mark.parametrize("limit", ["--max-cost", "--max-latency-ms"])
@pytest.mark.parametrize("value", ["nan", "inf", "-1"])
def test_invalid_limit_cannot_disable_the_gate(scripts, monkeypatch, tmp_path, limit, value):
    # The files need not exist: invalid limits must stop before reading evidence.
    args = ["gate.py", "--incumbent", str(tmp_path / "inc.json"),
            "--candidate", str(tmp_path / "candidate.json"),
            "--max-cost", "5", "--max-latency-ms", "1200"]
    args[args.index(limit) + 1] = value
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit, match=limit):
        scripts.gate.main()


@pytest.mark.parametrize("cost", [float("nan"), float("inf"), -1.0, True])
def test_holdout_rejects_invalid_call_cost_before_writing_evidence(
    scripts, monkeypatch, tmp_path, cost,
):
    config = tmp_path / "config.json"
    config.write_text("{}")
    holdout = tmp_path / "holdout.jsonl"
    holdout.write_text(json.dumps({"input": "question", "expected_output": "answer"}) + "\n")
    output = tmp_path / "result.json"
    monkeypatch.setitem(scripts.holdout.main.__globals__, "evaluate_one", lambda *a: (1.0, 10.0, cost))
    monkeypatch.setattr(sys, "argv", ["holdout.py", "--config", str(config),
                                    "--holdout", str(holdout), "--output", str(output)])
    with pytest.raises(SystemExit, match="cost"):
        scripts.holdout.main()
    assert not output.exists()
