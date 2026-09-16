"""Contract test: docs/agent-setup/prompt.md must carry a pinned checksum.

Issue #234: this file is the source of truth for the canonical agent-setup prompt; at
least one consumer (the TraigentFrontend portal) vendors it into its own constant.
Cross-repo CI fetches to compare copies live are brittle, so this repo's guard is
narrower: pin a checksum of the canonical body in docs/agent-setup/provenance.json
(schema mirrors the per-skill provenance.json convention in test_provenance.py) and
fail loudly whenever prompt.md changes without that checksum being bumped. That forces
every edit through the bump protocol documented in docs/agent-setup/README.md, which is
where a human re-syncs known downstream copies and records why — see that doc for which
copies currently need re-syncing (the list has drifted before: a copy once thought
canonical can be deliberately replaced upstream of this repo).

This test does NOT reach into any consumer repo — each one needs its own local guard
asserting its copy matches this pinned checksum; see docs/agent-setup/README.md for
what is and isn't tracked yet.
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
        "docs/agent-setup/README.md — including re-syncing whichever downstream "
        "copies it currently lists (verify each is still a copy before touching it) "
        "before merging."
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
