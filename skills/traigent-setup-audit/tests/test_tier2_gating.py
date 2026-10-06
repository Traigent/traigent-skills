"""No approval, no call. One approval, exactly one endpoint.

Every assertion here is made against a real listener's own log, never against
the script's prose about itself. The first test would pass vacuously against a
fake backend whose log stayed empty for its own reasons, so the second one proves
that same log fills up the moment a request IS made.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
from pathlib import Path

import pytest
from conftest import FIXTURES, _tier1_report, recorded_argv, run_tier2
from tier2_fake_backend import LOCAL_SESSION_ID, RUN_ID, FakeBackend


def receipt_rows(path: Path) -> list[tuple[str, str, int | None]]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    return [(row["method"], row["path"], row.get("status"))
            for row in receipt["requests"]]


def log_rows(backend: FakeBackend) -> list[tuple[str, str, int | None]]:
    return [(row["method"], row["path"], row["status"]) for row in backend.log]


def test_offer_mode_makes_no_request_and_spawns_no_process(
    healthy_tier1: Path, sentinel_key: str, fake_traigent_cli: Path
) -> None:
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--cost-limit", "5",
            "--list-runs",
        )
        assert completed.returncode == 0, completed.stderr
        assert backend.log == [], backend.log
    assert recorded_argv(fake_traigent_cli) == []
    # The claim is split because the evidence is: the guard measures the socket
    # half, and the process half holds by construction (nothing that shells out
    # is reachable without --approve) — the guard does not cover subprocesses.
    assert "the network guard is installed and reports `active`" in completed.stdout
    assert "that half is by construction, not by the guard" in completed.stdout


def test_the_empty_log_is_not_vacuous(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """Teeth for the test above: the same listener records a real request."""
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
        )
        assert completed.returncode == 0, completed.stderr
        assert log_rows(backend) == [
            ("GET", f"/api/v1/analytics/runs/{RUN_ID}/evaluator-quality", 200)
        ]


def test_one_approval_touches_only_its_endpoint_and_the_receipt_matches(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path
) -> None:
    receipt = tmp_path / "receipt.json"
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
            "--receipt", str(receipt),
        )
        assert completed.returncode == 0, completed.stderr
        assert receipt_rows(receipt) == log_rows(backend)


def test_two_approvals_touch_exactly_their_two_endpoints(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path
) -> None:
    receipt = tmp_path / "receipt.json"
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
            "--approve", "decision-brief",
            "--receipt", str(receipt),
        )
        assert completed.returncode == 0, completed.stderr
        assert log_rows(backend) == [
            ("GET", f"/api/v1/analytics/runs/{RUN_ID}/evaluator-quality", 200),
            ("GET", f"/api/v1/analytics/runs/{RUN_ID}/decision-payload", 200),
        ]
        assert receipt_rows(receipt) == log_rows(backend)


def test_an_approval_id_outside_the_catalogue_exits_2_with_no_request(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality-please",
        )
        assert completed.returncode == 2
        assert backend.log == []
        assert "no such check" in completed.stderr


def test_example_scoring_reads_and_stops_when_nothing_is_computed(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path
) -> None:
    """`computed: false` ends the check. It is not permission to start a job."""
    receipt = tmp_path / "receipt.json"
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "example-scoring",
            "--receipt", str(receipt),
        )
        assert completed.returncode == 0, completed.stderr
        base = f"/api/v1/analytics/example-scoring/{RUN_ID}"
        assert log_rows(backend) == [("GET", f"{base}/summary", 200)]
        assert backend.compute_calls == 0
        assert receipt_rows(receipt) == log_rows(backend)
    assert "has not computed results for this run" in completed.stdout


def test_example_scoring_never_posts_to_compute(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """The compute endpoint is wired and returns 500; nothing may reach it.

    Observed 2026-09-13 on the customer dogfood run: POST .../compute -> HTTP
    500. Until there is a successful runtime witness and a charging boundary,
    this skill does not trigger scoring at all.
    """
    with FakeBackend(computed=True) as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "example-scoring",
        )
        assert completed.returncode == 0, completed.stderr
        assert backend.compute_calls == 0
        assert not any(method == "POST" for method, _, _ in log_rows(backend))


def test_example_scoring_reads_dataset_quality_only_when_results_exist(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """Teeth for the test above: the second read happens on `computed: true`."""
    with FakeBackend(computed=True) as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "example-scoring",
        )
        assert completed.returncode == 0, completed.stderr
        base = f"/api/v1/analytics/example-scoring/{RUN_ID}"
        assert log_rows(backend) == [
            ("GET", f"{base}/summary", 200),
            ("GET", f"{base}/dataset-quality", 200),
        ]
    assert "has not computed results" not in completed.stdout


def test_a_local_session_id_is_reported_as_a_404_not_as_a_finding(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """A `tv0_` id is not a portal run id; every reader 404s on it."""
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", LOCAL_SESSION_ID,
            "--approve", "evaluator-quality",
            "--approve", "example-insights",
            "--approve", "example-scoring",
            "--approve", "decision-brief",
        )
        assert completed.returncode == 0, completed.stderr
        assert [status for _, _, status in log_rows(backend)] == [404, 404, 404, 404]
    assert completed.stdout.count("HTTP 404") == 4
    assert "abstain" not in completed.stdout
    assert "verbatim" not in completed.stdout


def test_a_run_dependent_check_without_a_run_id_exits_2(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--approve", "example-insights",
        )
        assert completed.returncode == 2
        assert backend.log == []
        assert "needs a completed run" in completed.stderr


def test_bounded_run_is_never_executed_here(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--approve", "bounded-run",
        )
        assert completed.returncode == 2
        assert backend.log == []
        assert "never executed by this skill" in completed.stderr


def test_the_offer_marks_exactly_one_recommendation(healthy_tier1: Path) -> None:
    completed = run_tier2("--from-audit", str(healthy_tier1))
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count("(recommended)") == 1


def test_the_recommendation_follows_tier_1s_ladder(
    weak_tier1: Path
) -> None:
    """An unrepeatable scorer is settled before a dataset is grown."""
    completed = run_tier2("--from-audit", str(weak_tier1), "--run-id", RUN_ID)
    assert completed.returncode == 0, completed.stderr
    assert "APPROVAL CARD — evaluator-quality   (recommended)" in completed.stdout


def _card(stdout: str, check_id: str) -> str:
    after = stdout.split(f"APPROVAL CARD — {check_id}", 1)[1]
    return after.split("APPROVAL CARD", 1)[0]


def test_an_unrepeatable_scorer_is_never_called_repeatable(weak_tier1: Path) -> None:
    """The card quotes Tier 1's result: the weak scorer failed the probe."""
    completed = run_tier2("--from-audit", str(weak_tier1), "--run-id", RUN_ID)
    assert completed.returncode == 0, completed.stderr
    card = _card(completed.stdout, "evaluator-quality")
    assert "found it repeatable" not in card
    assert "NOT reliable" in card
    assert re.search(r"returned \d+ different scores for the same pair", card), card


