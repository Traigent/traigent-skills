"""Contract test: provenance.json hashes must match current skill document bytes.

Spec: eval-artifacts/README.md, "Provenance v1" — doc_hash is the first 16 hex
characters of the SHA-256 hash of the corresponding SKILL.md bytes, and
reference_hashes maps references/*.md paths to the same hash prefix for each
reference file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _skill_dirs(root: Path) -> list[Path]:
    skills_root = root / "skills"
    return sorted(d for d in skills_root.iterdir() if d.is_dir())


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _provenanced_skills(root: Path) -> list[Path]:
    return [
        d
        for d in _skill_dirs(root)
        if (d / "provenance.json").is_file() and (d / "SKILL.md").is_file()
    ]


def _orphan_provenance_skills(root: Path) -> list[Path]:
    return [
        d
        for d in _skill_dirs(root)
        if (d / "provenance.json").is_file() and not (d / "SKILL.md").is_file()
    ]


def _unprovenanced_skills(root: Path) -> list[Path]:
    return [
        d
        for d in _skill_dirs(root)
        if (d / "SKILL.md").is_file() and not (d / "provenance.json").is_file()
    ]


def _skills_with_references(root: Path) -> list[Path]:
    return [
        d
        for d in _skill_dirs(root)
        if (d / "SKILL.md").is_file() and (d / "references").is_dir()
    ]


PROVENANCED_SKILLS = _provenanced_skills(repo_root())
UNPROVENANCED_SKILLS = _unprovenanced_skills(repo_root())
SKILLS_WITH_REFERENCES = _skills_with_references(repo_root())


@pytest.mark.parametrize(
    "skill_dir", PROVENANCED_SKILLS, ids=[d.name for d in PROVENANCED_SKILLS]
)
def test_provenance_doc_hash_matches_skill_md(skill_dir: Path) -> None:
    """skills/<name>/provenance.json doc_hash must equal the live SKILL.md hash."""
    provenance = json.loads(
        (skill_dir / "provenance.json").read_text(encoding="utf-8")
    )
    expected = _file_hash(skill_dir / "SKILL.md")
    actual = provenance.get("doc_hash")
    assert actual == expected, (
        f"{skill_dir.name}: provenance.json doc_hash is stale "
        f"(expected {expected!r} for current SKILL.md, found {actual!r}) — "
        "regenerate doc_hash after any SKILL.md content change"
    )


@pytest.mark.parametrize(
    "skill_dir",
    SKILLS_WITH_REFERENCES,
    ids=[d.name for d in SKILLS_WITH_REFERENCES],
)
def test_provenance_reference_hashes_match_references(skill_dir: Path) -> None:
    """reference_hashes must cover exactly references/*.md with live byte hashes."""
    assert (skill_dir / "provenance.json").is_file(), (
        f"{skill_dir.name}: skills with references/ must have provenance.json "
        "with reference_hashes"
    )
    provenance = json.loads(
        (skill_dir / "provenance.json").read_text(encoding="utf-8")
    )
    references = sorted((skill_dir / "references").glob("*.md"))
    expected = {
        f"references/{path.name}": _file_hash(path)
        for path in references
    }
    actual = provenance.get("reference_hashes")
    assert actual == expected, (
        f"{skill_dir.name}: provenance.json reference_hashes is stale "
        f"(expected {expected!r}, found {actual!r}) — regenerate "
        "reference_hashes after any references/*.md content change"
    )


@pytest.mark.parametrize(
    "skill_dir", UNPROVENANCED_SKILLS, ids=[d.name for d in UNPROVENANCED_SKILLS]
)
def test_skill_without_provenance_is_skipped(skill_dir: Path) -> None:
    pytest.skip(
        f"{skill_dir.name}: no provenance.json yet — genesis entries are owned by "
        "the private evaluation harness (eval-artifacts/README.md, Provenance v1)"
    )


def test_no_orphan_provenance_files() -> None:
    """A provenance.json without a matching SKILL.md is a leftover the gate must catch."""
    orphans = _orphan_provenance_skills(repo_root())
    assert not orphans, "provenance.json exists without a matching SKILL.md for: " + ", ".join(
        d.name for d in orphans
    )


# --- Chain continuity (traigent-skills#196) -------------------------------
#
# The head-hash check above only proves doc_hash matches the CURRENT SKILL.md.
# It says nothing about whether the entries[] ledger is a continuous record of
# how the document got there: a doc_hash bump with no matching entries[]
# record (a "restamp") is invisible to it. This check instead walks each
# provenance file's entries in file order and requires that, among entries
# carrying both doc_before_hash and doc_after_hash, each one's doc_before_hash
# equals the previous such entry's doc_after_hash, and that the last such
# entry's doc_after_hash equals the file's current doc_hash.
#
# Two exception lists below carve out breaks this check would otherwise flag
# that are NOT the transition traigent-skills#196 backfills. Every entry is
# commented with why. Never add to these silently — a break here means a real
# SKILL.md edit that the ledger does not account for.

# (skill_name, edit_id of the entry whose doc_before_hash does not match the
# previous hashed entry's doc_after_hash) -> reason.
CHAIN_BREAK_EXCEPTIONS: dict[tuple[str, str], str] = {
    # 2026-07-17/18 wave: "plugin-taxonomy-metadata" and
    # "economics-bounded-investment-posture" were authored on parallel
    # branches off the same parent state (both entries' doc_before_hash equal
    # that parent's doc_after_hash), later reconciled by a
    # "merge-main-taxonomy-into-econ-wi-a" entry. entries[] is a flat list and
    # cannot represent two branches sharing a parent; pre-existing, out of
    # scope for #196.
    ("traigent-analyze-guidance", "economics-bounded-investment-posture-2026-07-17"): (
        "parallel-branch entry (see module docstring); pre-existing, out of scope for #196"
    ),
    ("traigent-analyze-results", "economics-bounded-investment-posture-2026-07-17"): (
        "parallel-branch entry (see module docstring); pre-existing, out of scope for #196"
    ),
    ("traigent-boost-agent", "economics-bounded-investment-posture-2026-07-17"): (
        "parallel-branch entry (see module docstring); pre-existing, out of scope for #196"
    ),
    ("traigent-dataset-curate", "economics-bounded-investment-posture-2026-07-17"): (
        "parallel-branch entry (see module docstring); pre-existing, out of scope for #196"
    ),
    ("traigent-eval-audit", "economics-bounded-investment-posture-2026-07-17"): (
        "parallel-branch entry (see module docstring); pre-existing, out of scope for #196"
    ),
    ("traigent-optimize-run", "economics-bounded-investment-posture-2026-07-17"): (
        "parallel-branch entry (see module docstring); pre-existing, out of scope for #196"
    ),
    ("traigent-setup-decorator", "economics-bounded-investment-posture-2026-07-17"): (
        "parallel-branch entry (see module docstring); pre-existing, out of scope for #196"
    ),
    ("traigent-setup-quickstart", "economics-bounded-investment-posture-2026-07-17"): (
        "parallel-branch entry (see module docstring); pre-existing, out of scope for #196"
    ),
    # 2026-09-13 "example-insights-api-v1-base-url" (PR #277) and other
    # 2026-08/2026-09 restamps below: same entry-less-restamp class #196
    # documents, but from later commits than 56b7d22/PR #170 — the specific
    # transition #196 scoped in and backfilled. Discovered while adding this
    # check; root commit not archaeologized here. Pre-existing, needs its own
    # follow-up issue, out of scope for #196.
    ("traigent-analyze-guidance", "example-insights-api-v1-base-url-2026-09-13"): (
        "later entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
    ("traigent-boost-agent", "example-insights-api-v1-base-url-2026-09-13"): (
        "later entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
    ("traigent-dataset-curate", "example-insights-api-v1-base-url-2026-09-13"): (
        "later entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
    ("traigent-eval-audit", "task-type-not-in-released-sdk-2026-09-13"): (
        "later entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
    ("traigent-setup-decorator", "task-type-not-in-released-sdk-2026-09-13"): (
        "later entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
    ("traigent-analyze-results", "sim-findings-persistence-status-2026-07-04"): (
        "entry-less restamp predating 56b7d22; pre-existing, out of scope for #196"
    ),
    ("traigent-analyze-results", "noise-doctrine-corrections-2026-07-15"): (
        "entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
    ("traigent-analyze-results", "plugin-taxonomy-metadata-2026-07-18"): (
        "entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
    ("traigent-analyze-results", "drop-retired-next-steps-pointer-2026-08-11"): (
        "entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
    ("traigent-optimize-composite-knobs", "version-matrix-collapse-2026-07-15"): (
        "entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
    ("traigent-optimize-run", "tenacity-preflight-scope-and-citation-fix-2026-07-15"): (
        "entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
    ("traigent-recipe-text2sql", "exec-eval-per-row-id-2026-07-15"): (
        "entry-less restamp between 56b7d22 and this entry (PR #208 / #221 era, "
        "confirmed by `git log -- skills/traigent-recipe-text2sql/SKILL.md`); "
        "not 56b7d22 itself, which #196's backfilled entry accounts for "
        "separately; pre-existing, out of scope for #196"
    ),
    ("traigent-recipe-text2sql", "scoring-lessons-2026-09-13"): (
        "later entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
    ("traigent-setup-decorator", "winner-stability-reps-2026-08-13"): (
        "entry-less restamp, not 56b7d22/PR #170; pre-existing, out of scope for #196"
    ),
}

# skill_name -> reason, for files where the LAST hashed entry's doc_after_hash
# does not equal the current doc_hash (a content change with no entries[]
# record at all, not even a broken one).
TAIL_MISMATCH_EXCEPTIONS: dict[str, str] = {
    "traigent-analyze-results": "most recent restamp has no entries[] record at all; pre-existing, out of scope for #196",
    "traigent-analyze-variable-importance": "most recent restamp has no entries[] record at all; pre-existing, out of scope for #196",
    "traigent-eval-build": "most recent restamp has no entries[] record at all; pre-existing, out of scope for #196",
    "traigent-eval-choose-metric": "most recent restamp has no entries[] record at all; pre-existing, out of scope for #196",
    "traigent-js": "most recent restamp has no entries[] record at all; pre-existing, out of scope for #196",
    "traigent-optimize-composite-knobs": "most recent restamp has no entries[] record at all; pre-existing, out of scope for #196",
    "traigent-optimize-run": "most recent restamp has no entries[] record at all; pre-existing, out of scope for #196",
    "traigent-setup-quickstart": "most recent restamp has no entries[] record at all; pre-existing, out of scope for #196",
}


def _hashed_entries(provenance: dict) -> list[dict]:
    return [
        e
        for e in provenance.get("entries", [])
        if "doc_before_hash" in e and "doc_after_hash" in e
    ]


@pytest.mark.parametrize(
    "skill_dir", PROVENANCED_SKILLS, ids=[d.name for d in PROVENANCED_SKILLS]
)
def test_provenance_entry_chain_is_continuous(skill_dir: Path) -> None:
    """Consecutive hashed entries must chain: entries[i].doc_after_hash ==
    entries[i+1].doc_before_hash, and the last hashed entry's doc_after_hash
    must equal doc_hash — unless the specific break is named in
    CHAIN_BREAK_EXCEPTIONS / TAIL_MISMATCH_EXCEPTIONS above."""
    name = skill_dir.name
    provenance = json.loads(
        (skill_dir / "provenance.json").read_text(encoding="utf-8")
    )
    entries = _hashed_entries(provenance)
    if not entries:
        return

    prev_after = None
    for entry in entries:
        before = entry.get("doc_before_hash")
        if prev_after is not None and before != prev_after:
            key = (name, entry["edit_id"])
            assert key in CHAIN_BREAK_EXCEPTIONS, (
                f"{name}: entry {entry['edit_id']!r} has doc_before_hash "
                f"{before!r} but the previous hashed entry's doc_after_hash "
                f"is {prev_after!r} — the ledger claims a continuity it does "
                "not have. If this is a new, real transition, add a "
                "manual_edit entry that closes the gap instead of excepting it."
            )
        prev_after = entry.get("doc_after_hash")

    doc_hash = provenance.get("doc_hash")
    if prev_after != doc_hash:
        assert name in TAIL_MISMATCH_EXCEPTIONS, (
            f"{name}: last hashed entry's doc_after_hash {prev_after!r} does "
            f"not equal doc_hash {doc_hash!r} — the most recent SKILL.md "
            "change has no entries[] record at all."
        )
