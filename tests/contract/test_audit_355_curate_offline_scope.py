"""Issue #355 (dataset-curate part): ``offline=True`` is not zero egress.

``offline=True`` / ``TRAIGENT_OFFLINE_MODE`` stop Traigent backend traffic only.
Importing LiteLLM still fetches its pricing map from the network unless
``LITELLM_LOCAL_MODEL_COST_MAP=True`` is set first, and provider calls that mock
mode does not intercept still go out. The dataset-curate mock-first bullet must
scope its egress claim to the Traigent backend and name the LiteLLM variable.
"""

from __future__ import annotations

from pathlib import Path

CURATE = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "traigent-dataset-curate"
    / "SKILL.md"
)


def test_mock_first_bullet_scopes_offline_to_the_traigent_backend() -> None:
    bullet = next(
        line
        for line in CURATE.read_text(encoding="utf-8").splitlines()
        if line.startswith("- Mock") and "offline=True" in line
    )
    assert "zero-egress" not in bullet, bullet
    assert "zero Traigent backend egress" in bullet, bullet
    assert "LITELLM_LOCAL_MODEL_COST_MAP=True" in bullet, bullet
