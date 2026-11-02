"""A recipe exists for agents whose output is a ranked list under a budget.

Traigent/traigent-skills#474. No skill gave a list-output metric (recall at a
budget) or documented the metric parameter (`llm_metrics` / `metrics`) that
carries per-example usage, so a builder packed per-item seconds and model spend
into the expected-output JSON. The documented names must be the names the SDK
binds, and the recipe must be reachable from the metric chooser and from the
`test_selection_strategy` knob description.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
EVAL_BUILD = SKILLS / "traigent-eval-build" / "SKILL.md"
CHOOSE = SKILLS / "traigent-eval-choose-metric" / "SKILL.md"
SPINE = SKILLS / "traigent-optimize-config-space" / "references" / "structural-spine.md"
BOOST = SKILLS / "traigent-boost-agent" / "SKILL.md"

RECIPE_HEADING = "### Ranked or selected outputs (recall at a budget)"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start + len(heading) :]
    nxt = re.search(r"^#{2,3} ", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def test_eval_build_documents_the_usage_parameter_and_the_ranking_recipe() -> None:
    text = EVAL_BUILD.read_text(encoding="utf-8")
    assert RECIPE_HEADING in text
    recipe = _section(text, RECIPE_HEADING)
    for needle in ("llm_metrics", "metrics", "total_cost", "response_time_ms", "metadata"):
        assert needle in recipe, needle
    # The names list of Tier 3 names the usage parameter too.
    names = text.split("The names available are:")[1].split("\n\n")[0]
    assert "llm_metrics" in names


def test_the_recipe_scorer_runs_and_counts_unknown_items_honestly() -> None:
    text = EVAL_BUILD.read_text(encoding="utf-8")
    recipe = _section(text, RECIPE_HEADING)
    block = re.search(r"```python runnable\n(.*?)```", recipe, re.DOTALL)
    assert block, "the recipe needs a runnable scorer"
    namespace: dict = {}
    exec(compile(block.group(1), "recipe", "exec"), namespace)  # noqa: S102
    scorer = namespace["recall_at_budget"]
    meta = {"secs": {"a": 10, "b": 20, "c": 30}, "budget": 40, "secs_per_usd": 100}
    usage = {"total_cost": 0.0}
    assert scorer(["a", "b"], ["a", "c"], meta, usage) == 0.5
    # An unknown item neither finds anything nor spends budget.
    assert scorer(["zz", "a"], ["a"], meta, usage) == 1.0
    # Model spend is charged against the same budget: 0.3 USD = 30 s.
    assert scorer(["a", "b"], ["a", "b"], meta, {"total_cost": 0.3}) == 0.5
    # Unmeasured spend must not read as free.
    with pytest.raises(ValueError):
        scorer(["a"], ["a"], meta, {"total_cost": None})


def test_the_choose_metric_skill_and_the_knob_table_point_at_the_recipe() -> None:
    assert "Ranked or selected outputs" in CHOOSE.read_text(encoding="utf-8")
    spine = SPINE.read_text(encoding="utf-8")
    row = next(
        line for line in spine.splitlines() if line.startswith("| `test_selection_strategy`")
    )
    assert "traigent-eval-build" in row and "Ranked or selected outputs" in row


def test_the_usage_parameter_names_are_the_ones_the_sdk_binds() -> None:
    # Read the source rather than import it: the module pulls optional runtime
    # dependencies this check does not need.
    spec = importlib.util.find_spec("traigent")
    if spec is None or not spec.submodule_search_locations:
        pytest.skip("the traigent SDK is not importable here")
    source = Path(next(iter(spec.submodule_search_locations))) / "evaluators" / "local.py"
    match = re.search(r"^_LLM_METRIC_PARAM_NAMES\s*=\s*(\{[^}]*\})", source.read_text("utf-8"), re.M)
    if match is None:
        pytest.skip("this SDK release does not bind a usage parameter")
    assert {"llm_metrics", "metrics"} <= ast.literal_eval(match.group(1))
