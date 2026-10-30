"""Issue #465: mock-scope statements must be version-qualified for SDK 0.31.0.

Before 0.31.0 the LiteLLM interceptors were installed lazily, once an evaluator was built,
and a raw ``openai``/``anthropic`` call in mock mode reached the provider. From 0.31.0 they
are installed when mock mode is enabled (a standalone ``litellm.completion`` gets the canned
reply) and a request to a known LLM provider host is blocked, not billed. The block covers
httpx, aiohttp and requests only, so ``boto3`` and unlisted hosts are NOT covered: a skill
must never promise "no real call".
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.version import Version

from .test_runnable_snippets import _offline_mock_env

# Unversioned claims that raw clients bill / reach the provider under mock mode.
STALE = re.compile(
    r"real,\s+billable|still\s+calls\s+the\s+provider|still\s+bill\b|"
    r"will\s+reach\s+the\s+real\s+API|make\s+real,\s+billable",
    re.IGNORECASE,
)


def _markdown(root: Path) -> list[Path]:
    return sorted((root / "skills").rglob("*.md"))


def test_no_unversioned_raw_client_billing_claim(repo_root: Path) -> None:
    offenders = []
    for path in _markdown(repo_root):
        text = path.read_text(encoding="utf-8")
        for match in STALE.finditer(text):
            before = text[max(0, match.start() - 300) : match.start()].lower()
            if "raw" not in before and "mock" not in before:
                continue  # a claim about something other than raw clients under mock
            window = text[max(0, match.start() - 700) : match.end() + 700]
            if "0.31" not in window:
                offenders.append(f"{path.relative_to(repo_root)}: {match.group(0)!r}")
    assert not offenders, "\n".join(offenders)


def test_dataset_curate_no_longer_claims_standalone_litellm_is_unmocked_on_0_31(
    repo_root: Path,
) -> None:
    raw = (repo_root / "skills/traigent-dataset-curate/SKILL.md").read_text(encoding="utf-8")
    text = " ".join(re.sub(r"\n>[ ]?", "\n", raw).split())  # drop blockquote markers
    assert "still true on the SDK development branch" not in text
    assert "through 0.30.0" in text
    assert "From traigent 0.31.0 the interceptors are installed when mock mode is enabled" in text


def test_replacement_text_does_not_promise_no_real_call(repo_root: Path) -> None:
    """boto3 and unlisted hosts are not blocked; the debugging reference must say so."""
    text = " ".join(
        (repo_root / "skills/traigent-debugging/references/mock-mode.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert "boto3" in text and "not blocked" in text
    assert "MockModeTransportBlockedError" in text


PROBE = r'''
import json
import httpx
import litellm
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()   # no evaluator, no optimize run
reply = litellm.completion(
    model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
).choices[0].message.content
try:
    httpx.post("https://api.openai.com/v1/chat/completions", json={}, timeout=5)
except Exception as exc:
    blocked = type(exc).__name__
else:
    blocked = None
print("PROBE_JSON=" + json.dumps({"reply": reply, "blocked": blocked}))
'''


def test_standalone_litellm_is_mocked_and_provider_host_is_blocked(
    tmp_path: Path, sdk_version_label: str
) -> None:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.31.0"):
        pytest.skip("interceptors-at-enable and the transport guard ship in SDK 0.31.0")
    (tmp_path / "probe.py").write_text(PROBE, encoding="utf-8")
    env = _offline_mock_env()
    env["HOME"] = str(tmp_path)
    done = subprocess.run(
        [sys.executable, "probe.py"], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=120, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    import json

    line = next(r for r in done.stdout.splitlines() if r.startswith("PROBE_JSON="))
    data = json.loads(line.split("=", 1)[1])
    assert data == {
        "reply": "This is a mock response for testing.",
        "blocked": "MockModeTransportBlockedError",
    }
