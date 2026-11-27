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
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from .test_runnable_snippets import _offline_mock_env

COST_MAP_PATH = "/cost-map.json"
ROOT = Path(__file__).resolve().parents[2]
MOCK_MODE = ROOT / "skills" / "traigent-debugging" / "references" / "mock-mode.md"

IMPORT_PROBE = """
import json
import socket
lookups = []
imported = False
class ProbeNetworkAttempt(BaseException):
    pass
_real_getaddrinfo = socket.getaddrinfo
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
def _is_loopback(host):
    return str(host) == "127.0.0.1"
def _refuse_dns(host, *args, **kwargs):
    if _is_loopback(host):
        return _real_getaddrinfo(host, *args, **kwargs)
    lookups.append(str(host))
    raise ProbeNetworkAttempt()
def _refuse_connect(self, address, *args, **kwargs):
    if isinstance(address, tuple) and _is_loopback(address[0]):
        return _real_connect(self, address, *args, **kwargs)
    raise ProbeNetworkAttempt()
def _refuse_connect_ex(self, address, *args, **kwargs):
    if isinstance(address, tuple) and _is_loopback(address[0]):
        return _real_connect_ex(self, address, *args, **kwargs)
    raise ProbeNetworkAttempt()
socket.getaddrinfo = _refuse_dns
socket.socket.connect = _refuse_connect
socket.socket.connect_ex = _refuse_connect_ex
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


@contextmanager
def _cost_map_listener() -> Iterator[tuple[str, list[str]]]:
    """Loopback stand-in for LiteLLM's pricing-map URL; yields (url, request paths).

    litellm 1.111.0 moved the pricing-map download into a native extension, which
    resolves and connects below Python's ``socket`` module, so the in-process spy
    cannot see it (the fetch still happens at import). Pointing
    ``LITELLM_MODEL_COST_MAP_URL`` at this listener observes the attempt on every
    litellm version without anything leaving the machine.
    """
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            hits.append(self.path)
            self.send_error(404)

        def log_message(self, *args: object) -> None:
            pass

    class BoundedServer(HTTPServer):
        def get_request(self):  # type: ignore[no-untyped-def]
            conn, addr = super().get_request()
            # An incomplete request must not wedge serve_forever()/shutdown().
            conn.settimeout(5)
            return conn, addr

    # Port 0: the OS picks a free port; the URL is built from server_port.
    server = BoundedServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}{COST_MAP_PATH}", hits
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _probe_lookups(
    completed: subprocess.CompletedProcess[str],
    expect_egress: bool,
    native_hits: list[str] | None = None,
) -> list[str]:
    """Only the probe's deliberate network interruption permits an incomplete import.

    ``native_hits`` are request paths a ``_cost_map_listener`` saw. Loopback
    traffic is let through the probe's socket spy so that every litellm version,
    Python-level or native, can reach the listener; any other host is refused and
    recorded. When ``native_hits`` is given and egress is expected, the listener
    must have seen the pricing-map path.
    """
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    lines = [line for line in completed.stdout.splitlines() if line.startswith("EGRESS_JSON=")]
    assert len(lines) == 1, output
    ledger = json.loads(lines[0].removeprefix("EGRESS_JSON="))
    assert set(ledger) == {"lookups", "imported"}, output
    assert isinstance(ledger["lookups"], list), output
    assert all(isinstance(host, str) and host for host in ledger["lookups"]), output
    assert isinstance(ledger["imported"], bool), output
    native = list(native_hits or [])
    if native_hits is not None and expect_egress:
        # The positive control must prove the pricing-map fetch itself: a request
        # for the configured listener path, not merely any unrelated DNS lookup.
        assert COST_MAP_PATH in native, (
            f"no pricing-map request reached the loopback listener: {native}\n{output}"
        )
    assert bool(ledger["lookups"] or native) is expect_egress, output
    assert ledger["imported"] is not bool(ledger["lookups"]), output
    return ledger["lookups"] + native


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
    with _cost_map_listener() as (url, hits):
        env["LITELLM_MODEL_COST_MAP_URL"] = url
        completed = subprocess.run(
            [sys.executable, str(script)], cwd=tmp_path, env=env, text=True,
            capture_output=True, timeout=120, check=False,
        )
    _probe_lookups(completed, expect_egress, hits)
