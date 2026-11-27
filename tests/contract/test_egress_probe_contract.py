"""Independent controls for the actual egress subprocess and ledger verifier."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from .test_audit_355_mock_mode_egress_scope import _import_probe, _probe_lookups
from .test_runnable_snippets import _offline_mock_env


def _run_probe(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script], env=_offline_mock_env(),
        text=True, capture_output=True, timeout=30, check=False,
    )


def test_documented_positive_requires_success_without_dns() -> None:
    assert _probe_lookups(_run_probe(_import_probe("pass")), False) == []


def test_own_refused_dns_sentinel_is_accepted_as_negative_control() -> None:
    script = _import_probe("socket.getaddrinfo('control.invalid', 443)")
    assert _probe_lookups(_run_probe(script), True) == ["control.invalid"]


def test_missing_dns_cannot_pass_negative_control() -> None:
    with pytest.raises(AssertionError):
        _probe_lookups(_run_probe(_import_probe("pass")), True)


def test_real_dns_cannot_pass_documented_positive_control() -> None:
    script = _import_probe("socket.getaddrinfo('control.invalid', 443)")
    with pytest.raises(AssertionError):
        _probe_lookups(_run_probe(script), False)


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


def _ledger(source_info, *, lookups=(), connects=(), imported=True):
    ledger = {"lookups": list(lookups), "connects": list(connects), "imported": imported,
              "source_info": source_info,
              "source_info_unavailable": None if source_info else "module absent in this litellm"}
    return subprocess.CompletedProcess(
        [], 0, stdout="EGRESS_JSON=" + json.dumps(ledger) + "\n", stderr="")


def test_forced_local_record_with_lookup_fails_no_egress() -> None:
    with pytest.raises(AssertionError):
        _probe_lookups(_ledger(_FORCED, lookups=["x.invalid"]), False)


def test_forced_local_record_with_connect_fails_no_egress() -> None:
    with pytest.raises(AssertionError):
        _probe_lookups(_ledger(_FORCED, connects=["('x', 443)"]), False)


def test_remote_record_counts_as_egress() -> None:
    assert _probe_lookups(_ledger(_REMOTE), True)


def test_forced_local_record_is_not_egress() -> None:
    with pytest.raises(AssertionError):
        _probe_lookups(_ledger(_FORCED), True)


def test_clean_forced_local_record_passes_no_egress() -> None:
    assert _probe_lookups(_ledger(_FORCED), False) == []


def test_unforced_record_cannot_pass_no_egress() -> None:
    quiet = dict(_FORCED, is_env_forced=False)
    with pytest.raises(AssertionError):
        _probe_lookups(_ledger(quiet), False)
