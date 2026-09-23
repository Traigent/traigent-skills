"""The `score-relocation` version-matrix row must match what the SDK records (#304).

`trial.score` / `metrics["score"]` equal the primary objective only for a single
built-in objective. A weighted multi-objective run stores its selection basis there,
and a custom `metric_functions` objective leaves the builtin exact-match value in
`metrics["score"]`. Each case below names the phrase the row must carry and the
relation a real offline run on the installed SDK must show.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from .test_runnable_snippets import _offline_mock_env
from .test_version_matrix import _parse_matrix, repo_root

FACT_ID = "score-relocation"

# 2 of 3 outputs exact-match their label, so the builtin exact-match value is 2/3.
EXACT_MATCH = 2 / 3

RUNNER = """
import json, socket

def deny_connect(*args, **kwargs):
    raise AssertionError("unexpected network attempt")

socket.socket.connect = deny_connect
socket.socket.connect_ex = deny_connect

import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.core.objectives import create_default_objectives

with open("qa.jsonl", "w") as fh:
    for q, a in [("a", "A"), ("b", "B"), ("c", "C")]:
        fh.write(json.dumps({"input": {"q": q}, "output": a}) + "\\n")

import litellm

def answer(q):
    traigent.get_config()
    text = q.upper() if q != "c" else "wrong"
    # A cost objective needs measured usage: SDKs after 0.27.0 refuse an
    # all-$0 cost column. litellm's mock_response returns a real response with
    # token usage and makes no network call, so cost is measured, not faked.
    litellm.completion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": q}],
        mock_response=text,
    )
    return text

def exec_acc(output, expected, input_data=None):
    return 1.0

def always_one(output, expected, input_data=None):
    return 1.0

cases = {
    "single_builtin": dict(objectives=["accuracy"], eval_dataset="qa.jsonl"),
    "multi_objective": dict(objectives=["accuracy", "cost"], eval_dataset="qa.jsonl"),
    "custom_metric_function": dict(
        # Custom metric names need an explicit direction on SDKs after 0.27.0.
        objectives=create_default_objectives(
            ["exec_acc"], orientations={"exec_acc": "maximize"}
        ),
        evaluation=EvaluationOptions(
            eval_dataset="qa.jsonl", metric_functions={"exec_acc": exec_acc}
        ),
    ),
    "custom_scoring_function": dict(
        objectives=["accuracy"],
        evaluation=EvaluationOptions(eval_dataset="qa.jsonl", scoring_function=always_one),
    ),
}
out = {}
for label, kwargs in cases.items():
    fn = traigent.optimize(
        configuration_space={"m": ["x", "y"]},
        algorithm="grid",
        offline=True,
        max_trials=1,
        **kwargs,
    )(answer)
    result = fn.optimize_sync()
    trial = result.trials[0]
    out[label] = {
        "metrics": {
            k: v for k, v in trial.metrics.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        },
        "trial_score": trial.score,
        "best_score": result.best_score,
    }
