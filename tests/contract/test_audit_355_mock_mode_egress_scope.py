"""Debugging mock-mode reference: scope "zero egress" to the Traigent backend.

Traigent/traigent-skills#355 (the debugging sibling). ``offline=True`` stops only
Traigent backend traffic, and mock mode intercepts only LiteLLM/LangChain calls.
``import litellm`` fetches LiteLLM's public pricing map over the network unless
``LITELLM_LOCAL_MODEL_COST_MAP=True`` is set before the import. The reference
promised "zero-egress" and "No network calls at all" without those limits.
"""

from __future__ import annotations

import json
import shutil
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
import sys
lookups = []
connects = []
imported = False
class ProbeNetworkAttempt(BaseException):
    pass
def _refuse_dns(host, *args, **kwargs):
    lookups.append(str(host))
    raise ProbeNetworkAttempt()
def _refuse_connect(self, address=None, *args, **kwargs):
    connects.append(str(address))
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
# Newer LiteLLM fetches through a native client that never touches Python's
# socket module, so the patches above cannot see it. LiteLLM's own record of the
# load is the second witness. It is read only when litellm is already loaded, so
# unrelated probes never import it. An absent accessor (older litellm) means no
# record; any other failure reading it must fail the probe, not hide evidence.
source_info = None
source_info_unavailable = None
if "litellm" in sys.modules:
    import importlib
    import importlib.util
    _mod = "litellm.litellm_core_utils.get_model_cost_map"
    if importlib.util.find_spec(_mod) is None:
        source_info_unavailable = "module absent in this litellm"
    else:
        _accessor = getattr(importlib.import_module(_mod), "get_model_cost_map_source_info", None)
        if _accessor is None:
            source_info_unavailable = "accessor missing on existing module"
        else:
            source_info = dict(_accessor())
print("EGRESS_JSON=" + json.dumps(
    {"lookups": lookups, "connects": connects, "imported": imported,
     "source_info": source_info,
     "source_info_unavailable": source_info_unavailable}, default=str
), flush=True)
"""


def _import_probe(import_statement: str) -> str:
    assert IMPORT_PROBE.count("IMPORT_STATEMENT") == 1
    return IMPORT_PROBE.replace("IMPORT_STATEMENT", import_statement)


_ISOLATION_BACKENDS: tuple[list[str], ...] = (
    ["unshare", "-rn"],
    ["bwrap", "--unshare-net", "--unshare-user-try", "--dev-bind", "/", "/"],
)


def isolated_command(command: list[str]) -> list[str]:
    """Prefix ``command`` so it runs in a network namespace with no interfaces.

    The probe must not rely on patching Python's socket module alone: LiteLLM's
    native client bypasses it. A namespace makes any fetch fail without reaching
    the internet. If no backend works the test FAILS; it never skips or passes
    without isolation (GitHub-hosted runners may restrict unprivileged user
    namespaces; install bubblewrap or relax the restriction there).
    """
    tried: list[str] = []
    for prefix in _ISOLATION_BACKENDS:
        if shutil.which(prefix[0]) is None:
            tried.append(f"{prefix[0]}: not installed")
            continue
        check = subprocess.run(
            [*prefix, "true"], capture_output=True, text=True, timeout=30, check=False
        )
        if check.returncode == 0:
            return [*prefix, *command]
        tried.append(f"{prefix[0]}: rc={check.returncode} {check.stderr.strip()}")
    pytest.fail(
        "no network-isolation backend is usable, so the egress probe cannot run "
        "safely or reliably; refusing to skip. Tried: " + "; ".join(tried)
    )


def _remote_fetch_attempted(source_info: dict | None) -> bool:
    if not source_info or source_info.get("is_env_forced"):
        return False
    return source_info.get("source") == "remote" or bool(source_info.get("url"))


def _probe_lookups(completed: subprocess.CompletedProcess[str], expect_egress: bool) -> list[str]:
    """Return the egress evidence the probe recorded (empty when none)."""
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    lines = [line for line in completed.stdout.splitlines() if line.startswith("EGRESS_JSON=")]
    assert len(lines) == 1, output
    ledger = json.loads(lines[0].removeprefix("EGRESS_JSON="))
    assert set(ledger) == {"lookups", "connects", "imported", "source_info",
                         "source_info_unavailable"}, output
    assert isinstance(ledger["lookups"], list), output
    assert all(isinstance(host, str) and host for host in ledger["lookups"]), output
    assert isinstance(ledger["connects"], list), output
    assert isinstance(ledger["imported"], bool), output
    source_info = ledger["source_info"]
    assert ledger["source_info_unavailable"] is None or source_info is None, output
    sockets = [*ledger["lookups"], *(f"connect {c}" for c in ledger["connects"])]
    remote = _remote_fetch_attempted(source_info)
    if expect_egress:
        # LiteLLM's own record is authoritative when present; an unrelated
        # Python lookup must not override a forced-local or bundled-only load.
        evidence = (
            [f"litellm tried remote: {source_info}"] if remote else []
        ) if source_info is not None else sockets
        assert evidence, output
    else:
        # Clean means every witness is clean and the import really finished.
        evidence = []
        assert not remote and not sockets, output
        assert ledger["imported"] is True, output
        if source_info is not None:
            assert source_info.get("is_env_forced") is True, output
    return evidence


def run_probe(script_args: list[str], **kwargs):
    return subprocess.run(
        isolated_command(script_args), text=True, capture_output=True,
        check=False, **kwargs,
    )


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
    env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    if flag is not None:
        env["LITELLM_LOCAL_MODEL_COST_MAP"] = flag
    completed = run_probe([sys.executable, str(script)], cwd=tmp_path, env=env, timeout=120)
    _probe_lookups(completed, expect_egress)
