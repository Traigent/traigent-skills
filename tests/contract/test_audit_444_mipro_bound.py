"""Issue #444: the DSPy ``method="mipro"`` crash is not fixed in any release through 0.30.0.

The caveat must not carry an ``<=0.27.0`` upper bound (it reads as "fixed in
0.28.0+"), and the offline DummyLM repro pins the crash on the installed release.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "skills" / "traigent-setup-integrations"
PAGES = (ROOT / "SKILL.md", ROOT / "references" / "dspy.md")


def test_mipro_caveat_has_no_stale_upper_bound() -> None:
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if re.search(r"mipro|MIPRO|requires_permission_to_run|bootstrap", line):
                assert not re.search(r"<=\s*0\.27\.0", line), f"{page.name}:{number}"
        assert "through 0.30.0" in text


def test_mipro_still_crashes_on_the_installed_release() -> None:
    dspy = pytest.importorskip("dspy")
    from packaging.version import Version

    import traigent

    if Version(traigent.__version__) > Version("0.30.0"):
        pytest.skip("caveat bound is 0.30.0; re-verify on newer releases")
    from dspy.utils.dummies import DummyLM

    from traigent.integrations.dspy_adapter import DSPyPromptOptimizer

    dspy.configure(lm=DummyLM([{"answer": "a"}] * 200))
    trainset = [
        dspy.Example(question=f"q{i}", answer="a").with_inputs("question") for i in range(4)
    ]
    with pytest.raises(TypeError, match="requires_permission_to_run"):
        DSPyPromptOptimizer(method="mipro").optimize_prompt(
            module=dspy.Predict("question -> answer"),
            trainset=trainset,
            metric=lambda e, p, t=None: 1.0,
        )
