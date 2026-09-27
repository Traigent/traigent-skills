"""Mock mode does not bypass runtime cost enforcement; the env var is deprecated.

Pins the documented mock-mode cost behaviour on the installed SDK: with a tiny
`TRAIGENT_RUN_COST_LIMIT`, a mock run (in-code API or the legacy env var) stops
at 0 trials with `stop_reason="cost_limit"`. Lints the optimize skill files so
a `TRAIGENT_MOCK_LLM=true` recipe always sits next to its deprecation note.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.version import Version

from .test_runnable_snippets import _offline_mock_env


ROOT = Path(__file__).resolve().parents[2]
# Optimize-skill files that mention the env var. Other skills that teach it are
# covered by their own fixes; extend this list as they land.
LINTED = [
    ROOT / "skills" / "traigent-optimize-run" / "SKILL.md",
    ROOT / "skills" / "traigent-optimize-run" / "references" / "cost-management.md",
]
NEAR_LINES = 3
# Any way of SETTING the env var: `X=1`, `X="true"`, `os.environ["X"] = ...`,
# `setenv("X", ...)`, `environ.setdefault("X", ...)`. A bare mention (the
# "check it is unset" guardrail) is not an assignment.
ASSIGN_RE = re.compile(
    r"""TRAIGENT_MOCK_LLM\s*=(?!=)"""
    r"""|TRAIGENT_MOCK_LLM['"]\s*\]\s*=(?!=)"""
    r"""|(?:setenv|setdefault|putenv)\(\s*['"]TRAIGENT_MOCK_LLM['"]"""
)

PROBE = r'''
import json
import os
import traigent
from pathlib import Path

if os.environ.get("USE_IN_CODE_MOCK") == "1":
    import traigent.testing
    traigent.testing.enable_mock_mode_for_quickstart()
Path("qa.jsonl").write_text('{"input": {"question": "q"}, "output": "4"}\n')

@traigent.optimize(eval_dataset="qa.jsonl", objectives=["accuracy"], offline=True,
                   configuration_space={"model": ["gpt-4o-mini", "gpt-4o"],
                                        "temperature": [0.1, 0.5]})
def f(question: str) -> str:
    traigent.get_config()
    return "4"

r = f.optimize_sync(max_trials=4, algorithm="grid")
print("PROBE_JSON=" + json.dumps({"stop_reason": r.stop_reason, "trials": len(r.trials)}))
'''


def _run(tmp_path: Path, extra_env: dict[str, str]) -> tuple[dict, str]:
    (tmp_path / "probe.py").write_text(PROBE, encoding="utf-8")
    env = _offline_mock_env()
    env.update({"HOME": str(tmp_path), "TRAIGENT_RUN_COST_LIMIT": "0.0001"})
    env.update(extra_env)
    completed = subprocess.run(
        [sys.executable, "-W", "always::DeprecationWarning", "probe.py"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(r for r in completed.stdout.splitlines() if r.startswith("PROBE_JSON="))
    return json.loads(line.split("=", 1)[1]), completed.stderr


@pytest.mark.parametrize(
    "extra_env",
    [{"USE_IN_CODE_MOCK": "1"}, {"TRAIGENT_MOCK_LLM": "true"}],
    ids=["in-code-mock", "legacy-env-var"],
)
def test_mock_run_still_enforces_the_cost_limit(
    tmp_path: Path, sdk_version_label: str, extra_env: dict[str, str]
) -> None:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.27.0"):
        pytest.skip("mock-mode cost enforcement verified on SDK 0.27.0+")
    data, stderr = _run(tmp_path, extra_env)
    assert data == {"stop_reason": "cost_limit", "trials": 0}
    if "TRAIGENT_MOCK_LLM" in extra_env:
        assert "TRAIGENT_MOCK_LLM is deprecated" in stderr


def test_skill_files_do_not_claim_a_mock_cost_bypass() -> None:
    text = (ROOT / "skills" / "traigent-optimize-run" / "references" / "cost-management.md").read_text(
        encoding="utf-8"
    )
    assert "cost tracking is bypassed" not in text
    assert "No permits are issued" not in text
    assert "still bypasses cost tracking" not in text
    assert "bypass cost tracking in mock mode" not in text
    assert 'stop_reason="cost_limit"` apply in mock runs too' in text


def test_mock_env_var_recipes_carry_a_deprecation_note() -> None:
    for path in LINTED:
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not ASSIGN_RE.search(line):
                continue
            window = lines[max(0, index - NEAR_LINES): index + NEAR_LINES + 1]
            assert any("deprecated" in item.lower() for item in window), (
                f"{path.relative_to(ROOT)}:{index + 1}: TRAIGENT_MOCK_LLM is set "
                "without a nearby deprecation note"
            )
