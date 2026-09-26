"""A key value must not reach the card or the JSON by ANY path.

The first canary only covered the path that was already safe — a `.env` file on
the normal run. The three fixtures here are the paths that actually leaked: an
exception raised at import, an exception raised on every scoring call, and a
module that writes to stderr and ends the process. Each carries a sentinel read
from the environment, and each must be reported by exception TYPE and location
only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_project.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

SENTINEL = "canary-value-must-not-appear"

LEAK_ROUTES = ["leak-import", "leak-call", "leak-stderr"]


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


@pytest.fixture()
def sentinel_key(monkeypatch):
    """Set the sentinel in THIS process so every child inherits it.

    Handing `subprocess.run` a copied environment would work too, but copying
    the whole environment into a variable is the shape a credential scanner
    flags, and inheritance says the same thing more plainly.
    """
    monkeypatch.setenv("TRAIGENT_API_KEY", SENTINEL)
    return SENTINEL


@pytest.mark.parametrize("route", LEAK_ROUTES)
def test_no_sentinel_in_card_or_json(route: str, sentinel_key, tmp_path: Path) -> None:
    report, card = _run(FIXTURES / route, tmp_path)
    assert SENTINEL not in card
    assert SENTINEL not in json.dumps(report)
    assert report["areas"]["scorer"]["status"] == "attention"


def test_an_import_failure_is_reported_by_type_and_location(
    sentinel_key, tmp_path: Path
) -> None:
    report, card = _run(FIXTURES / "leak-import", tmp_path)
    probe = report["scorer_probe"]
    assert probe["ran"] is False
    assert probe["stage"] == "load"
    assert probe["error_type"] == "RuntimeError"
    assert probe["error_site"].startswith("scorer.py:")
    assert "misconfigured" not in card
    assert "RuntimeError at scorer.py:" in card
    assert "while loading, so it never ran" in card


def test_a_scoring_failure_is_reported_by_type_and_location(
    sentinel_key, tmp_path: Path
) -> None:
    report, card = _run(FIXTURES / "leak-call", tmp_path)
    probe = report["scorer_probe"]
    assert probe["ran"] is True
    assert probe["scores"]["good"] == []
    assert {error["error_type"] for error in probe["errors"]} == {"ValueError"}
    assert all(error["error_site"].startswith("scorer.py:") for error in probe["errors"])
    assert "cannot score" not in card
    assert "every probe call raised ValueError at scorer.py:" in card


def test_stderr_text_is_reduced_to_a_byte_count(sentinel_key, tmp_path: Path) -> None:
    report, card = _run(FIXTURES / "leak-stderr", tmp_path)
    probe = report["scorer_probe"]
    assert probe["ran"] is False
    assert probe["stage"] == "no-result"
    assert isinstance(probe["stderr_bytes"], int) and probe["stderr_bytes"] > 0
    assert "stderr_tail" not in probe
    assert "fatal" not in card


@pytest.mark.parametrize("route", LEAK_ROUTES)
def test_an_unmeasured_scorer_never_gets_the_instability_sentence(
    route: str, sentinel_key, tmp_path: Path
) -> None:
    """F8: a scorer that could not run is not a scorer that is unrepeatable."""
    _, card = _run(FIXTURES / route, tmp_path)
    assert "returns different numbers for the same pair" not in card
    assert "could not be run, so its repeatability is unmeasured" in card
    assert "0 times returned 0 different scores" not in card


def test_the_env_file_path_is_still_covered(tmp_path: Path) -> None:
    """The original canary, kept: a sentinel in .env is reported by NAME only."""
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / "healthy", root)
    (root / ".env").write_text(
        f"TRAIGENT_API_KEY={SENTINEL}\nOPENAI_API_KEY={SENTINEL}\n", encoding="utf-8"
    )
    report, card = _run(root, tmp_path / "out")
    assert SENTINEL not in card
    assert SENTINEL not in json.dumps(report)
    declared = report["setup"]["keys"]["names_declared_in_env_files"][".env"]
    assert declared == ["TRAIGENT_API_KEY", "OPENAI_API_KEY"]
    # tmp_path is under /tmp: without the sandbox bind this probe never loaded,
    # so the canary was inspecting a report with no probe output to leak.
    assert report["scorer_probe"]["ran"] is True, report["scorer_probe"]


# Bit values the environment-probe scorer adds up. The scorer reports which
# variable NAMES it can see through its score, never a value.
_ENV_BITS = {
    "TRAIGENT_API_KEY": 1,
    "OPENAI_API_KEY": 2,
    "ANY_TOKEN": 4,
    "PATH": 8,
    "HOME": 16,
}
_ENV_SCORER = (
    "import os\n\n"
    # Read at import, the way the leak-import fixture reads its key.
    "IMPORT_KEY = os.getenv('TRAIGENT_API_KEY', '')\n"
    f"BITS = {_ENV_BITS!r}\n\n"
    "def score(output, expected):\n"
    "    seen = sum(bit for name, bit in BITS.items() if name in os.environ)\n"
    "    return float(seen + (32 if IMPORT_KEY else 0))\n"
)


def test_the_scorer_probe_gets_no_key_or_token_variables(
    sentinel_key, monkeypatch, tmp_path: Path
) -> None:
    """The probe runs code the audit does not fully trust: it gets no credential,
    and still gets the ordinary variables an honest scorer may rely on."""
    monkeypatch.setenv("OPENAI_API_KEY", SENTINEL)
    monkeypatch.setenv("ANY_TOKEN", SENTINEL)
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "project"
    root.mkdir()
    (root / "scorer.py").write_text(_ENV_SCORER, encoding="utf-8")
    report, card = _run(root, tmp_path)
    probe = report["scorer_probe"]
    assert probe["ran"] is True, probe
    assert probe["scores"]["good"], probe
    visible = {
        name for name, bit in _ENV_BITS.items() if int(probe["scores"]["good"][0]) & bit
    }
    assert visible == {"PATH", "HOME"}
    assert int(probe["scores"]["good"][0]) & 32 == 0
    assert SENTINEL not in card


# Credential shapes a suffix denylist let through (and the ones it caught): the
# probe gets an allowlist, so every one of them, and any unknown name, is
# withheld. Values are placeholders; only whether the NAME is visible matters.
_WITHHELD = tuple(
    """
    API_TOKENS AWS_ACCESS_KEY_ID AWS_WEB_IDENTITY_TOKEN_FILE
    AZURE_STORAGE_CONNECTION_STRING CLIENT_SECRETS DATABASE_URL GITHUB_PAT
    GPG_PASSPHRASE HTTPS_PROXY KUBECONFIG MYSQL_PWD NETRC PASSWORD PGPASSWORD
    PIP_INDEX_URL REDIS_URL SECRET SENTRY_DSN SLACK_WEBHOOK_URL SMTP_PASS
    SSH_AUTH_SOCK TOKEN AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN DB_PASSWORD
    GOOGLE_APPLICATION_CREDENTIALS HF_TOKEN OPENAI_API_KEY FOO
    """.split()
)
_PASSED = ("PATH", "HOME", "LC_CTYPE")


def test_the_scorer_probe_gets_only_an_allowlisted_environment(
    sentinel_key, monkeypatch, tmp_path: Path
) -> None:
    names = (*_WITHHELD, *_PASSED)
    for name in _WITHHELD:
        monkeypatch.setenv(name, SENTINEL)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LC_CTYPE", "C.UTF-8")
    root = tmp_path / "project"
    root.mkdir()
    (root / "scorer.py").write_text(
        "import os\n\n"
        f"NAMES = {names!r}\n\n"
        "def score(output, expected):\n"
        "    return float(sum(1 << i for i, n in enumerate(NAMES) if n in os.environ))\n",
        encoding="utf-8",
    )
    report, card = _run(root, tmp_path)
    probe = report["scorer_probe"]
    assert probe["ran"] is True, probe
    bits = int(probe["scores"]["good"][0])
    visible = {name for i, name in enumerate(names) if bits & (1 << i)}
    assert visible == set(_PASSED)
    assert SENTINEL not in card
