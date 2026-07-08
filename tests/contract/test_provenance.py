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
    "skill_dir", PROVENANCED_SKILLS, ids=[d.name for d in PROVENANCED_SKILLS]
)
def test_provenance_hash_chain_is_continuous(skill_dir: Path) -> None:
    """Hashed provenance entries must link consecutively and end at top-level doc_hash."""
    provenance = json.loads(
        (skill_dir / "provenance.json").read_text(encoding="utf-8")
    )
    hashed_entries = [
        entry
        for entry in provenance.get("entries", [])
        if entry.get("doc_before_hash") and entry.get("doc_after_hash")
    ]

    for i in range(len(hashed_entries) - 1):
        current = hashed_entries[i]
        nxt = hashed_entries[i + 1]
        assert current["doc_after_hash"] == nxt["doc_before_hash"], (
            f"{skill_dir.name}: broken provenance hash chain between "
            f"{current.get('edit_id', f'entries[{i}]')!r} (after="
            f"{current['doc_after_hash']!r}) and "
            f"{nxt.get('edit_id', f'entries[{i + 1}]')!r} (before="
            f"{nxt['doc_before_hash']!r})"
        )

    if hashed_entries:
        last_entry = hashed_entries[-1]
        assert last_entry["doc_after_hash"] == provenance.get("doc_hash"), (
            f"{skill_dir.name}: last hashed entry "
            f"{last_entry.get('edit_id', 'entries[-1]')!r} doc_after_hash "
            f"{last_entry['doc_after_hash']!r} does not match top-level "
            f"doc_hash {provenance.get('doc_hash')!r}"
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
