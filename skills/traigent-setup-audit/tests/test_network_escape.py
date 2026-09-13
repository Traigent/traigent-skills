"""The reviewer's escape harness, kept as a test.

A real TCP listener on the host loopback, one fixture project per escape route,
and the assertion that the listener receives ZERO connections. Five of these
routes reached a real socket in the first version while the card said
`network_guard: active`, so the harness — not the prose — is what the claim
rests on now.

The control test connects to the same listener from the test process and
requires it to count exactly one connection: without that, "zero connections"
would pass even if the listener were broken.
"""

from __future__ import annotations

import importlib
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS_DIR / "audit_project.py"
PROBE = SCRIPTS_DIR / "scorer_probe.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

ESCAPE_ROUTES = [
    "escape-ctypes",
    "escape-socketmod",
    "escape-reload",
    "escape-multiprocessing",
    "escape-subprocess",
]


def _load_audit_module():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("audit_project")


audit = _load_audit_module()


class Listener:
    """A loopback TCP listener that counts every accepted connection."""

    def __init__(self) -> None:
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("localhost", 0))
        self.server.listen(16)
        self.port = self.server.getsockname()[1]
        self.connections: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self.server.settimeout(0.25)
        while not self._stop.is_set():
            try:
                connection, _ = self.server.accept()
            except OSError:
                continue
            self.connections.append("connection")
            try:
                connection.settimeout(0.5)
                connection.recv(4096)
                connection.sendall(b"HTTP/1.1 204 No Content\r\n\r\n")
            except OSError:
                pass
            finally:
                connection.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)
        self.server.close()


@pytest.fixture()
def listener():
    item = Listener()
    try:
        yield item
    finally:
        item.close()


@pytest.fixture()
def probe_port(listener, monkeypatch):
    """Publish the listener port to every child process by inheritance.

    Set in this process rather than handed to `subprocess.run` as a copied
    environment: copying the whole environment into a variable is exactly the
    shape a credential-exfiltration scanner flags, and inheritance is simpler.
    """
    monkeypatch.setenv("TRAIGENT_AUDIT_PROBE_PORT", str(listener.port))
    return listener.port


def test_the_listener_counts_a_real_connection(listener) -> None:
    """Teeth for every zero-connection assertion below."""
    connection = socket.create_connection(("localhost", listener.port), timeout=5)
    connection.sendall(b"GET /control HTTP/1.0\r\n\r\n")
    connection.close()
    for _ in range(100):
        if listener.connections:
            break
        threading.Event().wait(0.05)
    assert len(listener.connections) == 1


# --------------------------------------------------------------------------
# through the whole audit
# --------------------------------------------------------------------------


def _run_audit(root: Path, out_dir: Path, *extra: str):
    report_path = out_dir / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--json",
            str(report_path),
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(report_path.read_text(encoding="utf-8")), completed.stdout


@pytest.mark.parametrize("route", ESCAPE_ROUTES)
def test_no_escape_route_reaches_the_listener_through_the_audit(
    route: str, listener, probe_port, tmp_path: Path
) -> None:
    report, card = _run_audit(FIXTURES / route, tmp_path)
    threading.Event().wait(0.5)
    assert listener.connections == [], f"{route} reached the listener"
    # And it is visible in the card why: either the route was classified
    # executing and never run, or it ran inside a namespace that reached nothing.
    kinds = {item["kind"] for item in report["scorers"]}
    assert kinds == {"executing"}, report["scorers"]
    assert "were not run" in card


@pytest.mark.parametrize("route", ESCAPE_ROUTES)
def test_an_escape_route_named_with_scorer_is_refused(
    route: str, listener, probe_port, tmp_path: Path
) -> None:
    """F2: an explicit --scorer is not permission to run arbitrary code."""
    report, card = _run_audit(
        FIXTURES / route, tmp_path, "--scorer", "scorer.py:score"
    )
    threading.Event().wait(0.5)
    assert listener.connections == [], f"{route} reached the listener via --scorer"
    assert report["scorer_probe"] is None
    assert report["scorer_selection_refused"]
    assert "was selected with --scorer and refused" in card
    assert report["areas"]["scorer"]["status"] == "attention"


