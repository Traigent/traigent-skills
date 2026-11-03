"""Shared subprocess probe for the mock dry-run contract tests (#463-#465).

Runs a tiny ``@traigent.optimize`` agent under ``enable_mock_mode_for_quickstart()``
in a clean allowlisted environment with no provider keys, so a test can observe how
the installed SDK prices, gates, and fails a mock run. Not a test module.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .test_runnable_snippets import _offline_mock_env

PROBE = r'''
import json, os
import litellm
import traigent
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()
rows = int(os.environ["PROBE_ROWS"])
scorer_kind = os.environ["PROBE_SCORER"]
with open("rows.jsonl", "w", encoding="utf-8") as fh:
    for i in range(rows):
        fh.write(json.dumps({"input": {"q": "word " * 5000 + str(i)}, "output": json.dumps({"a": i})}) + "\n")


def number_scorer(output, expected, **_):
    return 1.0 if str(output) == str(expected) else 0.0


def parsing_scorer(output, expected, **_):
    return 1.0 if json.loads(output) == json.loads(expected) else 0.0


@traigent.optimize(
    eval_dataset="rows.jsonl", objectives=["accuracy"], offline=True,
    injection_mode="context",
    configuration_space={"model": ["gpt-4o", "gpt-4o-mini"]},
    scoring_function=parsing_scorer if scorer_kind == "parse" else number_scorer,
)
def agent(q: str) -> str:
    cfg = traigent.get_config()
    return litellm.completion(
        model=cfg["model"], messages=[{"role": "user", "content": q}]
    ).choices[0].message.content


try:
    result = agent.optimize_sync(max_trials=2, algorithm="grid")
except Exception as exc:  # report the class, never swallow it into a score
    print("PROBE_JSON=" + json.dumps({"error": type(exc).__name__}))
else:
    print("PROBE_JSON=" + json.dumps({
        "error": None,
        "trials": len(result.trials),
        "failed": len(result.failed_trials),
        "best_score": result.best_score,
    }))
'''


def run_probe(tmp_path: Path, *, rows: int, scorer: str, extra_env: dict[str, str | None]) -> dict:
    """Run the probe and return its JSON line; the process itself must exit 0."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "probe.py").write_text(PROBE, encoding="utf-8")
    env = _offline_mock_env()  # ENVIRONMENT=test, offline, no provider keys
    env.update({"HOME": str(tmp_path), "PROBE_ROWS": str(rows), "PROBE_SCORER": scorer})
    for name, value in extra_env.items():
        if value is None:
            env.pop(name, None)  # None means: remove it from the environment
        else:
            env[name] = value
    completed = subprocess.run(
        [sys.executable, "probe.py"], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=240, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(r for r in completed.stdout.splitlines() if r.startswith("PROBE_JSON="))
    return json.loads(line.split("=", 1)[1])
