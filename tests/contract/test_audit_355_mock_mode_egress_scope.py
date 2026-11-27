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
    connects.append(str(address[0] if isinstance(address, (tuple, list)) and address else address))
    raise ProbeNetworkAttempt()
class _StartedFinder:
    # Records that litellm was first requested; never loads anything. A failed
    # import is removed from sys.modules, so this is the only lasting witness.
    def find_spec(self, name, path=None, target=None):
        # Only a real import counts; importlib.util.find_spec("litellm") is an
        # availability check and never goes through _find_and_load.
        if name == "litellm":
            frame = sys._getframe(1)
            while frame is not None:
                if frame.f_code.co_name == "_find_and_load" and "importlib" in frame.f_code.co_filename:
                    litellm_started.append(True)
                    break
                frame = frame.f_back
        return None
litellm_started = []
sys.meta_path.insert(0, _StartedFinder())
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
    _mod = "litellm.litellm_core_utils.get_model_cost_map"
    _absent = {"litellm.litellm_core_utils", _mod}
    try:
        _module = importlib.import_module(_mod)
    except ModuleNotFoundError as _exc:
        if _exc.name not in _absent:
            raise
        source_info_unavailable = "module absent in this litellm"
    else:
        try:
            _accessor = getattr(_module, "get_model_cost_map_source_info")
        except AttributeError:
            source_info_unavailable = "accessor missing on existing module"
        else:
            if not callable(_accessor):
                raise TypeError("get_model_cost_map_source_info is not callable")
            source_info = dict(_accessor())
import os
from urllib.parse import urlparse
pricing_host = urlparse(
    os.environ.get("LITELLM_MODEL_COST_MAP_URL") or "https://raw.githubusercontent.com/"
).hostname
print("EGRESS_JSON=" + json.dumps(
    {"lookups": lookups, "connects": connects, "imported": imported,
     "source_info": source_info,
     "source_info_unavailable": source_info_unavailable,
     "litellm_import_started": bool(litellm_started), "pricing_host": pricing_host}, default=str
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
                         "source_info_unavailable",
                         "litellm_import_started", "pricing_host"}, output
    assert isinstance(ledger["lookups"], list), output
    assert all(isinstance(host, str) and host for host in ledger["lookups"]), output
    assert isinstance(ledger["connects"], list), output
    assert isinstance(ledger["imported"], bool), output
    source_info = ledger["source_info"]
    assert ledger["source_info_unavailable"] is None or source_info is None, output
    def norm(name: str) -> str:
        name = name.lower()
        return name[:-1] if name.endswith(".") else name

    host = norm(ledger["pricing_host"] or "")
    sockets = [*ledger["lookups"], *ledger["connects"]]
    remote = _remote_fetch_attempted(source_info)
    if expect_egress:
        if source_info is not None:
            # LiteLLM's own record is authoritative when present.
            evidence = [f"litellm tried remote: {source_info}"] if remote else []
        else:
            # No record: socket events count only if the litellm import was
            # started (a failed import leaves no module behind) and the
            # destination is exactly the pricing-map host.
            evidence = (
                [e for e in sockets if host and norm(e) == host]
                if ledger["litellm_import_started"] else []
            )
        assert evidence, output
    else:
        # Clean means every witness is clean and the import really finished.
        evidence = []
        if source_info is not None:
            assert not (source_info.get("source") == "remote" or source_info.get("url")), (
                "contradictory record (remote source or url): " + output
            )
            assert source_info.get("is_env_forced") is True, output
        assert not sockets, output
        assert ledger["imported"] is True, output
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
