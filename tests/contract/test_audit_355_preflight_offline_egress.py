"""preflight.md must not call an offline=True run zero-egress (#355).

``offline=True`` stops Traigent backend traffic only: model-provider calls still
go out, and LiteLLM fetches its pricing map at import unless
``LITELLM_LOCAL_MODEL_COST_MAP=True`` is set.
"""

from __future__ import annotations

from pathlib import Path

PREFLIGHT = Path("skills/traigent-analyze-guidance/references/preflight.md")


def test_offline_run_is_scoped_to_traigent_backend_egress(repo_root: Path) -> None:
    text = " ".join((repo_root / PREFLIGHT).read_text(encoding="utf-8").split())
    assert "zero-egress run" not in text
    assert "zero Traigent backend egress" in text
    assert "model-provider calls still go out" in text
    assert "LITELLM_LOCAL_MODEL_COST_MAP=True" in text
