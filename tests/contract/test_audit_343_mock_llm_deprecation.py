"""TRAIGENT_MOCK_LLM is deprecated, and mock mode does not bypass cost limits.

Traigent/traigent-skills#343 (the parts in the boost-agent and debugging skills).
On traigent 0.27.0 the env var emits a DeprecationWarning that Python hides by
default ("will be removed in a future release"), and the runtime cost enforcer
runs in mock mode too. Recipes that set the env var must say it is deprecated.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from .extract import _iter_fenced_blocks

ROOT = Path(__file__).resolve().parents[2]
# Skills this check owns; widen as the other skills that teach the env var are updated.
SCANNED_SKILLS = ("traigent-boost-agent", "traigent-debugging")
# A line that SETS the env var to true (export, inline, YAML env, os.environ, monkeypatch).
SETS_MOCK_LLM = re.compile(
    r"""TRAIGENT_MOCK_LLM\s*[=:]\s*["']?true|"""
    r"""\[["']TRAIGENT_MOCK_LLM["']\]\s*=\s*["']true|"""
    r"""setenv\(\s*["']TRAIGENT_MOCK_LLM["']\s*,\s*["']true""",
    re.IGNORECASE,
)
# Sections that teach the in-code API; an env-var setter there is a regression.
IN_CODE_SECTIONS = ("in python", "in pytest", "recommended (in-code)")


def _is_heading(line: str) -> bool:
    return line.lstrip().startswith("#") and not line.startswith("    ")


def _paragraph(lines: list[str], index: int) -> list[str]:
    """Contiguous non-blank lines around ``index``, never crossing a heading."""
    lo = index
    while lo > 0 and lines[lo - 1].strip() and not _is_heading(lines[lo - 1]):
        lo -= 1
    hi = index
    while hi + 1 < len(lines) and lines[hi + 1].strip() and not _is_heading(lines[hi + 1]):
        hi += 1
    return lines[lo : hi + 1]


def _unit(lines: list[str], blocks, index: int) -> str:
    """The structural unit a setter belongs to.

    Inside a fenced block: the block itself plus the prose paragraph directly above
    its opening fence (stopping at a heading). Outside a fence: its own paragraph.
    """
    for block in blocks:
        first = block.start_line - 1  # 0-based first content line
        last = first + len(block.lines) - 1
        if first <= index <= last:
            above = first - 2  # line before the opening fence
            while above >= 0 and not lines[above].strip():
                above -= 1
            prose = [] if above < 0 or _is_heading(lines[above]) else _paragraph(lines, above)
            return "\n".join(prose + list(block.lines))
    return "\n".join(_paragraph(lines, index))


def _section_heading(lines: list[str], index: int) -> str:
    for line in reversed(lines[: index + 1]):
        if _is_heading(line):
            return line.lstrip("#").strip().lower()
    return ""


def _setter_sites():
    for skill in SCANNED_SKILLS:
        for path in sorted((ROOT / "skills" / skill).glob("**/*.md")):
            lines = path.read_text(encoding="utf-8").splitlines()
            blocks = _iter_fenced_blocks(lines)
            for index, line in enumerate(lines):
                if SETS_MOCK_LLM.search(line):
                    yield path, lines, blocks, index


def test_every_mock_llm_recipe_says_it_is_deprecated() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{index + 1}: {lines[index].strip()}"
        for path, lines, blocks, index in _setter_sites()
        if "deprecated" not in _unit(lines, blocks, index).lower()
    ]
    assert not offenders, (
        "TRAIGENT_MOCK_LLM=true taught without 'deprecated' in its code block or the "
        "paragraph that introduces it:\n" + "\n".join(offenders)
    )


def test_in_code_mock_sections_do_not_set_the_env_var() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{index + 1}: under {_section_heading(lines, index)!r}"
        for path, lines, blocks, index in _setter_sites()
        if _section_heading(lines, index) in IN_CODE_SECTIONS
    ]
    assert not offenders, "env-var mock setup inside an in-code API section:\n" + "\n".join(offenders)


def test_mock_mode_reference_states_cost_limits_still_apply() -> None:
    text = " ".join(
        (ROOT / "skills" / "traigent-debugging" / "references" / "mock-mode.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert 'stop_reason="cost_limit"' in text
    assert "bypass cost tracking" not in text and "bypasses cost tracking" not in text


def test_mock_run_still_enforces_the_cost_limit(tmp_path: Path) -> None:
    pytest.importorskip("traigent")
    (tmp_path / "home").mkdir()
    script = tmp_path / "probe.py"
    script.write_text(
        textwrap.dedent(
            """
            import traigent
            from pathlib import Path
            from traigent.testing import enable_mock_mode_for_quickstart

            enable_mock_mode_for_quickstart()
            Path("qa.jsonl").write_text('{"input": {"question": "q"}, "output": "4"}\\n')

            @traigent.optimize(eval_dataset="qa.jsonl", objectives=["accuracy"], offline=True,
                               configuration_space={"model": ["gpt-4o-mini", "gpt-4o"],
                                                    "temperature": [0.1, 0.5]})
            def f(question: str) -> str:
                traigent.get_config()
                return "4"

            r = f.optimize_sync(max_trials=4, algorithm="grid")
            print(f"RESULT={r.stop_reason}|{len(r.trials)}")
            """
        ),
        encoding="utf-8",
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.endswith("_API_KEY") and k not in {"TRAIGENT_MOCK_LLM", "CI", "GITHUB_ACTIONS"}
    }
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "ENVIRONMENT": "test",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "TRAIGENT_OFFLINE_MODE": "true",
            "TRAIGENT_RUN_COST_LIMIT": "0.0001",
        }
    )
    completed = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(ln for ln in completed.stdout.splitlines() if ln.startswith("RESULT="))
    stop_reason, trials = line.removeprefix("RESULT=").split("|")
    assert (stop_reason, trials) == ("cost_limit", "0")
