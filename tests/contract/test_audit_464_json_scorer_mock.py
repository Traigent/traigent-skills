"""Issue #464: a reply-parsing scorer fails every trial under mock, it does not score 0.0.

The mock reply is the canned text ``This is a mock response for testing.``; a scorer that
``json.loads`` it raises, the SDK refuses to turn that into a fabricated 0.0, and every
trial fails (``best_score`` None, process exit 0). The skills promised "uniformly 0.0" for
JSON-schema scorers. They must split the two scorer shapes and must not tell users to
catch the error.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.version import Version

from .mock_probe import run_probe

BOOST = "skills/traigent-boost-agent/SKILL.md"
MOCK_MODE = "skills/traigent-debugging/references/mock-mode.md"
FALLBACK = "skills/traigent-setup-quickstart/references/first-value-fallback.md"
QUICKSTART = "skills/traigent-setup-quickstart/SKILL.md"


def _flat(root: Path, rel: str) -> str:
    text = (root / rel).read_text(encoding="utf-8")
    return " ".join(re.sub(r"\n>[ ]?", "\n", text).split())  # drop blockquote markers


def test_boost_agent_splits_numeric_and_parsing_scorers(repo_root: Path) -> None:
    text = _flat(repo_root, BOOST)
    assert "sees the mock LLM's constant response and scores uniformly 0.0" not in text
    step3 = text.split("### Step 3: Run Mock Optimization", 1)[1].split("### Step 3.5", 1)[0]
    assert "Parses the reply" in step3
    assert "every trial fails" in step3
    assert "All trials failed" in step3
    assert "Do not patch the scorer to swallow the error" in step3
    assert "valid JSON before the model call" in step3


def test_debugging_mock_mode_no_longer_lists_json_schema_as_uniform_zero(repo_root: Path) -> None:
    text = _flat(repo_root, MOCK_MODE)
    assert "(exact-match, JSON-schema, SQL execution accuracy), every trial scores 0.0" not in text
    assert "every trial fails" in text and "All trials failed" in text


@pytest.mark.parametrize("rel", [FALLBACK, QUICKSTART])
def test_quickstart_surfaces_mention_the_parsing_case(repo_root: Path, rel: str) -> None:
    text = _flat(repo_root, rel)
    assert "parse" in text and "json.loads" in text


def test_debugging_skill_no_longer_lists_json_schema_as_uniform_zero(repo_root: Path) -> None:
    text = _flat(repo_root, "skills/traigent-debugging/SKILL.md")
    assert "(exact-match, JSON-schema, SQL execution-accuracy) scores **0.0" not in text
    assert "fails **every trial**" in text


def test_nobody_is_told_to_swallow_the_parse_error(repo_root: Path) -> None:
    assert "Do not patch the scorer to swallow the error" in _flat(repo_root, BOOST)
    assert "Do not wrap the scorer to swallow the error" in _flat(repo_root, MOCK_MODE)


def test_parsing_scorer_fails_every_trial_under_mock(tmp_path: Path, sdk_version_label: str) -> None:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.31.0"):
        pytest.skip("canned-reply behaviour measured on SDK 0.31.0+")
    parsing = run_probe(tmp_path / "parse", rows=3, scorer="parse", extra_env={})
    assert parsing == {"error": None, "trials": 2, "failed": 2, "best_score": None}
    numeric = run_probe(tmp_path / "num", rows=3, scorer="number", extra_env={})
    assert numeric == {"error": None, "trials": 2, "failed": 0, "best_score": 0.0}
