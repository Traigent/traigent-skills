"""Independent controls for the actual egress subprocess and ledger verifier."""
from __future__ import annotations

import contextlib
import json
import subprocess
import sys

import pytest

from .test_audit_355_mock_mode_egress_scope import _import_probe, REQUIRED_LEDGER_KEYS, _probe_lookups, run_probe
from .test_runnable_snippets import _offline_mock_env


@contextlib.contextmanager
def _mismatch():
    """Expect the verifier's evidence-decision failure, anchored at the message start."""
    with pytest.raises(AssertionError) as caught:
        yield
    assert str(caught.value).startswith("egress evidence mismatch:"), str(caught.value)


def _expect_verifier_failure(completed, expect_egress: bool) -> None:
    """The child must have run cleanly with a well-typed ledger, then the VERIFIER rejects it."""
    assert completed.returncode == 0, completed.stdout + completed.stderr
    lines = [x for x in completed.stdout.splitlines() if x.startswith("EGRESS_JSON=")]
    assert len(lines) == 1, completed.stdout + completed.stderr
    ledger = json.loads(lines[0].removeprefix("EGRESS_JSON="))
    assert set(ledger) == REQUIRED_LEDGER_KEYS, ledger
    for key in ("lookups", "connects"):
        assert isinstance(ledger[key], list) and all(isinstance(x, str) for x in ledger[key]), key
    for key in ("imported", "litellm_import_started"):
        assert isinstance(ledger[key], bool), key
    assert ledger["source_info"] is None or isinstance(ledger["source_info"], dict)
    with _mismatch():
        _probe_lookups(completed, expect_egress)


def _run_probe_with_pkg(script: str, tmp_path, init_body: str):
    """Run ``script`` with a fake ``litellm`` package whose __init__ is ``init_body``."""
    pkg = tmp_path / "pkg" / "litellm"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(init_body)
    env = _offline_mock_env()
    env["PYTHONPATH"] = str(tmp_path / "pkg")
    return run_probe([sys.executable, "-c", script], env=env, timeout=30)


def _run_probe(script: str) -> subprocess.CompletedProcess[str]:
    return run_probe([sys.executable, "-c", script], env=_offline_mock_env(), timeout=30)


def test_documented_positive_requires_success_without_dns() -> None:
    assert _probe_lookups(_run_probe(_import_probe("pass")), False) == []


def test_own_refused_dns_sentinel_is_accepted_as_negative_control(tmp_path) -> None:
    script = _import_probe("import litellm")
    completed = _run_probe_with_pkg(
        script, tmp_path, "import socket\nsocket.getaddrinfo('raw.githubusercontent.com', 443)\n")
    assert _probe_lookups(completed, True) == ["raw.githubusercontent.com"]


def test_unrelated_lookup_without_litellm_is_not_egress() -> None:
    script = _import_probe("socket.getaddrinfo('control.invalid', 443)")
    _expect_verifier_failure(_run_probe(script), True)


def test_missing_dns_cannot_pass_negative_control() -> None:
    _expect_verifier_failure(_run_probe(_import_probe("pass")), True)


def test_real_dns_cannot_pass_documented_positive_control() -> None:
    script = _import_probe("socket.getaddrinfo('control.invalid', 443)")
    _expect_verifier_failure(_run_probe(script), False)


def test_unexpected_import_error_before_dns_remains_failure() -> None:
    completed = _run_probe(_import_probe("raise ImportError('before-DNS-control')"))
    assert completed.returncode != 0
    assert "before-DNS-control" in completed.stderr
    with pytest.raises(AssertionError, match="before-DNS-control"):
        _probe_lookups(completed, True)