def test_a_stable_but_misranking_scorer_is_told_to_fix_what_it_measures(
    tmp_path: Path,
) -> None:
    """A constant scorer is perfectly repeatable and ranks nothing: the card
    must say that, not tell the user to make it repeatable."""
    project = tmp_path / "constant"
    shutil.copytree(FIXTURES / "healthy", project)
    (project / "scorer.py").write_text(
        "def score(output, expected):\n    return 0.5\n", encoding="utf-8"
    )
    report = _tier1_report(project, tmp_path / "tier1")
    completed = run_tier2("--from-audit", str(report), "--run-id", RUN_ID)
    assert completed.returncode == 0, completed.stderr
    card = _card(completed.stdout, "evaluator-quality")
    assert "did not rank a known-good answer above a known-bad one" in card
    assert "Make it repeatable" not in card
    assert "found it repeatable" not in card
    assert "fix what it measures" in card


def test_a_repeatable_scorer_is_still_called_repeatable(healthy_tier1: Path) -> None:
    completed = run_tier2("--from-audit", str(healthy_tier1), "--run-id", RUN_ID)
    assert completed.returncode == 0, completed.stderr
    card = _card(completed.stdout, "evaluator-quality")
    assert "found it repeatable" in card
    assert "NOT reliable" not in card


