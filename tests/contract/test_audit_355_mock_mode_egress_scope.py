"""Debugging mock-mode reference: scope "zero egress" to the Traigent backend.

Traigent/traigent-skills#355 (the debugging sibling). ``offline=True`` stops only
Traigent backend traffic, and mock mode intercepts only LiteLLM/LangChain calls.
``import litellm`` fetches LiteLLM's public pricing map over the network unless
``LITELLM_LOCAL_MODEL_COST_MAP=True`` is set before the import. The reference
promised "zero-egress" and "No network calls at all" without those limits.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from .test_runnable_snippets import _offline_mock_env

ROOT = Path(__file__).resolve().parents[2]
MOCK_MODE = ROOT / "skills" / "traigent-debugging" / "references" / "mock-mode.md"

IMPORT_PROBE = """
import json
import socket
lookups = []
imported = False
class ProbeNetworkAttempt(BaseException):
    pass
def _refuse_dns(host, *args, **kwargs):
    lookups.append(str(host))
    raise ProbeNetworkAttempt()
def _refuse_connect(*args, **kwargs):
    raise ProbeNetworkAttempt()
socket.getaddrinfo = _refuse_dns
socket.socket.connect = _refuse_connect
socket.socket.connect_ex = _refuse_connect
try:
    IMPORT_STATEMENT
except ProbeNetworkAttempt:
    pass
else:
    imported = True
print("EGRESS_JSON=" + json.dumps({"lookups": lookups, "imported": imported}), flush=True)
"""


def _import_probe(import_statement: str) -> str:
    assert IMPORT_PROBE.count("IMPORT_STATEMENT") == 1
    return IMPORT_PROBE.replace("IMPORT_STATEMENT", import_statement)


def _probe_lookups(completed: subprocess.CompletedProcess[str], expect_egress: bool) -> list[str]:
    """Only the probe's deliberate network interruption permits an incomplete import."""
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    lines = [line for line in completed.stdout.splitlines() if line.startswith("EGRESS_JSON=")]
    assert len(lines) == 1, output
    ledger = json.loads(lines[0].removeprefix("EGRESS_JSON="))
    assert set(ledger) == {"lookups", "imported"}, output
    assert isinstance(ledger["lookups"], list), output
    assert all(isinstance(host, str) and host for host in ledger["lookups"]), output
    assert isinstance(ledger["imported"], bool), output
    assert bool(ledger["lookups"]) is expect_egress, output
    assert ledger["imported"] is not expect_egress, output
    return ledger["lookups"]


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
    script = tmp_path / "probe.py"
    script.write_text(_import_probe("import litellm"), encoding="utf-8")
    env = _offline_mock_env()
    env.pop("LITELLM_LOCAL_MODEL_COST_MAP")
    if flag is not None:
        env["LITELLM_LOCAL_MODEL_COST_MAP"] = flag
    completed = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=120, check=False,
    )
    _probe_lookups(completed, expect_egress)
