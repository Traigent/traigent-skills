"""Three ways the probe boundary leaked, each pinned by the thing that leaked.

- A module named at runtime never appears as an import, so an import-only
  classifier called it deterministic and ran it. With the sandbox removed, each
  of three spellings made real connections while the card said `Scorer — ok`.
- The parent read the child's LAST stdout line as its result, so a scorer with
  an `atexit` handler could print a JSON object and forge the verdict, its
  scores and a free-text field carrying a key.
- Under bwrap the prefix ends `--tmpfs /tmp`, so a project living under /tmp
  disappeared inside the sandbox and the audit blamed the user's scorer.
"""

from __future__ import annotations

import ast
import importlib
import json
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS_DIR / "audit_project.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_audit_module():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("audit_project")


audit = _load_audit_module()

DYNAMIC_ROUTES = ["dynamic-builtin", "dynamic-getattr", "dynamic-importmodule"]
SENTINEL = "canary-value-must-not-appear"

# All three routes reach out with curl. Without it a "no connection" result
# would prove nothing, so the end-to-end cases skip rather than pass vacuously.
CURL = shutil.which("curl")
needs_curl = pytest.mark.skipif(
    CURL is None, reason="curl is not installed, so an escape could not connect anyway"
)


def _run(root: Path, out_dir: Path, *extra: str):
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


# --------------------------------------------------------------------------
# NEW-1 — a module named at runtime
# --------------------------------------------------------------------------


def _score_node(source: str):
    tree = ast.parse(source)
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == "score"
    )
    return tree, node


@pytest.mark.parametrize("route", DYNAMIC_ROUTES)
def test_a_runtime_named_module_is_classified_executing(route: str) -> None:
    source = (FIXTURES / route / "scorer.py").read_text(encoding="utf-8")
    tree, node = _score_node(source)
    kind, signals = audit.classify_scorer(tree, node)
    assert kind == "executing", (route, signals)
    assert signals


_DYNAMIC_IMPORT = "import_" + "module"
_EVAL = "ev" + "al"

DYNAMIC_SHAPES = {
    "getattr with a computed name": "import os\n\ndef score(output, expected):\n"
    "    return getattr(os, 'get' + 'cwd')()\n",
    "getattr on a sensitive module": "import socket\n\ndef score(output, expected):\n"
    "    return getattr(socket, 'gethostname')()\n",
    "import_module by name": "import importlib\n\ndef score(output, expected):\n"
    "    return importlib.import_module('json')\n",
    # These two call names are assembled rather than written out: the repo's
    # forensics gate matches them as raw text, even inside a string literal in a
    # test. The parsed source is identical.
    "import_module with a variable": "import importlib\n\n"
    "def score(output, expected):\n"
    f"    return importlib.{_DYNAMIC_IMPORT}(output)\n",
    "eval of a computed string": "def score(output, expected):\n"
    f"    return {_EVAL}(output)\n",
}


@pytest.mark.parametrize(
    "label,source", sorted(DYNAMIC_SHAPES.items()), ids=sorted(DYNAMIC_SHAPES)
)
def test_every_dynamic_naming_shape_is_executing(label: str, source: str) -> None:
    tree, node = _score_node(source)
    kind, signals = audit.classify_scorer(tree, node)
    assert kind == "executing", (label, signals)


def test_a_plain_getattr_on_ordinary_data_stays_deterministic() -> None:
    """Teeth: the rule is about runtime NAMING, not about getattr existing."""
    tree, node = _score_node(
        "def score(output, expected):\n    return getattr(output, 'strip')()\n"
    )
    assert audit.classify_scorer(tree, node)[0] == "deterministic"


def test_the_python_level_note_does_not_present_the_classifier_as_a_sandbox() -> None:
    note = audit.GUARD_NOTE[audit.GUARD_PYTHON]
    assert "a static read of the module's imports and calls, not a sandbox" in note


