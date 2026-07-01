from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_ioc_manager():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "repo-forensics"
        / "ioc_manager.py"
    )
    spec = importlib.util.spec_from_file_location("repo_forensics_ioc_manager", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_fetch_remote_iocs_rejects_loopback_without_network(monkeypatch):
    ioc_manager = _load_ioc_manager()
    calls = []

    def fake_urlopen(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("urlopen must not be called for rejected IOC feed URLs")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert ioc_manager.fetch_remote_iocs("https://127.0.0.1/latest.json") is None
    assert calls == []


def test_fetch_remote_iocs_rejects_non_https_without_network(monkeypatch):
    ioc_manager = _load_ioc_manager()
    calls = []

    def fake_urlopen(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("urlopen must not be called for rejected IOC feed URLs")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    url = "http://raw.githubusercontent.com/alexgreensh/repo-forensics/main/iocs/latest.json"
    assert ioc_manager.fetch_remote_iocs(url) is None
    assert calls == []


def test_fetch_remote_iocs_rejects_unapproved_hosts_without_network(monkeypatch):
    ioc_manager = _load_ioc_manager()
    calls = []

    def fake_urlopen(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("urlopen must not be called for rejected IOC feed URLs")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert ioc_manager.fetch_remote_iocs("https://ioc.example.com/latest.json") is None
    assert calls == []


def test_fetch_remote_iocs_allows_configured_https_hosts(monkeypatch):
    ioc_manager = _load_ioc_manager()
    calls = []
    payload = {"version": "test", "c2_ips": ["203.0.113.10"]}

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return _FakeResponse(payload)

    monkeypatch.setenv(
        ioc_manager.IOC_FEED_ALLOWED_HOSTS_ENV,
        "ioc.example.com",
    )
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    url = "https://IOC.Example.com/latest.json?version=1#discarded"
    assert ioc_manager.fetch_remote_iocs(url) is None
    assert calls == []

    assert (
        ioc_manager.fetch_remote_iocs("https://IOC.Example.com/latest.json?version=1")
        == payload
    )
    request, timeout = calls[0]
    assert request.full_url == "https://ioc.example.com/latest.json?version=1"
    assert timeout == 10