def test_list_runs_is_only_offered_when_asked_for(healthy_tier1: Path) -> None:
    without = run_tier2("--from-audit", str(healthy_tier1))
    assert "APPROVAL CARD — list-runs" not in without.stdout
    assert "pass --list-runs" in without.stdout
    with_flag = run_tier2("--from-audit", str(healthy_tier1), "--list-runs")
    assert "APPROVAL CARD — list-runs" in with_flag.stdout


def test_list_runs_reports_completed_runs_newest_first(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--list-runs",
            "--approve", "list-runs",
        )
        assert completed.returncode == 0, completed.stderr
        assert [(method, path) for method, path, _ in log_rows(backend)] == [
            ("GET", "/api/v1/experiments?limit=10"),
            ("GET", "/api/v1/experiment-runs/"
                    "cbb7bf81-06cb-4677-aa82-19bf8627afab/runs"),
        ]
    # The verbatim body is relayed in full, running rows included; the summary
    # the user acts on offers only the runs a check can actually read, with the
    # context needed to pick the intended one and no auto-selection.
    summary = completed.stdout.split("completed portal runs, newest first:", 1)[1]
    assert f"portal run id : {RUN_ID}" in summary
    assert "project id    : project_personal_66c1223ef6a64ce8a7cce5fbeb777479" in summary
    assert "experiment id : cbb7bf81-06cb-4677-aa82-19bf8627afab" in summary
    assert "experiment    : ruler-dev-001" in summary
    assert "status        : completed" in summary
    assert "completed_at  : 2026-09-13T09:12:00Z" in summary
    assert "configuration runs: 8" in summary
    assert "00000000-0000-4000-8000-000000000002" not in summary
    assert "asked for at most 10 experiment(s) and got 1." in summary
    assert "pass the one you want as --run-id" in summary
    assert "`tv0_` id" in summary


def test_a_missing_key_stops_a_backend_check_before_any_request(
    healthy_tier1: Path, monkeypatch
) -> None:
    monkeypatch.delenv("TRAIGENT_API_KEY", raising=False)
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
        )
        assert completed.returncode == 2
        assert backend.log == []
        assert "TRAIGENT_API_KEY is not set" in completed.stderr


def test_stop_here_can_be_the_recommendation(weak_tier1: Path) -> None:
    """With no run to read and a local fix still open, the honest move is to stop.

    Recommending a reader here would be recommending a paid run whose only
    purpose is to make an analysis service answer — and it may still abstain.
    """
    completed = run_tier2("--from-audit", str(weak_tier1))
    assert completed.returncode == 0, completed.stderr
    assert "APPROVAL CARD — stop-here   (recommended)" in completed.stdout
    assert completed.stdout.count("(recommended)") == 1


def test_stop_here_is_not_always_the_recommendation(healthy_tier1: Path) -> None:
    """Teeth: a project with nothing left to fix locally is offered the plan."""
    completed = run_tier2("--from-audit", str(healthy_tier1))
    assert "APPROVAL CARD — plan   (recommended)" in completed.stdout


