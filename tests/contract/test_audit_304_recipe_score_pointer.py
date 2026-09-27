"""Boost-agent instrument recipe: do not present ``score`` as the primary objective.

Traigent/traigent-skills#304 (the instrument-recipe pointer). In a run with more
than one objective, ``metrics["score"]`` and ``trial.score`` are the weighted
selection basis, not the primary objective. The recipe optimizes
``["accuracy", "cost"]``, so it must tell readers to read objectives by name.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "skills" / "traigent-boost-agent" / "references" / "instrument-recipe.md"


def test_recipe_reads_objectives_by_name_not_score() -> None:
    text = " ".join(RECIPE.read_text(encoding="utf-8").split())
    assert 'objectives=["accuracy", "cost"]' in text
    assert "score mirrors the primary objective" not in text
    assert "mirrors a single built-in primary objective" in text
    assert 'trial.metrics["accuracy"]' in text
