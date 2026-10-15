"""Independent controls for the actual egress subprocess and ledger verifier."""
from __future__ import annotations

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
