"""Evidence the audit reports beyond the four areas.

- past-run evidence under `.traigent/*/metadata.json` is detected by presence
  only, never read, never followed through a symlink;
- undeclared tunable-looking literals are named as candidates, never valued;
- a partial scan (a cap, an unparsed or unreadable file) sets `scan_state` and
  exits 1, while a complete scan that found gaps still exits 0;
- a symlink that leaves `--root` is skipped without being read;
- the audit process itself opens no socket (a tripwire in the parent).
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
SCRIPT = SCRIPTS_DIR / "audit_project.py"
FIXTURES = TESTS_DIR / "fixtures"
CANARY = "canary-value-must-not-appear"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
audit = importlib.import_module("audit_project")


def _audit(root: Path, out_dir: Path, *extra: str, env: dict | None = None):
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--json", str(report_path),
         *extra],
        capture_output=True, text=True, timeout=300, check=False, env=env,
    )
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
    return completed, report


def _audit_with_caps(root: Path, out_dir: Path, **caps: int):
    """Run `main` in a child with module caps lowered.

    A child, never `audit.main(...)` here: `main` installs the network guard in
    its own process, which would break every later test in this pytest process.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.json"
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
        "import audit_project as a\n"
        f"for name, value in {caps!r}.items():\n"
        "    setattr(a, name, value)\n"
        f"sys.exit(a.main(['--root', {str(root)!r}, '--json', {str(report_path)!r}]))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=300,
        check=False,
    )
    return completed, json.loads(report_path.read_text(encoding="utf-8"))


def _healthy(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / "healthy", root)
    return root


# --------------------------------------------------------------------------
# past-run evidence
# --------------------------------------------------------------------------


def test_no_past_run_artifacts_reads_not_evaluated(tmp_path: Path) -> None:
    done, report = _audit(_healthy(tmp_path), tmp_path / "out")
    assert done.returncode == 0, done.stderr
    assert report["evaluation"]["state"] == "not_evaluated"
    assert report["evaluation"]["artifacts"] == 0
    assert "Evaluation: not evaluated" in done.stdout


def test_past_run_artifacts_are_counted_but_never_read(tmp_path: Path) -> None:
    root = _healthy(tmp_path)
    for name in ("run-a", "run-b"):
        run = root / ".traigent" / name
        run.mkdir(parents=True)
        (run / "metadata.json").write_text(
            json.dumps({"best_score": 0.99, "note": CANARY}), encoding="utf-8"
        )
    done, report = _audit(root, tmp_path / "out")
    assert done.returncode == 0, done.stderr
    evaluation = report["evaluation"]
    assert evaluation["state"] == "unverified_past_run_evidence"
    assert evaluation["artifacts"] == 2
    assert "unverified past-run evidence (2 artifacts" in done.stdout
    blob = done.stdout + json.dumps(report)
    assert CANARY not in blob and "0.99" not in blob


def test_a_symlinked_artifact_is_not_followed(tmp_path: Path) -> None:
    root = _healthy(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "metadata.json").write_text("{}", encoding="utf-8")
    (root / ".traigent").mkdir()
    (root / ".traigent" / "linked-dir").symlink_to(outside, target_is_directory=True)
    real = root / ".traigent" / "linked-file"
    real.mkdir()
    (real / "metadata.json").symlink_to(outside / "metadata.json")
    done, report = _audit(root, tmp_path / "out")
    assert report["evaluation"]["state"] == "not_evaluated", report["evaluation"]


def test_a_symlinked_traigent_directory_is_not_followed(tmp_path: Path) -> None:
    root = _healthy(tmp_path)
    outside = tmp_path / "elsewhere" / "run"
    outside.mkdir(parents=True)
    (outside / "metadata.json").write_text("{}", encoding="utf-8")
    (root / ".traigent").symlink_to(outside.parent, target_is_directory=True)
    _, report = _audit(root, tmp_path / "out")
    assert report["evaluation"]["state"] == "not_evaluated"


# --------------------------------------------------------------------------
# candidate tunables
# --------------------------------------------------------------------------

CANDIDATE_AGENT = '''\
import traigent


@traigent.optimize(configuration_space={"temperature": [0.0, 0.5]})
def answer(question, temperature):
    reply = client.chat(model="secret-model-name", temperature=temperature,
                        max_tokens=512, top_p=0.9)
    other = helper(temperature=0.123)
    return reply
'''


def test_undeclared_literals_are_candidates_without_values(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "agent.py").write_text(CANDIDATE_AGENT, encoding="utf-8")
    done, report = _audit(root, tmp_path / "out")
    entry = report["entry_points"][0]
    found = {(item["name"], item["file"], item["line"]) for item in entry["candidate_tunables"]}
    # `temperature` is declared, so only the undeclared names are candidates,
    # and the declared one is not repeated even where a literal sets it.
    assert found == {
        ("model", "agent.py", 6),
        ("max_tokens", "agent.py", 7),
        ("top_p", "agent.py", 7),
    }
    assert [knob["name"] for knob in entry["knobs"]] == ["temperature"]
    assert "candidate, not declared: `model`" in done.stdout
    blob = done.stdout + json.dumps(report)
    for value in ("secret-model-name", "512", "0.9", "0.123"):
        assert value not in blob, value


def test_a_variable_or_decorator_keyword_is_not_a_candidate() -> None:
    source = (
        "import traigent\n"
        "@traigent.optimize(configuration_space={}, model='x')\n"
        "def f(m):\n"
        "    return call(model=m, temperature=get_t())\n"
    )
    import ast

    tree = ast.parse(source)
    entries = audit.collect_entry_points(tree, "a.py")
    assert entries[0].candidate_tunables == []


