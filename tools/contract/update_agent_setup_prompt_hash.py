#!/usr/bin/env python3
"""Bump docs/agent-setup/provenance.json after an intentional edit to
docs/agent-setup/prompt.md (issue #234's bump protocol).

Recomputes doc_hash (first 16 hex chars of the file's SHA-256, matching the
per-skill provenance.json convention) and appends a dated manual_edit entry.
Reminds the operator that the two downstream vendored copies (TraigentFrontend
agentSetupPrompt.ts, traigent-web public/agent-setup/prompt.md) still need to be
re-synced by hand in their own repos/PRs — this script only pins the canonical
source's checksum.

Usage:
  python3 tools/contract/update_agent_setup_prompt_hash.py --note "<what changed and why>"
  python3 tools/contract/update_agent_setup_prompt_hash.py --check   # exit 1 if stale, no write
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def hash_prefix(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--note",
        help="One-line changelog note for the new provenance entry (required unless --check).",
    )
    parser.add_argument(
        "--edit-id",
        help="Optional stable id for the entry; defaults to a date-stamped id.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if doc_hash is stale; write nothing.",
    )
    args = parser.parse_args()

    root = repo_root()
    prompt_path = root / "docs" / "agent-setup" / "prompt.md"
    provenance_path = root / "docs" / "agent-setup" / "provenance.json"

    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    before = provenance.get("doc_hash")
    after = hash_prefix(prompt_path)

    if args.check:
        if before == after:
            print("docs/agent-setup/provenance.json doc_hash is current.")
            return 0
        print(
            f"STALE: doc_hash={before!r} but docs/agent-setup/prompt.md hashes to {after!r}"
        )
        return 1

    if before == after:
        print("Already up to date; no entry added.")
        return 0

    if not args.note:
        raise SystemExit("--note is required to record why prompt.md changed")

    edit_id = args.edit_id or f"prompt-edit-{datetime.now(timezone.utc):%Y-%m-%d}"
    provenance["doc_hash"] = after
    entries = provenance.setdefault("entries", [])
    entries.append(
        {
            "edit_id": edit_id,
            "op": "manual_edit",
            "status": "accepted",
            "run_id": None,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z"),
            "doc_before_hash": before,
            "doc_after_hash": after,
            "note": args.note,
            "source_type": "human",
        }
    )
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"Updated docs/agent-setup/provenance.json: {before!r} -> {after!r}")
    print(
        "Reminder: re-sync the two downstream copies in their own repos/PRs — "
        "TraigentFrontend agentSetupPrompt.ts and traigent-web public/agent-setup/prompt.md — "
        "per docs/agent-setup/README.md's bump protocol."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
