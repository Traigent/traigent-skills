"""Issue #335: mock mode does not intercept a standalone ExampleSynthesizer.

``enable_mock_mode_for_quickstart()`` installs no litellm interceptor until an
evaluator is built, so the client-side synthesis snippet's ``private_llm`` makes
a real provider call during what the user believes is a free mock check. The
skill must say so and give a stub-``llm`` smoke test. That stub snippet is
tagged ``runnable`` (so the runnable-snippet suite executes it), and here it is
executed with every ``litellm.completion`` call turned into a failure, proving it
makes zero provider calls.
"""

from __future__ import annotations

import re
from pathlib import Path

from .test_audit_326_comparator_case import _run_driver

CURATE = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "traigent-dataset-curate"
    / "SKILL.md"
)
SECTION = (
    CURATE.read_text(encoding="utf-8")
    .split("## Synthesize examples client-side", 1)[-1]
    .split("\n## ", 1)[0]
)
RUNNABLE_BLOCKS = re.findall(
    r"^```python runnable\n(.*?)^```", SECTION, re.MULTILINE | re.DOTALL
)


def test_synthesis_section_warns_mock_mode_does_not_cover_it() -> None:
    assert "Mock mode does not cover this snippet" in SECTION
    assert "ExampleSynthesizer" in SECTION and "stub" in SECTION


def test_stub_smoke_test_runs_with_zero_provider_calls(tmp_path: Path) -> None:
    assert len(RUNNABLE_BLOCKS) == 1, (
        "the synthesis section needs one runnable stub-llm smoke test"
    )
    body = """
    def refuse(*args, **kwargs):
        raise AssertionError("provider call attempted: " + str(kwargs.get("model")))
    litellm.completion = refuse
    load_block(sys.argv[1])
    emit({"provider_calls": 0})
    """
    assert _run_driver(tmp_path, RUNNABLE_BLOCKS[0], body) == {"provider_calls": 0}
