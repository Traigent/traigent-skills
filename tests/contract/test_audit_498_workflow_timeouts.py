"""CI hygiene: every workflow job is bounded, every PR workflow cancels stale runs.

Traigent/traigent-skills#498. A job without ``timeout-minutes`` runs to the
360-minute GitHub default, so a hung step holds a runner (and leaves a required
check pending) for up to six hours. CodeQL's ``analyze`` job had no timeout.
A job that only calls a reusable workflow (``uses:``) cannot take
``timeout-minutes``; the called workflow's own jobs carry it instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted(
    [*(REPO_ROOT / ".github" / "workflows").glob("*.yml"),
     *(REPO_ROOT / ".github" / "workflows").glob("*.yaml")]
)


def _load(path: Path) -> dict[Any, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data.get("jobs"), f"{path.name}: no jobs"
    return data


def _triggers(workflow: dict[Any, Any]) -> set[str]:
    # PyYAML (YAML 1.1) parses the bare key ``on`` as boolean True.
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    return set(on or {})


def test_workflows_found() -> None:
    assert WORKFLOWS, "no workflow files found"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_declares_timeout_minutes(path: Path) -> None:
    jobs = _load(path)["jobs"]
    unbounded = [
        name
        for name, job in jobs.items()
        if "uses" not in job and not isinstance(job.get("timeout-minutes"), int)
    ]
    assert not unbounded, (
        f"{path.name}: jobs without an integer timeout-minutes (default 360): {unbounded}"
    )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_pull_request_workflows_cancel_superseded_runs(path: Path) -> None:
    workflow = _load(path)
    if "pull_request" not in _triggers(workflow):
        pytest.skip("not a pull_request workflow")
    levels = [workflow.get("concurrency")] + [
        job.get("concurrency") for job in workflow["jobs"].values()
    ]
    assert any(
        isinstance(c, dict) and c.get("cancel-in-progress") is True for c in levels
    ), f"{path.name}: pull_request workflow without a cancel-in-progress concurrency group"
