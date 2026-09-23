"""Debugging mock-mode reference: scope "zero egress" to the Traigent backend.

Traigent/traigent-skills#355 (the debugging sibling). ``offline=True`` stops only
Traigent backend traffic, and mock mode intercepts only LiteLLM/LangChain calls.
``import litellm`` fetches LiteLLM's public pricing map over the network unless
``LITELLM_LOCAL_MODEL_COST_MAP=True`` is set before the import. The reference
promised "zero-egress" and "No network calls at all" without those limits.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOCK_MODE = ROOT / "skills" / "traigent-debugging" / "references" / "mock-mode.md"


def _text() -> str:
    return " ".join(MOCK_MODE.read_text(encoding="utf-8").split())


def test_no_unscoped_zero_egress_claims() -> None:
    text = _text()
    assert "zero-egress" not in text
    assert "No network calls at all" not in text
    assert "zero Traigent backend egress" in text


def test_reference_names_the_litellm_pricing_fetch_and_raw_clients() -> None:
    text = _text()
    assert "LITELLM_LOCAL_MODEL_COST_MAP=True" in text
    assert "pricing map" in text
    # The accurate interception claim stays, with its raw-client limit.
    assert "Raw `openai` and `anthropic` clients are **not** intercepted" in text


@pytest.mark.parametrize(("flag", "expect_egress"), [(None, True), ("True", False)])
def test_litellm_import_fetches_its_pricing_map_unless_the_flag_is_set(
    tmp_path: Path, flag: str | None, expect_egress: bool
) -> None:
    pytest.importorskip("litellm")
    script = tmp_path / "probe.py"
    script.write_text(
        textwrap.dedent(
            """
            import socket
            seen = []
            def _blocked(*args, **kwargs):
                seen.append(args[0] if args else None)
                raise OSError("blocked by probe")
            socket.getaddrinfo = _blocked
            socket.socket.connect = lambda self, addr: _blocked(addr)
            import litellm  # noqa: F401
            print("EGRESS=" + str(bool(seen)))
            """
        ),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != "LITELLM_LOCAL_MODEL_COST_MAP" and not k.endswith("_API_KEY")}
    if flag is not None:
        env["LITELLM_LOCAL_MODEL_COST_MAP"] = flag
    completed = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert f"EGRESS={expect_egress}" in completed.stdout, completed.stdout + completed.stderr