# --------------------------------------------------------------------------
# partial scans and the exit code
# --------------------------------------------------------------------------


def test_a_complete_scan_with_gaps_exits_zero(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()  # no agent at all: a gap, not a partial scan
    done, report = _audit(root, tmp_path / "out")
    assert done.returncode == 0, done.stderr
    assert report["scan_state"] == "complete"
    assert report["scan_partial_reasons"] == []


def test_an_unparsed_file_makes_the_scan_partial_and_exits_one(tmp_path: Path) -> None:
    root = _healthy(tmp_path)
    (root / "broken.py").write_text("def (\n", encoding="utf-8")
    done, report = _audit(root, tmp_path / "out")
    assert done.returncode == 1, done.stderr
    assert report["scan_state"] == "partial"
    assert "python_unparsed" in report["scan_partial_reasons"]
    assert "Scan state: PARTIAL" in done.stdout


def test_a_python_file_cap_makes_the_scan_partial(tmp_path: Path) -> None:
    root = _healthy(tmp_path)
    (root / "extra.py").write_text("X = 1\n", encoding="utf-8")
    done, report = _audit_with_caps(root, tmp_path / "out", MAX_PYTHON_FILES=1)
    assert done.returncode == 1, done.stderr
    assert "python_file_cap" in report["scan_partial_reasons"]


def test_an_oversized_dataset_makes_the_scan_partial(tmp_path: Path) -> None:
    done, report = _audit_with_caps(
        _healthy(tmp_path), tmp_path / "out", MAX_DATA_BYTES=10
    )
    assert done.returncode == 1, done.stderr
    assert "data_file_not_read" in report["scan_partial_reasons"]


def test_a_data_file_cap_makes_the_scan_partial(tmp_path: Path) -> None:
    root = _healthy(tmp_path)
    (root / "second.jsonl").write_text('{"input": "a", "output": "b"}\n', encoding="utf-8")
    done, report = _audit_with_caps(root, tmp_path / "out", MAX_DATA_FILES=1)
    assert done.returncode == 1, done.stderr
    assert "data_file_cap" in report["scan_partial_reasons"]


def test_a_row_cap_makes_the_scan_partial(tmp_path: Path) -> None:
    done, report = _audit_with_caps(_healthy(tmp_path), tmp_path / "out", MAX_ROWS=2)
    assert done.returncode == 1, done.stderr
    assert "data_rows_truncated" in report["scan_partial_reasons"]


def test_a_usage_error_still_exits_two(tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path / "missing")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert done.returncode == 2


# --------------------------------------------------------------------------
# symlinks that leave the root
# --------------------------------------------------------------------------


def test_symlinked_files_outside_the_root_are_skipped_unread(tmp_path: Path) -> None:
    root = _healthy(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret_data.jsonl").write_text(
        json.dumps({"input": CANARY, "output": CANARY}) + "\n", encoding="utf-8"
    )
    (outside / "leaky.py").write_text(
        f"CANARY = '{CANARY}'\n\ndef score_{CANARY.replace('-', '_')}(a, b):\n    return 1\n",
        encoding="utf-8",
    )
    (root / "linked.jsonl").symlink_to(outside / "secret_data.jsonl")
    (root / "linked.py").symlink_to(outside / "leaky.py")
    done, report = _audit(root, tmp_path / "out")
    blob = done.stdout + json.dumps(report)
    assert CANARY not in blob
    assert report["files"]["python_symlink_skipped"] == ["linked.py"]
    assert any("linked.jsonl" in line and "symlink" in line
               for line in report["files"]["dataset_files_not_analysed"])
    assert report["scan_state"] == "partial"
    assert done.returncode == 1


def test_a_symlink_that_stays_inside_the_root_is_read(tmp_path: Path) -> None:
    root = _healthy(tmp_path)
    (root / "alias.jsonl").symlink_to(root / "dataset.jsonl")
    _, report = _audit(root, tmp_path / "out")
    assert report["files"]["dataset_files_not_analysed"] == []


# --------------------------------------------------------------------------
# the parent process opens no socket
# --------------------------------------------------------------------------

TRIPWIRE = '''\
import atexit
import json
import os
import socket

HITS = {"network": []}


def _net(name):
    def tripped(*args, **kwargs):
        HITS["network"].append(name)
        raise OSError("tripwire: network blocked")

    return tripped


for _name in ("connect", "connect_ex"):
    setattr(socket.socket, _name, _net("socket." + _name))
for _name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "create_connection"):
    setattr(socket, _name, _net("socket." + _name))
atexit.register(lambda: open(os.environ["TRIPWIRE_OUT"], "w").write(json.dumps(HITS)))
'''


def test_the_audit_process_makes_no_network_attempt(tmp_path: Path) -> None:
    """A real subprocess, with the tripwire installed by `sitecustomize` before
    `audit_project.py` starts, so even an attempt the script's own guard would
    have refused is counted."""
    wire = tmp_path / "wire"
    wire.mkdir()
    (wire / "sitecustomize.py").write_text(TRIPWIRE, encoding="utf-8")
    out = tmp_path / "hits.json"
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env.update(PYTHONPATH=str(wire), TRIPWIRE_OUT=str(out))
    root = _healthy(tmp_path)
    done, report = _audit(root, tmp_path / "out", env=env)
    assert done.returncode == 0, done.stderr
    assert report["scorer_probe"]["ran"] is True  # the probe really ran
    assert json.loads(out.read_text(encoding="utf-8"))["network"] == []
