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
import re
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _provenance_errors(provenance: dict[str, object], expected_hash: str) -> list[str]:
    errors: list[str] = []
    doc_hash = provenance.get("doc_hash")
    if doc_hash != expected_hash:
        errors.append(
            f"doc_hash={doc_hash!r} does not match live prompt hash={expected_hash!r}"
        )

    entries = provenance.get("entries")
    if not isinstance(entries, list) or not entries:
        return [*errors, "provenance must record at least a genesis entry"]

    previous_after: object = None
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entry {index} is not an object")
            previous_after = None
            continue
        if not entry.get("edit_id"):
            errors.append(f"entry {index} is missing edit_id")
        if not entry.get("note"):
            errors.append(f"entry {index} is missing note")

        after = entry.get("doc_after_hash")
        if not isinstance(after, str) or re.fullmatch(r"[0-9a-f]{16}", after) is None:
            errors.append(f"entry {index} has invalid doc_after_hash={after!r}")
        if index > 0 and entry.get("doc_before_hash") != previous_after:
            errors.append(
                f"entry {index} breaks the hash chain: "
                f"doc_before_hash={entry.get('doc_before_hash')!r}, "
                f"previous doc_after_hash={previous_after!r}"
            )
        previous_after = after

    if previous_after != doc_hash:
        errors.append(
            "latest entry does not terminate at doc_hash: "
            f"doc_after_hash={previous_after!r}, doc_hash={doc_hash!r}"
        )
    return errors


def test_agent_setup_prompt_provenance_is_current_and_contiguous() -> None:
    root = repo_root()
    prompt_path = root / "docs" / "agent-setup" / "prompt.md"
    provenance_path = root / "docs" / "agent-setup" / "provenance.json"

    assert prompt_path.is_file(), f"missing {prompt_path}"
    assert provenance_path.is_file(), f"missing {provenance_path}"

    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    expected = _file_hash(prompt_path)
    errors = _provenance_errors(provenance, expected)

    assert not errors, (
        "docs/agent-setup prompt provenance is invalid:\n- "
        + "\n- ".join(errors)
        + "\n"
        "Run `python3 tools/contract/update_agent_setup_prompt_hash.py --note "
        '"<what changed and why>"` and follow the bump protocol in '
        "docs/agent-setup/README.md — including re-syncing whichever downstream "
        "copies it currently lists (verify each is still a copy before touching it) "
        "before merging."
    )


def test_hash_only_restamp_does_not_satisfy_provenance_guard() -> None:
    old_hash = "a" * 16
    new_hash = "b" * 16
    provenance = {
        "doc_hash": new_hash,
        "entries": [
            {"edit_id": "genesis", "note": "baseline", "doc_after_hash": old_hash}
        ],
    }

    errors = _provenance_errors(provenance, new_hash)

    assert any("latest entry does not terminate at doc_hash" in error for error in errors)


def test_broken_middle_link_does_not_satisfy_provenance_guard() -> None:
    first_hash = "a" * 16
    second_hash = "b" * 16
    latest_hash = "c" * 16
    provenance = {
        "doc_hash": latest_hash,
        "entries": [
            {"edit_id": "genesis", "note": "baseline", "doc_after_hash": first_hash},
            {
                "edit_id": "edit-1",
                "note": "first edit",
                "doc_before_hash": "f" * 16,
                "doc_after_hash": second_hash,
            },
            {
                "edit_id": "edit-2",
                "note": "second edit",
                "doc_before_hash": second_hash,
                "doc_after_hash": latest_hash,
            },
        ],
    }

    errors = _provenance_errors(provenance, latest_hash)

    assert any("entry 1 breaks the hash chain" in error for error in errors)


def test_valid_provenance_append_satisfies_guard() -> None:
    old_hash = "a" * 16
    new_hash = "b" * 16
    provenance = {
        "doc_hash": new_hash,
        "entries": [
            {"edit_id": "genesis", "note": "baseline", "doc_after_hash": old_hash},
            {
                "edit_id": "edit-1",
                "note": "intentional update",
                "doc_before_hash": old_hash,
                "doc_after_hash": new_hash,
            },
        ],
    }

    assert _provenance_errors(provenance, new_hash) == []
