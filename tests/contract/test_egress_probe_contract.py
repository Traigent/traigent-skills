"""Independent controls for the actual egress subprocess and ledger verifier."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from .test_audit_355_mock_mode_egress_scope import _import_probe, _probe_lookups
from .test_runnable_snippets import _offline_mock_env


_FAKE_LITELLM = "sys.modules['litellm'] = type(sys)('litellm'); "


def _run_probe(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script], env=_offline_mock_env(),
        text=True, capture_output=True, timeout=30, check=False,
    )


def test_documented_positive_requires_success_without_dns() -> None:
    assert _probe_lookups(_run_probe(_import_probe("pass")), False) == []


def test_own_refused_dns_sentinel_is_accepted_as_negative_control() -> None:
    script = _import_probe(_FAKE_LITELLM + "socket.getaddrinfo('raw.githubusercontent.com', 443)")
    assert _probe_lookups(_run_probe(script), True) == ["raw.githubusercontent.com"]


def test_unrelated_lookup_without_litellm_is_not_egress() -> None:
    script = _import_probe("socket.getaddrinfo('control.invalid', 443)")
    with pytest.raises(AssertionError):
        _probe_lookups(_run_probe(script), True)


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


def _ledger(source_info, *, lookups=(), connects=(), imported=True, loaded=True):
    ledger = {"lookups": list(lookups), "connects": list(connects), "imported": imported,
              "source_info": source_info,
              "source_info_unavailable": None if source_info else "module absent in this litellm",
              "litellm_loaded": loaded, "pricing_host": "raw.githubusercontent.com"}
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


def test_unrelated_host_without_record_cannot_pass_egress() -> None:
    with pytest.raises(AssertionError):
        _probe_lookups(_ledger(None, lookups=["control.invalid"]), True)
    assert _probe_lookups(_ledger(None, lookups=["raw.githubusercontent.com"]), True)
    with pytest.raises(AssertionError):  # litellm never loaded: no evidence
        _probe_lookups(_ledger(None, lookups=["raw.githubusercontent.com"], loaded=False), True)


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
    completed = subprocess.run(
        [sys.executable, "-c", _import_probe("import litellm")], env=env,
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert (completed.returncode != 0) is bool(rc_nonzero), completed.stdout + completed.stderr
    assert expect in completed.stdout + completed.stderr
