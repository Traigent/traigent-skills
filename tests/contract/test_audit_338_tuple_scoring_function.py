"""A custom scorer IS invoked on the (output, metrics) tuple-return path.

Traigent/traigent-skills#338 (the boost-agent instrument-recipe part). The recipe
warned that a ``scoring_function`` / 3-arg ``metric_functions`` is "NOT invoked
with the unpacked prediction" on this path and that ``score`` "is ALSO 0.0". On
every supported SDK the scorer receives the unpacked ``str`` and its value is the
objective. The runtime check pins that; the text check keeps the false warning out.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "skills" / "traigent-boost-agent" / "references" / "instrument-recipe.md"


def test_recipe_does_not_claim_the_scorer_is_skipped() -> None:
    text = " ".join(RECIPE.read_text(encoding="utf-8").split())
    for claim in ("NOT invoked", "known SDK issue", "is ALSO 0.0"):
        assert claim not in text, f"instrument-recipe.md still says {claim!r}"


def test_scoring_function_receives_unpacked_output_on_tuple_return(tmp_path: Path) -> None:
    pytest.importorskip("traigent")
    (tmp_path / "home").mkdir()
    script = tmp_path / "probe.py"
    script.write_text(
        textwrap.dedent(
            """
            import json
            from pathlib import Path
            import traigent
            from traigent.testing import enable_mock_mode_for_quickstart

            enable_mock_mode_for_quickstart()
            Path("qa.jsonl").write_text(
                '{"input": {"question": "What is 2+2?"}, "output": "4"}\\n'
                '{"input": {"question": "Capital of France?"}, "output": "Paris"}\\n'
                '{"input": {"question": "Color of the sky?"}, "output": "blue"}\\n'
            )
            received = []

            def scorer(output, expected, **kwargs):
                received.append(type(output).__name__)
                return 0.11 if isinstance(output, tuple) else (0.77 if output == "4" else 0.05)

            @traigent.optimize(eval_dataset="qa.jsonl", objectives=["accuracy"], offline=True,
                               scoring_function=scorer, configuration_space={"model": ["m"]})
            def answer(question: str):
                traigent.get_config()
                return "4", {"side_metric": 1.0}

            metrics = answer.optimize_sync(max_trials=1, algorithm="grid").trials[0].metrics
            print("RESULT=" + json.dumps({"accuracy": metrics["accuracy"],
                                          "side_metric": metrics.get("side_metric"),
                                          "received": received}))
            """
        ),
        encoding="utf-8",
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.endswith("_API_KEY") and k not in {"TRAIGENT_MOCK_LLM", "CI", "GITHUB_ACTIONS"}
    }
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "ENVIRONMENT": "test",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "TRAIGENT_OFFLINE_MODE": "true",
        }
    )
    completed = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(ln for ln in completed.stdout.splitlines() if ln.startswith("RESULT="))
    result = json.loads(line.removeprefix("RESULT="))
    assert result["received"] and set(result["received"]) == {"str"}, result
    # 0.77 is a value only this scorer produces: the objective is the scorer's.
    assert result["accuracy"] == pytest.approx(0.77), result
    assert result["side_metric"] == pytest.approx(1.0), result
