"""Boost-agent instrument recipe: the mock dry-run is keyless, local, and cannot pass falsely.

Traigent/traigent-skills#349 (the instrument-recipe part). The recipe's After
block called a raw ``openai`` client, which mock mode does not intercept: keyless
it crashed at import, and with a key every dry-run call went to the provider. It
also mapped a composite with no output to ``""``, so a run where every model call
failed reported zero failed trials.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from .extract import _iter_fenced_blocks

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "skills" / "traigent-boost-agent" / "references" / "instrument-recipe.md"
# Skills whose markdown this check owns; widen as sibling skills adopt the caveat.
SCANNED_SKILLS = (
    "traigent-boost-agent",
    "traigent-recipe-text2sql",
    "traigent-debugging",
    "traigent-ci-safety-gate",
)
RAW_CLIENT_RE = re.compile(
    r"openai\.chat\.completions\.create|\bOpenAI\(\)|anthropic\.Anthropic\(\)"
)
CAVEAT = "Mock mode covers LiteLLM/LangChain calls only"


def _after_block() -> str:
    section = RECIPE.read_text(encoding="utf-8").split("## After", 1)[1].split("## Environment", 1)[0]
    python = [b.text for b in _iter_fenced_blocks(section.splitlines()) if b.language == "python"]
    assert len(python) == 1
    return python[0]


def _run_after_block(tmp_path: Path, *, stubs: str, env_extra: dict[str, str]) -> dict:
    pytest.importorskip("traigent")
    (tmp_path / "evals").mkdir()
    rows = [
        {"input": {"question": "What is 2+2?"}, "output": "4"},
        {"input": {"question": "Capital of France?"}, "output": "Paris"},
    ]
    (tmp_path / "evals" / "qa.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (tmp_path / "home").mkdir()
    agent = tmp_path / "agent.py"
    agent.write_text(_after_block() + "\n", encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text(
        textwrap.dedent(
            """
            import builtins, json, runpy, socket
            connects = []
            _connect = socket.socket.connect
            def _spy(self, addr):
                if self.family in (socket.AF_INET, socket.AF_INET6):
                    connects.append(str(addr))
                return _connect(self, addr)
            socket.socket.connect = _spy

            from traigent.testing import enable_mock_mode_for_quickstart
            enable_mock_mode_for_quickstart()
            """
        )
        + textwrap.dedent(stubs)
        + textwrap.dedent(
            f"""
            ns = runpy.run_path({str(agent)!r}, run_name="recipe_under_test")
            result = ns["answer_question"].optimize_sync(max_trials=2, algorithm="grid")
            print("RESULT=" + json.dumps({{
                "trials": len(result.trials),
                "failed": len(getattr(result, "failed_trials", []) or []),
                "statuses": [t.status.value for t in result.trials],
                "connects": connects,
            }}))
            """
        ),
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.endswith("_API_KEY") and key not in {"TRAIGENT_MOCK_LLM", "CI", "GITHUB_ACTIONS"}
    }
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "ENVIRONMENT": "test",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "TRAIGENT_OFFLINE_MODE": "true",
            **env_extra,
        }
    )
    completed = subprocess.run(
        [sys.executable, str(runner)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=240,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(ln for ln in completed.stdout.splitlines() if ln.startswith("RESULT="))
    return {**json.loads(line.removeprefix("RESULT=")), "log": completed.stdout + completed.stderr}


WORKING_STUBS = """
builtins.retrieve_context = lambda question, **kw: ["context"]
builtins.format_context = lambda chunks, **kw: "context"
builtins.estimate_last_call_cost_usd = lambda: 0.001
"""


def test_after_block_dry_run_is_keyless_and_makes_no_network_call(tmp_path: Path) -> None:
    result = _run_after_block(tmp_path, stubs=WORKING_STUBS, env_extra={})
    assert result["connects"] == [], f"mock dry-run left the machine: {result['connects']}"
    assert result["trials"] >= 1
    assert result["failed"] == 0, result["log"][-3000:]
    assert set(result["statuses"]) == {"completed"}, result["statuses"]


def test_after_block_reports_failed_model_calls_as_failed_trials(tmp_path: Path) -> None:
    failing = """
def _unreachable(question, **kw):
    raise RuntimeError("provider call failed")
builtins.retrieve_context = _unreachable
builtins.format_context = lambda chunks, **kw: "context"
builtins.estimate_last_call_cost_usd = lambda: 0.001
"""
    # A fake key and a dead endpoint only let an older raw-client recipe import;
    # the failing stub raises before any client call.
    result = _run_after_block(
        tmp_path,
        stubs=failing,
        env_extra={"OPENAI_API_KEY": "sk-test-not-a-real-key", "OPENAI_BASE_URL": "http://127.0.0.1:9/v1"},
    )
    assert result["trials"] >= 1
    assert result["failed"] == result["trials"], (
        f"every model call failed but only {result['failed']} of {result['trials']} "
        "trials are failed: the recipe hides failures"
    )


def test_raw_client_examples_carry_the_mock_scope_caveat() -> None:
    offenders = []
    for skill in SCANNED_SKILLS:
        for path in sorted((ROOT / "skills" / skill).glob("**/*.md")):
            text = path.read_text(encoding="utf-8")
            if "enable_mock_mode_for_quickstart" not in text or CAVEAT in text:
                continue
            for block in _iter_fenced_blocks(text.splitlines()):
                if block.language in {"python", "py"} and RAW_CLIENT_RE.search(block.text):
                    offenders.append(f"{path.relative_to(ROOT)}:{block.start_line}")
    assert not offenders, (
        "raw provider client in a file that teaches the mock dry-run, without the "
        f"'{CAVEAT}' caveat: " + ", ".join(offenders)
    )