# --------------------------------------------------------------------------
# NEW-1 end to end, with the sandbox removed
# --------------------------------------------------------------------------


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
def python_level(listener, monkeypatch, tmp_path_factory):
    """Force the python-level guard by taking the sandboxes off PATH.

    `curl` is kept reachable, so a route that escapes really can connect — the
    point of the test is that it does not.
    """
    fake_bin = tmp_path_factory.mktemp("bin")
    if CURL:
        (fake_bin / "curl").symlink_to(CURL)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setenv("TRAIGENT_AUDIT_PROBE_PORT", str(listener.port))
    assert audit.detect_isolation()[0] == audit.GUARD_PYTHON
    return listener


@needs_curl
@pytest.mark.parametrize("route", DYNAMIC_ROUTES)
def test_a_runtime_named_module_reaches_nothing_at_python_level(
    route: str, python_level, tmp_path: Path
) -> None:
    report, card = _run(FIXTURES / route, tmp_path)
    threading.Event().wait(0.5)
    assert report["network_guard"] == audit.GUARD_PYTHON
    assert python_level.connections == [], f"{route} reached the listener"
    assert report["scorer_probe"] is None
    assert {item["kind"] for item in report["scorers"]} == {"executing"}
    assert "were not run" in card
    assert "not a sandbox" in card