def test_unexpected_import_error_after_dns_remains_failure() -> None:
    # Simulate an imported module catching the probe interruption and raising
    # an unrelated error. A broad import catch must not turn this into success.
    statement = (
        "try:\n"
        "        socket.getaddrinfo('control.invalid', 443)\n"
        "    except ProbeNetworkAttempt:\n"
        "        raise ImportError('after-DNS-control')"
    )
    script = _import_probe(statement)
    completed = _run_probe(script)
    assert completed.returncode != 0
    assert "after-DNS-control" in completed.stderr
    with pytest.raises(AssertionError, match="after-DNS-control"):
        _probe_lookups(completed, True)


_FORCED = {"source": "local", "url": None, "is_env_forced": True, "fallback_reason": None}
_REMOTE = {"source": "local", "url": "https://example.invalid/map.json",
           "is_env_forced": False, "fallback_reason": "fetch failed"}


def _ledger(source_info, *, lookups=(), connects=(), imported=True, started=True):
    ledger = {"lookups": list(lookups), "connects": list(connects), "imported": imported,
              "source_info": source_info,
              "source_info_unavailable": None if source_info else "module absent in this litellm",
              "litellm_import_started": started, "pricing_host": "raw.githubusercontent.com"}
    return subprocess.CompletedProcess(
        [], 0, stdout="EGRESS_JSON=" + json.dumps(ledger) + "\n", stderr="")


def test_forced_local_record_with_lookup_fails_no_egress() -> None:
    with _mismatch():
        _probe_lookups(_ledger(_FORCED, lookups=["x.invalid"]), False)


def test_forced_local_record_with_connect_fails_no_egress() -> None:
    with _mismatch():
        _probe_lookups(_ledger(_FORCED, connects=["x"]), False)


def test_remote_record_counts_as_egress() -> None:
    assert _probe_lookups(_ledger(_REMOTE), True)


def test_forced_local_record_is_not_egress() -> None:
    with _mismatch():
        _probe_lookups(_ledger(_FORCED), True)


def test_clean_forced_local_record_passes_no_egress() -> None:
    assert _probe_lookups(_ledger(_FORCED), False) == []


def test_unforced_record_cannot_pass_no_egress() -> None:
    quiet = dict(_FORCED, is_env_forced=False)
    with _mismatch():
        _probe_lookups(_ledger(quiet), False)


def test_unrelated_host_without_record_cannot_pass_egress() -> None:
    with _mismatch():
        _probe_lookups(_ledger(None, lookups=["control.invalid"]), True)
    assert _probe_lookups(_ledger(None, lookups=["raw.githubusercontent.com"]), True)
    with _mismatch():  # import never started
        _probe_lookups(_ledger(None, lookups=["raw.githubusercontent.com"], started=False), True)


def test_forced_flag_cannot_hide_a_remote_url() -> None:
    contradictory = dict(_FORCED, url="https://example.invalid/map.json")
    with pytest.raises(AssertionError, match="contradictory"):
        _probe_lookups(_ledger(contradictory), False)
    with pytest.raises(AssertionError, match="contradictory"):
        _probe_lookups(_ledger(dict(_FORCED, source="remote")), False)


_ACCESSORS = {
    "no_module": (None, 0, "module absent"),
    "missing": ("x = 1\n", 0, "accessor missing"),
    "none": ("get_model_cost_map_source_info = None\n", 1, "not callable"),
    "dep_import_error": ("import nonexistent_dep_control\n", 1, "nonexistent_dep_control"),
    "init_attribute_error": ("raise AttributeError('init-attr-control')\n", 1, "init-attr-control"),
    "raises": ("def get_model_cost_map_source_info():\n    raise RuntimeError('boom-control')\n",
               1, "boom-control"),
}


