"""CI safety gate: the TVL validation step must fail when no spec was validated.

Traigent/traigent-skills#323. ``python -m traigent.tvl tvl/ --strict`` exits 0 when
``tvl/`` is missing, empty, or holds only ``*.tvl`` files (the validator discovers
only ``*.tvl.yml`` / ``*.tvl.yaml``), so the taught step passed CI while
validating nothing, including a broken spec named the way the skill showed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from .extract import _iter_fenced_blocks

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "skills" / "traigent-ci-safety-gate"
VALID_SPEC = textwrap.dedent(
    """\
    tvl:
      module: examples.gate
    tvl_version: "1.0"
    tvars:
      - name: model
        type: enum[str]
        domain: ["gpt-4o", "gpt-4o-mini"]
        default: "gpt-4o-mini"
    objectives:
      - name: accuracy
        direction: maximize
    """
)


def _tvl_steps() -> list[tuple[str, str]]:
    steps = []
    for path in sorted(SKILL_DIR.glob("**/*.md")):
        for block in _iter_fenced_blocks(path.read_text(encoding="utf-8").splitlines()):
            if block.language not in {"yaml", "yml"}:
                continue
            workflow = yaml.safe_load(block.text)
            for job_name, job in (workflow or {}).get("jobs", {}).items():
                for step in job.get("steps", []):
                    run = step.get("run", "")
                    if "traigent.tvl" in run:
                        steps.append((f"{path.relative_to(ROOT)}:{block.start_line}:{job_name}", run))
    return steps


def test_every_tvl_example_path_uses_a_discoverable_suffix() -> None:
    bad = []
    for path in sorted(SKILL_DIR.glob("**/*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in re.finditer(r"[\w./-]+\.tvl(?![.\w])", line):
                if match.group(0).endswith("traigent.tvl"):  # the module, not a spec file
                    continue
                bad.append(f"{path.relative_to(ROOT)}:{number}: {match.group(0)}")
    assert not bad, "TVL spec names the validator will not discover:\n" + "\n".join(bad)


def test_workflow_tvl_steps_assert_a_spec_exists() -> None:
    steps = _tvl_steps()
    assert len(steps) >= 3, steps
    unguarded = [where for where, run in steps if '-gt 0' not in run or re.search(r"traigent\.tvl\s+tvl/", run)]
    assert not unguarded, "TVL step with no spec-count guard: " + ", ".join(unguarded)


@pytest.mark.parametrize(
    ("case", "expected_ok"),
    [("missing_dir", False), ("only_dot_tvl", False), ("broken_spec", False), ("valid_spec", True)],
)
def test_workflow_tvl_steps_fail_closed(tmp_path: Path, case: str, expected_ok: bool) -> None:
    pytest.importorskip("traigent.tvl")
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to run the workflow step")
    for where, run in _tvl_steps():
        work = tmp_path / re.sub(r"\W", "_", where)
        work.mkdir()
        if case != "missing_dir":
            (work / "tvl").mkdir()
        if case == "only_dot_tvl":
            (work / "tvl" / "promotion-gate.tvl").write_text("this: [is: not valid\n", encoding="utf-8")
        if case == "broken_spec":
            (work / "tvl" / "promotion-gate.tvl.yml").write_text("this: [is: not valid\n", encoding="utf-8")
        if case == "valid_spec":
            (work / "tvl" / "promotion-gate.tvl.yml").write_text(VALID_SPEC, encoding="utf-8")
        script = re.sub(r"\bpython -m ", f"{sys.executable} -m ", run)
        completed = subprocess.run(
            [bash, "-e", "-c", script], cwd=work, text=True, capture_output=True, timeout=120, check=False
        )
        ok = completed.returncode == 0
        assert ok is expected_ok, (
            f"{where} [{case}]: exit {completed.returncode}\n{completed.stdout}{completed.stderr}"
        )