def test_a_project_with_no_dataset_is_never_told_one_exists(tmp_path: Path) -> None:
    """The bounded-run card quotes what Tier 1 found, and with no dataset the
    plan is not recommended: there is nothing to size a first run from."""
    project = tmp_path / "nodata"
    project.mkdir()
    (project / "agent.py").write_text(
        "import traigent\n\n"
        "@traigent.optimize(configuration_space={'model': ['gpt-4o-mini', 'gpt-4o'],"
        " 'temperature': [0.0, 0.7]})\n"
        "def answer(question, model='gpt-4o-mini', temperature=0.0):\n"
        "    return f'{model}:{temperature}:{question}'\n",
        encoding="utf-8",
    )
    (project / "scorer.py").write_text(
        "def score(output, expected):\n"
        "    return 1.0 if output.strip() == expected.strip() else 0.0\n",
        encoding="utf-8",
    )
    report = _tier1_report(project, tmp_path / "tier1")
    completed = run_tier2("--from-audit", str(report))
    assert completed.returncode == 0, completed.stderr
    out = completed.stdout
    assert "a dataset and scorer exist" not in out
    assert "APPROVAL CARD — plan   (recommended)" not in out
    assert "no evaluation dataset" in _card(out, "bounded-run")


def test_stop_here_cannot_be_approved(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--approve", "stop-here",
        )
        assert completed.returncode == 2
        assert backend.log == []
    assert "nothing to approve" in completed.stderr


def test_every_card_discloses_where_the_api_key_travels(
    healthy_tier1: Path
) -> None:
    completed = run_tier2("--from-audit", str(healthy_tier1), "--list-runs")
    cards = completed.stdout.count("APPROVAL CARD")
    assert cards >= 8
    assert completed.stdout.count("Your API key        :") == cards


