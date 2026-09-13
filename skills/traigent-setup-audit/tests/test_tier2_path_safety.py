"""A path segment is not a path, and a receipt must record what was SENT.

Three defects, each reproduced here before it was fixed:

1. `--run-id ../../../../api/v1/admin/secrets` walked the request to a different
   endpoint than the one the card named — the server saw
   `GET /api/v1/admin/secrets/evaluator-quality`;
2. the receipt recorded the string this script assembled, not the one httpx put
   on the wire, so it disagreed with the server's own log in exactly the case
   where the log matters;
3. the `experiment_id` in the SERVER's own reply is interpolated into the next
   request's path, so a hostile reply moved the follow-up request out of the
   experiment-runs endpoint entirely.

The run id is now refused before any request when it is not run-id shaped, every
segment is quoted, and the receipt reads the path back off the request object.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import run_tier2
from tier2_fake_backend import HOSTILE_EXPERIMENT_ID, RUN_ID, FakeBackend

TRAVERSAL_RUN_ID = "../../../../api/v1/admin/secrets"


def receipt_rows(path: Path) -> list[tuple[str, str, int | None]]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    return [(row["method"], row["path"], row.get("status"))
            for row in receipt["requests"]]


def log_rows(backend: FakeBackend) -> list[tuple[str, str, int | None]]:
    return [(row["method"], row["path"], row["status"]) for row in backend.log]


def test_a_traversal_run_id_is_refused_before_any_request(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path
) -> None:
    receipt = tmp_path / "receipt.json"
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", TRAVERSAL_RUN_ID,
            "--approve", "evaluator-quality",
            "--receipt", str(receipt),
        )
        assert completed.returncode == 2
        assert backend.log == []
    assert "is not a run id" in completed.stderr
    assert not receipt.exists()


def test_a_traversal_run_id_is_refused_in_offer_mode_too(
    healthy_tier1: Path
) -> None:
    """The card would otherwise print it back as the id to approve."""
    completed = run_tier2("--from-audit", str(healthy_tier1),
                          "--run-id", TRAVERSAL_RUN_ID)
    assert completed.returncode == 2
    assert "is not a run id" in completed.stderr


def test_a_real_run_id_still_passes_the_check(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """Teeth: the pattern must admit the run ids the portal actually issues."""
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
        )
        assert completed.returncode == 0, completed.stderr
        assert len(backend.log) == 1


def test_a_hostile_experiment_id_cannot_leave_its_endpoint(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path
) -> None:
    """The id comes from the server's reply, and it becomes a path segment."""
    receipt = tmp_path / "receipt.json"
    with FakeBackend(experiment_id=HOSTILE_EXPERIMENT_ID) as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--list-runs",
            "--approve", "list-runs",
            "--receipt", str(receipt),
        )
        assert completed.returncode == 0, completed.stderr
        paths = [row["path"] for row in backend.log]
        assert paths[0] == "/api/v1/experiments?limit=10"
        # One segment, still inside the endpoint the card named: every `/` in the
        # hostile id is encoded, so it cannot introduce a path boundary.
        assert paths[1] == (
            "/api/v1/experiment-runs/"
            "..%2F..%2F..%2F..%2Fapi%2Fv1%2Fadmin%2Fsecrets/runs"
        )
        assert paths[1].count("/") == 5
        assert "/admin/secrets" not in paths[1]
        # The receipt is the record of what was sent, so it must equal the log.
        assert receipt_rows(receipt) == log_rows(backend)


def test_a_bare_dot_segment_from_the_server_cannot_climb(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """`quote("..")` is still `".."`; a dots-only segment gets its dots encoded."""
    with FakeBackend(experiment_id="..") as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--list-runs",
            "--approve", "list-runs",
        )
        assert completed.returncode == 0, completed.stderr
        paths = [row["path"] for row in backend.log]
        assert paths[1] == "/api/v1/experiment-runs/%2E%2E/runs"


def test_the_receipt_records_the_path_that_was_sent(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path
) -> None:
    """Every row is marked as read back off the wire, not as locally assembled."""
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
        rows = json.loads(receipt.read_text(encoding="utf-8"))["requests"]
        assert all(row["path_sent"] is True for row in rows)
        assert receipt_rows(receipt) == log_rows(backend)


def test_one_list_runs_approval_is_a_bounded_number_of_requests(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path
) -> None:
    """A limit=10 page answered with 50 experiments is not 51 requests."""
    receipt = tmp_path / "receipt.json"
    with FakeBackend(experiments_in_reply=50) as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--list-runs",
            "--approve", "list-runs",
            "--receipt", str(receipt),
        )
        assert completed.returncode == 0, completed.stderr
        assert len(backend.log) == 1 + 10
        assert len(receipt_rows(receipt)) == 1 + 10
    assert "the reply carried 50 experiment(s) for a limit=10 page" in completed.stdout
    assert "40 were not fetched" in completed.stdout


def test_the_page_cap_does_not_fire_on_a_normal_reply(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """Teeth: a one-experiment reply is read whole and says nothing about a cap."""
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--list-runs",
            "--approve", "list-runs",
        )
        assert completed.returncode == 0, completed.stderr
        assert len(backend.log) == 2
    assert "were not fetched" not in completed.stdout


def test_an_abbreviated_approve_flag_is_a_usage_error_not_a_silent_run(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """`--appr <id>` used to install the guard AND take the run-mode path."""
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--appr", "evaluator-quality",
        )
        assert completed.returncode == 2
        assert backend.log == []
    assert "Tier 2 run" not in completed.stdout
    assert "NetworkDisabled" not in completed.stdout + completed.stderr


def test_the_unabbreviated_flag_still_works(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """Teeth for the test above."""
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
        )
        assert completed.returncode == 0, completed.stderr
        assert len(backend.log) == 1


def test_run_mode_counts_the_processes_it_spawned(
    healthy_tier1: Path, sentinel_key: str, fake_traigent_cli: Path, tmp_path: Path
) -> None:
    """The process count is measured, not asserted — the guard never covered it."""
    receipt = tmp_path / "receipt.json"
    completed = run_tier2(
        "--from-audit", str(healthy_tier1),
        "--approve", "model-ids",
        "--receipt", str(receipt),
    )
    assert completed.returncode == 0, completed.stderr
    assert "0 request(s) and 2 process(es) were made — both counted" in completed.stdout
