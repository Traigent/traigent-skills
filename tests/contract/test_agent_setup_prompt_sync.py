"""Contract test: docs/agent-setup/prompt.md must carry a pinned checksum.

Issue #234: the canonical agent-setup prompt exists in three places — this file (the
source of truth), the TraigentFrontend vendored constant, and the traigent-web static
copy. Cross-repo CI fetches to compare all three are brittle, so this repo's guard is
narrower: pin a checksum of the canonical body in docs/agent-setup/provenance.json
(schema mirrors the per-skill provenance.json convention in test_provenance.py) and
fail loudly whenever prompt.md changes without that checksum being bumped. That forces
every edit through the bump protocol documented in docs/agent-setup/README.md, which is
where a human re-syncs the two downstream copies and records why.

This test does NOT reach into TraigentFrontend or traigent-web — those consumer repos
need their own local guard asserting their copy matches this pinned checksum, tracked
separately from this issue.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def test_agent_setup_prompt_doc_hash_matches_provenance() -> None:
    root = repo_root()
    prompt_path = root / "docs" / "agent-setup" / "prompt.md"
    provenance_path = root / "docs" / "agent-setup" / "provenance.json"

    assert prompt_path.is_file(), f"missing {prompt_path}"
    assert provenance_path.is_file(), f"missing {provenance_path}"

    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    expected = _file_hash(prompt_path)
    actual = provenance.get("doc_hash")

    assert actual == expected, (
        "docs/agent-setup/prompt.md changed without updating its pinned checksum "
        f"(provenance.json doc_hash={actual!r}, live file hash={expected!r}). "
        "Run `python3 tools/contract/update_agent_setup_prompt_hash.py --note "
        '"<what changed and why>"` and follow the bump protocol in '
        "docs/agent-setup/README.md — including re-syncing the two downstream "
        "vendored copies (TraigentFrontend agentSetupPrompt.ts, traigent-web "
        "public/agent-setup/prompt.md) before merging."
    )


def test_agent_setup_prompt_provenance_has_at_least_one_entry() -> None:
    root = repo_root()
    provenance = json.loads(
        (root / "docs" / "agent-setup" / "provenance.json").read_text(
            encoding="utf-8"
        )
    )
    entries = provenance.get("entries")
    assert isinstance(entries, list) and entries, (
        "docs/agent-setup/provenance.json must record at least a genesis entry"
    )
    for entry in entries:
        assert entry.get("edit_id"), f"provenance entry missing edit_id: {entry}"
        assert entry.get("note"), f"provenance entry missing note: {entry}"
