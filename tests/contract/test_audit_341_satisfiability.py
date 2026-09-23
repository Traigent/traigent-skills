"""The satisfiability check the config-space skill teaches, against the real SDK.

Runs the SKILL.md ConfigSpace example and asserts the status the skill
documents for it (UNKNOWN for a continuous Range), plus the finite-space and
`unsat_core` behaviour the docs describe.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.version import Version

from .extract import _iter_fenced_blocks
from .test_runnable_snippets import _offline_mock_env


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "traigent-optimize-config-space" / "SKILL.md"
CONSTRAINTS = (
    ROOT / "skills" / "traigent-optimize-config-space" / "references" / "constraints.md"
)

DRIVER = r'''
import json
import skill_example
from traigent import Choices, IntRange, Range, require
from traigent.api.config_space import ConfigSpace

m = Choices(["a", "b"], name="m")
k = IntRange(1, 3, name="k")
bad = ConfigSpace(tvars={"m": m, "k": k},
                  constraints=[require(m.equals("a")), require(m.equals("b")), require(k.gte(1))])
bad_sat = bad.check_satisfiability()
t = Range(0.0, 1.0, step=0.5, name="t")
stepped = ConfigSpace(tvars={"t": t, "m": m}, constraints=[require(m.equals("a"))])
print("PROBE_JSON=" + json.dumps({
    "example": skill_example.sat.status.name,
    "finite_unsat": bad_sat.status.name,
    "unsat_core": bad_sat.unsat_core,
    "stepped": stepped.check_satisfiability().status.name,
}))
'''


def _config_space_example() -> str:
    blocks = [
        block.text
        for block in _iter_fenced_blocks(SKILL.read_text(encoding="utf-8").splitlines())
        if block.language == "python" and "space.check_satisfiability()" in block.text
    ]
    assert len(blocks) == 1, "expected one ConfigSpace satisfiability example"
    # Keep everything up to the decorator usage; the example's function body is elided.
    return blocks[0].split("# Use with decorator", 1)[0]


def test_skill_config_space_example_status_matches_docs(
    tmp_path: Path, sdk_version_label: str
) -> None:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.27.0"):
        pytest.skip("satisfiability behaviour verified on SDK 0.27.0+")
    (tmp_path / "skill_example.py").write_text(_config_space_example(), encoding="utf-8")
    (tmp_path / "driver.py").write_text(DRIVER, encoding="utf-8")
    env = _offline_mock_env()
    env["HOME"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "driver.py"], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(r for r in completed.stdout.splitlines() if r.startswith("PROBE_JSON="))
    data = json.loads(line.split("=", 1)[1])
    # The skill says a continuous Range returns UNKNOWN; the example has one.
    assert data["example"] == "UNKNOWN"
    # A finite unsatisfiable space: the core lists every constraint, including
    # the irrelevant `k >= 1`, as the docs now say.
    assert data["finite_unsat"] == "UNSAT"
    assert data["unsat_core"] == [0, 1, 2]
    # Adding `step=` makes the space finite, so the check really runs.
    assert data["stepped"] == "SAT"


def test_docs_explain_unknown_and_full_unsat_core() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "SatStatus.UNKNOWN" in skill
    assert "elif sat.status is SatStatus.UNKNOWN:" in skill
    assert "names the offending constraint" not in skill
    assert "never `if sat:`" in skill
    assert "if sat.status is SatStatus.UNSAT:" in skill
    reference = CONSTRAINTS.read_text(encoding="utf-8")
    assert "SatStatus.UNKNOWN" in reference
    assert "not a minimal core" in reference