def test_a_backend_url_carrying_the_api_prefix_is_refused(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """Observed 2026-09-13: the origin plus /api/v1 doubles the path and 404s."""
    completed = run_tier2(
        "--from-audit", str(healthy_tier1),
        "--backend-url", "https://portal.traigent.ai/api/v1",
        "--run-id", RUN_ID,
        "--approve", "evaluator-quality",
    )
    assert completed.returncode == 2
    assert "pass the ORIGIN with no path" in completed.stderr


def test_no_card_promises_a_finding_it_cannot_produce(healthy_tier1: Path) -> None:
    """An offer says what it RETRIEVES; the promise words belong to nothing here."""
    completed = run_tier2("--from-audit", str(healthy_tier1), "--list-runs")
    out = completed.stdout
    assert "says WHICH of those rows to fix" not in out
    assert "settles" not in out
    # Every card carries the caveat line that keeps the offer honest.
    assert out.count("Caveat              :") == out.count("APPROVAL CARD")


# A report written by an older audit can carry branch `g` over a probe the
# current rule does not call ready. Each mutation keeps the stored branch.
STALE_PROBES = (
    "errors",
    "infinity",
    "dropped_errors",
    "legacy_dropped_key",
    "huge_int",
    "blocked",
    "string_scores",
    "string_errors",
)


def _make_stale(probe: dict, how: str) -> None:
    if how == "legacy_dropped_key":
        # An older parent dropped an error record it could not name and kept
        # only the count, so the scores alone look complete.
        probe.clear()
        probe.update(
            {
                "ran": True,
                "scores": {"good": [1.0], "partial": [0.5], "bad": [0.0]},
                "dropped_keys": 1,
            }
        )
    elif how == "huge_int":
        # Valid JSON, finite, and too large for a float.
        probe["scores"]["good"] = [10**400] * len(probe["scores"]["good"])
    elif how == "blocked":
        # No symptom text to quote.
        probe.clear()
        probe.update({"ran": False, "network_blocked": True})
    elif how == "string_scores":
        # Malformed stored data the parent would never have written.
        probe["scores"]["good"] = ["1.0"]
    elif how == "string_errors":
        probe["errors"] = ["RuntimeError"]
    elif how == "errors":
        probe["errors"] = [
            {"case": "partial", "error_type": "RuntimeError", "error_site": "scorer.py:6"}
        ]
    elif how == "infinity":
        # Written with json.dumps' default, so it lands as a legacy `Infinity`.
        probe["scores"]["good"] = [float("inf")] * len(probe["scores"]["good"])
    else:
        probe["scores"]["partial"] = []
        probe.pop("errors", None)


@pytest.mark.parametrize("run_id", [None, RUN_ID], ids=["no-run-id", "run-id"])
@pytest.mark.parametrize("how", STALE_PROBES)
def test_a_stale_all_clear_recommends_rerunning_the_audit(
    how: str, run_id: str | None, healthy_tier1: Path, tmp_path: Path
) -> None:
    report = json.loads(healthy_tier1.read_text(encoding="utf-8"))
    assert report["next_step"]["branch"] == "g"
    _make_stale(report["scorer_probe"], how)
    # Paths a shell would split, so the quoted command is the one to paste.
    report["root"] = str(tmp_path / "my project")
    stale = tmp_path / "stale report.json"
    stale.write_text(json.dumps(report), encoding="utf-8")
    completed = run_tier2(
        "--from-audit", str(stale), *(("--run-id", run_id) if run_id else ())
    )
    assert completed.returncode == 0, completed.stderr
    assert "Traceback" not in completed.stderr
    out = completed.stdout
    assert out.count("(recommended)") == 1
    assert "APPROVAL CARD — stop-here   (recommended)" in out
    assert "APPROVAL CARD — plan   (recommended)" not in out
    card = _card(out, "stop-here")
    assert "all-clear" in card
    assert "written by an older audit or edited" in card
    assert "with the same options you used before (for example --scorer" in card
    command = (
        f"audit_project.py --root {shlex.quote(report['root'])} "
        f"--json {shlex.quote(str(stale))}"
    )
    assert command in card
    if how == "blocked":
        assert "does not support it —" in card
        assert "()" not in card
    if how.startswith("string_"):
        assert "(its stored probe result could not be read)" in card


def test_a_fresh_mixed_error_report_is_not_called_repeatable(tmp_path: Path) -> None:
    project = tmp_path / "partial-raise"
    shutil.copytree(FIXTURES / "healthy", project)
    (project / "scorer.py").write_text(
        "def score(output, expected):\n"
        "    if output == expected:\n        return 1.0\n"
        "    if expected.startswith(output):\n"
        "        raise RuntimeError('partial')\n"
        "    return 0.0\n",
        encoding="utf-8",
    )
    report = _tier1_report(project, tmp_path / "tier1")

    without = run_tier2("--from-audit", str(report))
    assert without.returncode == 0, without.stderr
    assert "APPROVAL CARD — stop-here   (recommended)" in without.stdout
    assert without.stdout.count("(recommended)") == 1

    with_run = run_tier2("--from-audit", str(report), "--run-id", RUN_ID)
    assert with_run.returncode == 0, with_run.stderr
    assert "APPROVAL CARD — evaluator-quality   (recommended)" in with_run.stdout
    card = _card(with_run.stdout, "evaluator-quality")
    # Not judged: a raised call leaves the reading not established.
    assert "NOT reliable" not in card
    assert re.search(
        r"scored some probe calls and 1 probe call\(s\) raised RuntimeError"
        r" at scorer\.py:\d+",
        card,
    ), card
    assert "not established that a run would get a usable score" in card
    assert "rule out the probe's own conditions" in card
    assert "measuring the scorer" not in card
    assert "found it repeatable" not in card


def test_a_probe_with_no_finite_score_is_not_called_repeat_scored(
    tmp_path: Path,
) -> None:
    project = tmp_path / "all-nan"
    shutil.copytree(FIXTURES / "healthy", project)
    (project / "scorer.py").write_text(
        "def score(output, expected):\n    return float('nan')\n", encoding="utf-8"
    )
    report = _tier1_report(project, tmp_path / "tier1")
    completed = run_tier2("--from-audit", str(report), "--run-id", RUN_ID)
    assert completed.returncode == 0, completed.stderr
    card = _card(completed.stdout, "evaluator-quality")
    assert "repeat-scored" not in card
    assert "Tier 1 probed your scorer and it produced no finite score" in card
