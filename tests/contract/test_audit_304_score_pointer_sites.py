"""Trial loops must read objectives by name, not `metrics["score"]`.

In a multi-objective run `score` is the weighted selection basis, not the
primary objective. This pins that relation on the installed SDK and keeps the
optimize/composite skills from presenting `score` as the primary objective.
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
SCORE_READ_RE = re.compile(r"""\.get\(\s*['"]score['"]""")
SITES = [
    ROOT / "skills" / "traigent-optimize-run" / "SKILL.md",
    ROOT / "skills" / "traigent-optimize-run" / "references" / "cost-management.md",
    ROOT / "skills" / "traigent-optimize-composite-knobs" / "SKILL.md",
]

PROBE = r'''
import json
import traigent
import traigent.testing
from pathlib import Path

traigent.testing.enable_mock_mode_for_quickstart()
Path("qa.jsonl").write_text(
    '{"input": {"q": "a"}, "output": "A"}\n'
    '{"input": {"q": "b"}, "output": "B"}\n'
    '{"input": {"q": "c"}, "output": "C"}\n'
)

@traigent.optimize(eval_dataset="qa.jsonl", objectives=["accuracy", "cost"], offline=True,
                   configuration_space={"m": ["x", "y"]})
def answer(q):
    traigent.get_config()
    return q.upper() if q != "c" else "wrong"   # 2 of 3 correct

r = answer.optimize_sync(max_trials=1, algorithm="grid")
t = r.trials[0]
print("PROBE_JSON=" + json.dumps({
    "accuracy": t.metrics["accuracy"],
    "metrics_score": t.metrics["score"],
    "trial_score": t.score,
    "best_score": r.best_score,
}))
'''


def test_no_site_says_score_mirrors_the_primary_objective() -> None:
    for path in SITES:
        text = path.read_text(encoding="utf-8")
        assert "score mirrors the primary objective" not in text, path
        assert "score\n# mirrors the primary objective" not in text, path
        assert not SCORE_READ_RE.search(text), path


def test_multi_objective_score_is_not_the_primary_objective(
    tmp_path: Path, sdk_version_label: str
) -> None:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.27.0"):
        pytest.skip("weighted-score relation verified on SDK 0.27.0+")
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
    assert data["accuracy"] == pytest.approx(2 / 3)
    assert data["best_score"] == pytest.approx(2 / 3)
    assert data["metrics_score"] == pytest.approx(data["trial_score"])
    assert data["metrics_score"] != pytest.approx(data["accuracy"])
