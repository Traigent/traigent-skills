"""How the key travels, and where it is allowed to travel at all.

The live probe of the portal settled both of these (2026-09-13): the API key is
accepted only in `X-API-Key`, and the standard-library default User-Agent is
refused at the edge with HTTP 403 before the service ever sees the request. Both
are asserted here against a real listener's record of the headers it received.
"""

from __future__ import annotations

from pathlib import Path

from conftest import run_tier2
from tier2_fake_backend import EXPERIMENT_ID, RUN_ID, FakeBackend


def test_every_request_carries_the_api_key_header_and_the_sdk_user_agent(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
            "--approve", "example-insights",
            "--approve", "example-scoring",
            "--approve", "decision-brief",
        )
        assert completed.returncode == 0, completed.stderr
        assert len(backend.log) == 4
        for row in backend.log:
            assert row["has_api_key"], row
            assert (row["user_agent"] or "").startswith("traigent-sdk/"), row
            assert "authorization" not in row["header_names"], row


def test_a_plain_http_backend_is_refused_unless_it_is_loopback(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    completed = run_tier2(
        "--from-audit", str(healthy_tier1),
        "--backend-url", "http://example.invalid",
        "--run-id", RUN_ID,
        "--approve", "evaluator-quality",
    )
    assert completed.returncode == 2
    assert "refusing backend URL" in completed.stderr


def test_the_refusal_is_not_a_refusal_of_every_http_url(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """Teeth: the loopback exception is what the whole test suite runs on."""
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
        )
        assert completed.returncode == 0, completed.stderr
        assert len(backend.log) == 1


def test_an_https_backend_is_accepted_without_being_called(
    healthy_tier1: Path
) -> None:
    completed = run_tier2(
        "--from-audit", str(healthy_tier1),
        "--backend-url", "https://portal.traigent.ai",
    )
    assert completed.returncode == 0, completed.stderr
    assert "https://portal.traigent.ai" in completed.stdout


def test_every_request_url_the_script_builds_is_pinned(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """The exact path of every request, against the ORIGIN as the base URL.

    Observed 2026-09-13: `BackendAnalyticsClient` and `traigent plan` take the
    ORIGIN (no `/api/v1`), while `ExampleInsightsClient` takes the `/api/v1`
    base. This script uses raw httpx and builds full `/api/v1/...` paths onto the
    origin, so the whole set is pinned here rather than left to convention.
    """
    with FakeBackend(computed=True) as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--list-runs",
            "--approve", "evaluator-quality",
            "--approve", "example-insights",
            "--approve", "example-scoring",
            "--approve", "decision-brief",
            "--approve", "list-runs",
        )
        assert completed.returncode == 0, completed.stderr
        assert [row["path"] for row in backend.log] == [
            f"/api/v1/analytics/runs/{RUN_ID}/evaluator-quality",
            f"/api/v1/analytics/runs/{RUN_ID}/example-insights",
            f"/api/v1/analytics/example-scoring/{RUN_ID}/summary",
            f"/api/v1/analytics/example-scoring/{RUN_ID}/dataset-quality",
            f"/api/v1/analytics/runs/{RUN_ID}/decision-payload",
            "/api/v1/experiments?limit=10",
            f"/api/v1/experiment-runs/{EXPERIMENT_ID}/runs",
        ]
        # Never a doubled prefix, whatever the base URL was.
        assert not any("/api/v1/api/v1" in row["path"] for row in backend.log)