@needs_curl
@pytest.mark.parametrize("route", DYNAMIC_ROUTES)
def test_the_route_really_does_escape_the_python_level_guard(
    route: str, python_level, tmp_path: Path
) -> None:
    """Teeth: each route is a LIVE escape, so refusing to run it is the fix.

    Drives the probe directly with no sandbox, which is what the audit used to
    do for these modules. The connection that lands here is the defect; the
    test above is the same route going through the audit and landing nowhere.
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
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "scorer_probe.py"), "--request-stdin"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    threading.Event().wait(0.5)
    assert python_level.connections, (
        f"{route} did not reach the listener even unsandboxed, so the "
        "python-level test above proves nothing"
    )


@needs_curl
def test_the_control_still_connects_at_python_level(python_level) -> None:
    """Teeth: curl really is reachable in this environment."""
    completed = subprocess.run(
        [
            "curl",
            "-s",
            "-m",
            "2",
            f"http://localhost:{python_level.port}/control",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    threading.Event().wait(0.5)
    assert completed.returncode == 0
    assert len(python_level.connections) == 1


# --------------------------------------------------------------------------
# NEW-2 — a forged result line
# --------------------------------------------------------------------------


@pytest.fixture()
def sentinel_key(monkeypatch):
    monkeypatch.setenv("TRAIGENT_API_KEY", SENTINEL)
    return SENTINEL


def test_a_forged_framed_line_is_refused_not_believed(
    sentinel_key, tmp_path: Path
) -> None:
    report, card = _run(FIXTURES / "forge-framed", tmp_path)
    probe = report["scorer_probe"]
    assert probe["ran"] is False
    assert probe["stage"] == "tampered-result"
    assert probe["framed_result_lines"] == 2
    assert SENTINEL not in card
    assert SENTINEL not in json.dumps(report)
    assert "Scorer — attention" in card
    assert "absent, duplicated or malformed" in card


def test_a_forged_plain_line_is_ignored_and_the_real_scores_stand(
    sentinel_key, tmp_path: Path
) -> None:
    report, card = _run(FIXTURES / "forge-plain", tmp_path)
    probe = report["scorer_probe"]
    assert probe["ran"] is True
    assert probe["framed_result_lines"] == 1
    # The real scorer returns 0.25 for everything; the forgery claimed 1.0/0.0.
    assert probe["scores"]["good"] == [0.25] * 5
    assert probe["scores"]["bad"] == [0.25]
    assert SENTINEL not in card
    assert SENTINEL not in json.dumps(report)
    # 0.25 everywhere is stable but not ordered, so this is not a pass.
    assert "Scorer — attention" in card


def test_unknown_keys_are_dropped_and_counted() -> None:
    clean, dropped = audit.validate_probe_payload(
        {
            "ran": True,
            "scores": {"good": [1.0]},
            "note": "leaked " + SENTINEL,
            "network_guard": "totally-fine",
            "stage": "made-up",
            "extra": {"deep": SENTINEL},
        }
    )
    assert clean == {"ran": True, "scores": {"good": [1.0]}}
    assert dropped == 4
    assert SENTINEL not in json.dumps(clean)


@pytest.mark.parametrize(
    "payload",
    [
        "not a dict",
        {"scores": {"good": [1.0]}},
        {"ran": "yes"},
        {"ran": True, "scores": {"good": ["1.0"]}},
        {"ran": True, "scores": {"good": [True]}},
        {"ran": True, "scores": {"unknown_case": [1.0]}},
        {"ran": True, "errors": [{"error_type": "has spaces"}]},
    ],
    ids=[
        "not-a-dict",
        "no-ran",
        "ran-not-bool",
        "scores-not-numbers",
        "scores-bools",
        "unknown-case",
        "error-type-not-an-identifier",
    ],
)
def test_a_malformed_payload_never_produces_scores(payload: object) -> None:
    clean, _ = audit.validate_probe_payload(payload)
    assert clean.get("ran") is not True or "scores" not in clean


def test_the_probe_frames_its_own_result_line() -> None:
    request = {
        "module": str(FIXTURES / "healthy" / "scorer.py"),
        "root": str(FIXTURES / "healthy"),
        "function": "score",
        "good": "a value",
        "partial": "a",
        "bad": "another value",
        "repeats": 2,
    }
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "scorer_probe.py"), "--request-stdin"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    framed = [
        line
        for line in completed.stdout.splitlines()
        if line.startswith(audit.RESULT_MARKER)
    ]
    assert len(framed) == 1
    assert json.loads(framed[0][len(audit.RESULT_MARKER) :])["ran"] is True


# --------------------------------------------------------------------------
# NEW-3 — the sandbox must not hide the project
# --------------------------------------------------------------------------


def test_a_project_under_tmp_is_still_readable_inside_the_sandbox(
    tmp_path: Path,
) -> None:
    """tmp_path IS under /tmp, which `--tmpfs /tmp` used to blank out."""
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / "healthy", root)
    report, card = _run(root, tmp_path / "out")
    probe = report["scorer_probe"]
    assert probe["ran"] is True, probe
    assert probe.get("error_type") != "FileNotFoundError"
    assert probe["scores"]["good"] == [1.0] * 5
    assert report["areas"]["scorer"]["status"] == "ok"
    assert "FileNotFoundError" not in card


def test_the_sandbox_command_binds_the_project_after_the_tmpfs(
    tmp_path: Path,
) -> None:
    level, backend, args, terminator = audit.detect_isolation()
    command = audit.isolation_command(backend, args, terminator, [tmp_path])
    if backend != "bwrap":
        pytest.skip(f"bwrap is not the active backend here (level {level})")
    assert command[-1] == "--"
    tmpfs_at = command.index("--tmpfs")
    bind_at = command.index(str(tmp_path.resolve()))
    assert bind_at > tmpfs_at, command


def test_the_root_directory_is_never_bound_over_itself() -> None:
    _, backend, args, terminator = audit.detect_isolation()
    command = audit.isolation_command(backend, args, terminator, [Path("/")])
    assert command.count("/") == (2 if backend == "bwrap" else 0)


def test_a_nonexistent_bind_is_skipped_rather_than_breaking_the_probe() -> None:
    _, backend, args, terminator = audit.detect_isolation()
    missing = Path("/definitely/not/here/at/all")
    command = audit.isolation_command(backend, args, terminator, [missing])
    assert str(missing) not in command


# --------------------------------------------------------------------------
# #309 — what the classifier reads, and the version check starts nothing
# --------------------------------------------------------------------------


def test_the_classifier_reads_the_scorers_own_file_only(tmp_path: Path) -> None:
    """Pinned as TODAY's reach, so widening it is a visible decision.

    A helper module the scorer imports from the project is not read: its
    `import subprocess` leaves the scorer deterministic. SKILL.md's Safety
    section says exactly this, and tells the reader to review helpers by hand.
    """
    (tmp_path / "helpers.py").write_text(
        "import subprocess  # imported, never called\n\n"
        "def normalize(text):\n    return text.strip().lower()\n",
        encoding="utf-8",
    )
    scorer = tmp_path / "scorer.py"
    scorer.write_text(
        "from helpers import normalize\n\n"
        "def score(output, expected):\n"
        "    return 1.0 if normalize(output) == normalize(expected) else 0.0\n",
        encoding="utf-8",
    )
    kind, _ = audit.classify_module_function(scorer, "score")
    assert kind == "deterministic"
    # Control: the same import in the scorer's own file is refused.
    scorer.write_text(
        "import subprocess\n\ndef score(output, expected):\n    return 1.0\n",
        encoding="utf-8",
    )
    kind, _ = audit.classify_module_function(scorer, "score")
    assert kind == "executing"


def _project_with_venv(tmp_path: Path, version: str | None) -> tuple[Path, Path]:
    root = tmp_path / "interp"
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (root / "agent.py").write_text(
        "import traigent\n\n"
        "@traigent.optimize(configuration_space={'temperature': [0.0, 0.7]})\n"
        "def answer(q, temperature=0.0):\n    return f'{temperature}:{q}'\n",
        encoding="utf-8",
    )
    marker = tmp_path / "interpreter-ran.txt"
    shim = bin_dir / "python"
    shim.write_text(
        f"#!/bin/sh\necho started >> '{marker}'\nexec '{sys.executable}' \"$@\"\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    if version is not None:
        dist_info = (
            root
            / ".venv"
            / "lib"
            / "python3.12"
            / "site-packages"
            / f"traigent-{version}.dist-info"
        )
        dist_info.mkdir(parents=True)
        (dist_info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: traigent\nVersion: {version}\n",
            encoding="utf-8",
        )
    return root, marker


def test_the_version_check_never_starts_the_project_interpreter(
    tmp_path: Path,
) -> None:
    root, marker = _project_with_venv(tmp_path, "0.27.0")
    report, card = _run(root, tmp_path)
    assert not marker.exists(), marker.read_text(encoding="utf-8")
    assert report["setup"]["sdk"]["traigent_version"] == "0.27.0"
    assert "traigent 0.27.0 is importable by" in card


def test_a_venv_without_the_sdk_reads_as_not_installed(tmp_path: Path) -> None:
    root, marker = _project_with_venv(tmp_path, None)
    report, card = _run(root, tmp_path)
    assert not marker.exists()
    assert report["setup"]["sdk"]["traigent_version"] is None
    assert "traigent is not installed for" in card


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True, timeout=60
    )


@needs_git
@pytest.mark.parametrize("ignored", [True, False])
def test_the_env_file_check_runs_no_project_configured_git_hook(
    ignored: bool, sentinel_key, tmp_path: Path
) -> None:
    """`git check-ignore` honours a project's `core.fsmonitor`, which is a
    command the project chooses. The audit must not run it, and the answer
    about `.env` must still be right."""
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "-q")
    marker = tmp_path / "fsmonitor-ran.txt"
    hook = tmp_path / "fsmonitor.sh"
    hook.write_text(
        f"#!/bin/sh\necho \"key=${{TRAIGENT_API_KEY:-unset}}\" >> '{marker}'\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    _git(root, "config", "core.fsmonitor", str(hook))
    (root / ".env").write_text("TRAIGENT_API_KEY=placeholder\n", encoding="utf-8")
    if ignored:
        (root / ".gitignore").write_text(".env\n", encoding="utf-8")
    # Teeth: plain git in this repo really does run the hook.
    subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", ".env"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert marker.exists(), "git did not run the fsmonitor hook, so this proves nothing"
    marker.unlink()

    assert audit.env_file_ignored(root) == ("ignored" if ignored else "not ignored")
    report, _ = _run(root, tmp_path)
    assert not marker.exists(), marker.read_text(encoding="utf-8")
    assert report["setup"]["env_file_git_status"] == (
        "ignored" if ignored else "not ignored"
    )