print("RESULT " + json.dumps(out))
"""


def _close(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) < 1e-9


def _single_builtin(r: dict) -> list[str]:
    m = r["metrics"]
    problems = []
    if not _close(m.get("score"), m.get("accuracy")):
        problems.append(
            f"metrics['score'] {m.get('score')} != accuracy {m.get('accuracy')}"
        )
    if not _close(r["trial_score"], m.get("accuracy")):
        problems.append(
            f"trial.score {r['trial_score']} != accuracy {m.get('accuracy')}"
        )
    return problems


def _multi_objective(r: dict) -> list[str]:
    m = r["metrics"]
    problems = []
    if not _close(r["trial_score"], m.get("score")):
        problems.append(
            f"trial.score {r['trial_score']} != metrics['score'] {m.get('score')}"
        )
    if _close(m.get("score"), m.get("accuracy")):
        problems.append(
            "metrics['score'] equals accuracy; the weighted basis is expected"
        )
    if not _close(r["best_score"], m.get("accuracy")):
        problems.append(f"best_score {r['best_score']} != accuracy {m.get('accuracy')}")
    return problems


def _custom_metric_function(r: dict) -> list[str]:
    m = r["metrics"]
    problems = []
    if not _close(r["trial_score"], m.get("exec_acc")):
        problems.append(
            f"trial.score {r['trial_score']} != exec_acc {m.get('exec_acc')}"
        )
    if not _close(m.get("score"), EXACT_MATCH):
        problems.append(
            f"metrics['score'] {m.get('score')} != exact-match {EXACT_MATCH}"
        )
    return problems


def _custom_scoring_function(r: dict) -> list[str]:
    m = r["metrics"]
    problems = []
    if not _close(m.get("exact_match_default"), EXACT_MATCH):
        problems.append(
            f"metrics['exact_match_default'] {m.get('exact_match_default')} != {EXACT_MATCH}"
        )
    if not _close(m.get("score"), m.get("accuracy")):
        problems.append(
            f"metrics['score'] {m.get('score')} != accuracy {m.get('accuracy')}"
        )
    return problems


# case -> (phrase the row's delta must contain, relation the SDK must show)
CASES = {
    "single_builtin": ("Single built-in objective", _single_builtin),
    "multi_objective": (
        "Multi-objective (weighted) runs: both carry the weighted, run-range-normalised "
        "selection basis",
        _multi_objective,
    ),
    "custom_metric_function": (
        "Custom `metric_functions` primary objective: `trial.score` is the objective, "
        '`metrics["score"]` is the builtin exact-match value',
        _custom_metric_function,
    ),
    "custom_scoring_function": (
        '`metrics["exact_match_default"]`',
        _custom_scoring_function,
    ),
}


def _row():
    rows = {row.fact_id: row for row in _parse_matrix(repo_root())}
    assert FACT_ID in rows, f"docs/version-matrix.md has no {FACT_ID!r} row"
    return rows[FACT_ID]


def test_row_tells_readers_to_read_objectives_by_name() -> None:
    row = _row()
    assert "single built-in" in row.canonical_phrasing, (
        f"{FACT_ID} canonical_phrasing must qualify the claim to a single built-in "
        f"objective: {row.canonical_phrasing!r}"
    )
    for text in (row.delta, row.canonical_phrasing):
        assert "objectives by name" in text, (
            f"{FACT_ID} must tell readers to read objectives by name: {text!r}"
        )


@pytest.fixture(scope="module")
def sdk_results(sync_map: dict, sdk_version_label: str, tmp_path_factory) -> dict:
    current = str(sync_map["current_released_sdk_version"])
    if sdk_version_label not in (current, "develop"):
        pytest.skip(
            f"score relation is pinned to SDK {current}; installed {sdk_version_label}"
        )
    workdir = tmp_path_factory.mktemp("score_relocation")
    (workdir / "runner.py").write_text(RUNNER, encoding="utf-8")
    env = _offline_mock_env()
    # A fresh HOME keeps the SDK's local session store out of the run (and fast).
    env["HOME"] = str(workdir / "home")
    completed = subprocess.run(
        [sys.executable, "runner.py"],
        cwd=workdir,
        env=env,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    lines = [
        line for line in completed.stdout.splitlines() if line.startswith("RESULT ")
    ]
    assert len(lines) == 1, completed.stdout + completed.stderr
    return json.loads(lines[0][len("RESULT ") :])


@pytest.mark.parametrize("case", sorted(CASES))
def test_row_documents_the_score_relation_the_sdk_records(
    case: str, sdk_results: dict
) -> None:
    phrase, relation = CASES[case]
    assert phrase in _row().delta, (
        f"docs/version-matrix.md {FACT_ID} does not document the {case} case "
        f"(expected {phrase!r})"
    )
    problems = relation(sdk_results[case])
    assert not problems, f"{case}: SDK no longer matches the row: " + "; ".join(
        problems
    )


def test_relations_have_teeth() -> None:
    """Each relation must reject the other shapes' results."""
    single = {
        "metrics": {"accuracy": 0.6, "score": 0.6},
        "trial_score": 0.6,
        "best_score": 0.6,
    }
    weighted = {
        "metrics": {"accuracy": 0.6, "score": 0.5},
        "trial_score": 0.5,
        "best_score": 0.6,
    }
    assert not _single_builtin(single) and _single_builtin(weighted)
    assert not _multi_objective(weighted) and _multi_objective(single)
    custom_ok = {"metrics": {"exec_acc": 1.0, "score": EXACT_MATCH}, "trial_score": 1.0}
    custom_bad = {"metrics": {"exec_acc": 1.0, "score": 1.0}, "trial_score": 1.0}
    assert not _custom_metric_function(custom_ok) and _custom_metric_function(
        custom_bad
    )
    assert _custom_scoring_function({"metrics": {"accuracy": 1.0, "score": 1.0}})