def test_a_deterministic_scorer_named_with_scorer_still_runs(tmp_path: Path) -> None:
    """Teeth for the refusal above: --scorer is not simply ignored."""
    report, _ = _run_audit(
        FIXTURES / "healthy", tmp_path, "--scorer", "scorer.py:score"
    )
    assert report["scorer_selection_refused"] is None
    assert report["scorer_probe"]["ran"] is True


def test_a_scorer_not_in_the_inventory_is_classified_not_assumed(
    listener, probe_port, tmp_path: Path
) -> None:
    """A --scorer target the search never reached is read from its module."""
    report, _ = _run_audit(
        FIXTURES / "escape-subprocess",
        tmp_path,
        "--scorer",
        "scorer.py:not_a_function_that_exists",
    )
    assert listener.connections == []
    assert report["scorer_probe"] is None
    assert "refused" in (report["scorer_selection_refused"] or "")


# --------------------------------------------------------------------------
# the sandbox itself
# --------------------------------------------------------------------------


ISOLATION_LEVEL, ISOLATION_PREFIX = audit.detect_isolation()


@pytest.mark.skipif(
    not ISOLATION_PREFIX,
    reason="no network namespace backend preflighted on this machine",
)
@pytest.mark.parametrize("route", ESCAPE_ROUTES)
def test_the_sandbox_blocks_every_escape_route(
    route: str, listener, probe_port, tmp_path: Path
) -> None:
    """Drive the probe under the sandbox directly, bypassing the classifier.

    The classifier already refuses these routes, so without this test the
    zero-connection result would say nothing about the sandbox itself.
    """
    root = FIXTURES / route
    request = {
        "module": str(root / "scorer.py"),
        "root": str(root),
        "function": "score",
        "good": "a value",
        "partial": "a",
        "bad": "another value",
        "repeats": 1,
    }
    completed = subprocess.run(
        [*ISOLATION_PREFIX, sys.executable, str(PROBE), "--request-stdin"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    threading.Event().wait(0.5)
    assert listener.connections == [], (
        f"{route} reached the listener from inside {ISOLATION_LEVEL}: "
        f"{completed.stdout}\n{completed.stderr}"
    )


def test_the_card_reports_which_guard_level_was_in_force(tmp_path: Path) -> None:
    """Unconditional: whatever this machine supports, the card must name it."""
    report, card = _run_audit(FIXTURES / "healthy", tmp_path)
    level = report["network_guard"]
    assert level == ISOLATION_LEVEL
    assert level == audit.GUARD_PYTHON or level.startswith("isolated (")
    assert f"`network_guard: {level}`" in card
    assert report["network_guard_note"] in card
    # The claim in the header is never bare "no network".
    header = card.splitlines()[2]
    assert "network_guard:" in header
    if level == audit.GUARD_PYTHON:
        assert "ctypes" in header
    assert any(level in item or "python-level" in item for item in report["not_established"])


def test_the_audit_process_itself_still_holds_the_in_process_guard(
    tmp_path: Path,
) -> None:
    report, _ = _run_audit(FIXTURES / "healthy", tmp_path)
    assert report["audit_process_guard"] == "active"


def test_the_guard_allows_the_ssl_stack_to_import() -> None:
    """F8: the refusal is a class, so `class SSLSocket(socket)` still builds."""
    program = (
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
        "import scorer_probe\n"
        "scorer_probe.install_network_guard()\n"
        "import ssl, urllib.request, http.client, asyncio\n"
        "print('imports-ok')\n"
        "print(scorer_probe.verify_network_guard())\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "imports-ok" in completed.stdout
    assert "active" in completed.stdout
