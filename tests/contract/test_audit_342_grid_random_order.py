"""Grid order and random exhaustion as documented in optimize-run algorithms.md.

On a 2x2 space: the default grid varies `model` fastest (alphabetical order
otherwise), and random search runs each discrete configuration once, then stops
with `stop_reason="optimizer"` before `max_trials`.
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
ALGORITHMS = ROOT / "skills" / "traigent-optimize-run" / "references" / "algorithms.md"

PROBE = r'''
import json
import traigent
import traigent.testing
from pathlib import Path

traigent.testing.enable_mock_mode_for_quickstart()
Path("qa.jsonl").write_text('{"input": {"question": "q"}, "output": "4"}\n')

@traigent.optimize(eval_dataset="qa.jsonl", objectives=["accuracy"], offline=True,
                   configuration_space={"model": ["gpt-4o-mini", "gpt-4o"],
                                        "temperature": [0.1, 0.5]})
def f(question: str) -> str:
    traigent.get_config()
    return "4"

g = f.optimize_sync(max_trials=4, algorithm="grid")
r = f.optimize_sync(max_trials=10, algorithm="random")
print("PROBE_JSON=" + json.dumps({
    "grid": [[t.config["model"], t.config["temperature"]] for t in g.trials],
    "random_trials": len(r.trials),
    "random_unique": len({tuple(sorted(t.config.items())) for t in r.trials}),
    "random_stop": r.stop_reason,
}))
'''


def test_default_grid_order_and_random_exhaustion(
    tmp_path: Path, sdk_version_label: str
) -> None:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.27.0"):
        pytest.skip("grid/random ordering verified on SDK 0.27.0+")
    (tmp_path / "probe.py").write_text(PROBE, encoding="utf-8")
    env = _offline_mock_env()
    env["HOME"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "probe.py"], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(r for r in completed.stdout.splitlines() if r.startswith("PROBE_JSON="))
    data = json.loads(line.split("=", 1)[1])
    # `model` varies fastest; `temperature` is the outer loop.
    assert data["grid"] == [
        ["gpt-4o-mini", 0.1],
        ["gpt-4o", 0.1],
        ["gpt-4o-mini", 0.5],
        ["gpt-4o", 0.5],
    ]
    assert data["random_trials"] == 4
    assert data["random_unique"] == 4
    assert data["random_stop"] == "optimizer"


def test_algorithms_reference_matches_the_sdk() -> None:
    text = ALGORITHMS.read_text(encoding="utf-8")
    assert "lexicographic" not in text
    assert "with replacement" not in text
    assert "`model`, which is placed last and varies" in text
    assert "without repeating a configuration" in text
    # Unchanged neighbours.
    assert 'Stops with `stop_reason="optimizer"` when all combinations are exhausted' in text
    assert "parameter_order={" in text