@pytest.mark.parametrize("case", sorted(_ACCESSORS))
def test_probe_side_accessor_branches(tmp_path, case: str) -> None:
    body, rc_nonzero, expect = _ACCESSORS[case]
    utils = tmp_path / "pkg" / "litellm" / "litellm_core_utils"
    utils.mkdir(parents=True)
    (tmp_path / "pkg" / "litellm" / "__init__.py").write_text("")
    (utils / "__init__.py").write_text("")
    if body is not None:
        (utils / "get_model_cost_map.py").write_text(body)
    env = _offline_mock_env()
    env["PYTHONPATH"] = str(tmp_path / "pkg")
    completed = run_probe([sys.executable, "-c", _import_probe("import litellm")], env=env, timeout=30)
    assert (completed.returncode != 0) is bool(rc_nonzero), completed.stdout + completed.stderr
    assert expect in completed.stdout + completed.stderr


def test_lookalike_host_is_not_the_pricing_host() -> None:
    with _mismatch():
        _probe_lookups(_ledger(None, lookups=["raw.githubusercontent.com.example.invalid"]), True)
    assert _probe_lookups(_ledger(None, lookups=["Raw.GitHubUserContent.com."]), True)


def test_find_spec_then_unrelated_lookup_is_not_pricing_evidence(tmp_path) -> None:
    (tmp_path / "pkg" / "litellm").mkdir(parents=True)
    (tmp_path / "pkg" / "litellm" / "__init__.py").write_text("")
    statement = (
        "import importlib.util\n"
        "    assert importlib.util.find_spec('litellm') is not None\n"
        "    socket.getaddrinfo('raw.githubusercontent.com', 443)"
    )
    env = _offline_mock_env()
    env["PYTHONPATH"] = str(tmp_path / "pkg")
    completed = run_probe([sys.executable, "-c", _import_probe(statement)], env=env, timeout=30)
    _expect_verifier_failure(completed, True)


def test_real_connect_to_pricing_host_is_recorded_as_egress(tmp_path) -> None:
    completed = _run_probe_with_pkg(
        _import_probe("import litellm"), tmp_path,
        "import socket\nsocket.socket().connect(('raw.githubusercontent.com', 443))\n")
    assert _probe_lookups(completed, True) == ["raw.githubusercontent.com"]


def test_traigent_find_spec_then_lookup_is_not_pricing_evidence(tmp_path) -> None:
    for name, body in {"litellm": "", "traigent": (
        "import importlib.util, socket\n"
        "assert importlib.util.find_spec('litellm') is not None\n"
        "socket.getaddrinfo('raw.githubusercontent.com', 443)\n")}.items():
        (tmp_path / "pkg" / name).mkdir(parents=True)
        (tmp_path / "pkg" / name / "__init__.py").write_text(body)
    env = _offline_mock_env()
    env["PYTHONPATH"] = str(tmp_path / "pkg")
    completed = run_probe(
        [sys.executable, "-c", _import_probe("import traigent")], env=env, timeout=30)
    _expect_verifier_failure(completed, True)


def test_empty_ledger_is_malformed_not_an_evidence_failure() -> None:
    completed = subprocess.CompletedProcess([], 0, stdout="EGRESS_JSON={}\n", stderr="")
    with pytest.raises(AssertionError, match="malformed probe ledger"):
        _probe_lookups(completed, True)
    with pytest.raises(AssertionError):  # the helper refuses it too
        _expect_verifier_failure(completed, True)


def test_null_lookups_with_phrase_in_stderr_is_malformed_not_a_mismatch() -> None:
    ledger = {k: None for k in REQUIRED_LEDGER_KEYS}
    ledger.update(connects=[], imported=True, litellm_import_started=False)
    completed = subprocess.CompletedProcess(
        [], 0, stdout="EGRESS_JSON=" + json.dumps(ledger) + "\n",
        stderr="egress evidence mismatch: forged")
    with pytest.raises(AssertionError, match="malformed probe ledger"):
        _probe_lookups(completed, True)
    with pytest.raises(AssertionError):
        _expect_verifier_failure(completed, True)
    with pytest.raises(AssertionError) as caught:
        _probe_lookups(completed, True)
    assert not str(caught.value).startswith("egress evidence mismatch:")
