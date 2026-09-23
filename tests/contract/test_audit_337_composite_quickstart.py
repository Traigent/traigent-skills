"""The composite-knobs Quick Start must be a working template, not a flat search.

Runs the SKILL.md Quick Start block verbatim in a fresh offline process on the
installed SDK, then grid-searches it: the gate threshold must change the score,
and every declared tuned variable must change the result for some value.
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
SKILL = ROOT / "skills" / "traigent-optimize-composite-knobs" / "SKILL.md"

DRIVER = """
import json
import quickstart

r = quickstart.answer.optimize_sync(max_trials=6, algorithm="grid")
rows = [
    {
        "config": dict(t.config),
        "metrics": {
            k: v
            for k, v in t.metrics.items()
            if k == "accuracy" or k.startswith("composite_")
        },
    }
    for t in r.trials
]
print("TRIALS_JSON=" + json.dumps(rows, sort_keys=True))
"""


def _quickstart_block() -> str:
    text = SKILL.read_text(encoding="utf-8")
    quick_start = text.split("## Quick Start", 1)[1]
    blocks = [
        block.text
        for block in _iter_fenced_blocks(quick_start.splitlines())
        if block.language == "python" and "execute_composite(" in block.text
    ]
    assert blocks, "Quick Start has no execute_composite block"
    return blocks[0]


@pytest.fixture()
def trials(tmp_path: Path, sdk_version_label: str) -> list[dict]:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.27.0"):
        pytest.skip("Quick Start behaviour verified on SDK 0.27.0+")
    (tmp_path / "quickstart.py").write_text(_quickstart_block(), encoding="utf-8")
    (tmp_path / "driver.py").write_text(DRIVER, encoding="utf-8")
    env = _offline_mock_env()
    env["HOME"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "driver.py"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(
        row for row in completed.stdout.splitlines() if row.startswith("TRIALS_JSON=")
    )
    return json.loads(line.split("=", 1)[1])


def test_quick_start_threshold_changes_the_score(trials: list[dict]) -> None:
    accuracies = {row["metrics"]["accuracy"] for row in trials}
    assert len(accuracies) > 1, trials


def test_every_quick_start_tuned_variable_is_a_lever(trials: list[dict]) -> None:
    keys = set().union(*(row["config"] for row in trials))
    assert keys, trials
    for key in sorted(keys):
        # Group trials that agree on every OTHER key; within some group, changing
        # `key` must change the scored result or the composite measures.
        groups: dict[str, set[str]] = {}
        for row in trials:
            others = json.dumps(
                {k: v for k, v in row["config"].items() if k != key}, sort_keys=True
            )
            groups.setdefault(others, set()).add(
                json.dumps(row["metrics"], sort_keys=True)
            )
        assert any(len(signatures) > 1 for signatures in groups.values()), (
            f"tuned variable {key!r} never changes the result: {trials}"
        )


def test_quick_start_states_the_multi_sample_requirement() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "must return more than one sample" in text
