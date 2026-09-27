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


def _skills(root: Path) -> list[Path]:
    return [d for d in _skill_dirs(root) if (d / "SKILL.md").is_file()]


def _skills_with_references(root: Path) -> list[Path]:
    return [
        d
        for d in _skill_dirs(root)
        if (d / "SKILL.md").is_file() and (d / "references").is_dir()
    ]


PROVENANCED_SKILLS = _provenanced_skills(repo_root())
SKILLS = _skills(repo_root())
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


@pytest.mark.parametrize("skill_dir", SKILLS, ids=[d.name for d in SKILLS])
def test_every_skill_has_provenance(skill_dir: Path) -> None:
    """Every shipped skill carries the provenance.json the README promises."""
    assert (skill_dir / "provenance.json").is_file(), (
        f"{skill_dir.name}: missing provenance.json — add one with a genesis entry "
        "and the current doc_hash (eval-artifacts/README.md, Provenance v1)"
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
# carrying both doc_before_hash and doc_after_hash ("hashed" entries), each
# one's doc_before_hash equals the previous hashed entry's doc_after_hash,
# and that the last hashed entry's doc_after_hash equals the file's current
# doc_hash. A skill with no hashed entries at all is its own gap (see
# NO_HASHED_ENTRIES below), not a silent pass.
#
# Every gap this check can find must be named in GAP_EXCEPTIONS, keyed by the
# exact hash pair the gap interrupts:
#   - a mid-chain break:  (skill, previous_hashed_entry.doc_after_hash, this_entry.doc_before_hash)
#   - a tail gap:         (skill, last_hashed_entry.doc_after_hash, doc_hash)
#   - no hashed entries:  (skill, "NO_HASHED_ENTRIES", doc_hash)
#
# This key form is deliberate, not incidental (traigent-skills#296 review):
#   - it survives a later, correct backfill elsewhere in the file — appending
#     a new hashed entry whose doc_before_hash equals today's doc_hash does
#     not change any *existing* gap's key, so a legitimate concurrent PR
#     landing an entry after this one does not silently stop this exception
#     from applying (and does not have to re-derive #196's archaeology to
#     pass);
#   - it does NOT survive a fresh, undocumented restamp — that produces a
#     brand-new doc_hash, so the new gap gets a brand-new key that is not in
#     this list and the gate goes red, pointing at the exact hash pair rather
#     than an edit_id that may not exist yet;
#   - keying by skill name alone (this test's first version) fails both of
#     the above: it is blind to a fresh restamp in an already-excepted skill,
#     and it silently stops applying — with no red run to notice — once a
#     concurrent PR's real entry moves the gap so it is no longer the last
#     one in the file.
#
# test_gap_exceptions_are_all_still_present (below) fails if a listed gap is
# ever closed by a later backfill and the exception here is not removed with
# it — so this list cannot silently accumulate exceptions for gaps that no
# longer exist. Never add to GAP_EXCEPTIONS silently: a gap means a real
# SKILL.md edit the ledger does not account for, and every entry below says
# why it is not backfilled instead.

GapKey = tuple[str, str, str]

GAP_EXCEPTIONS: dict[GapKey, str] = {
    # ---- 2026-07-17/18: parallel-branch entries ------------------------
    # "plugin-taxonomy-metadata" and "economics-bounded-investment-posture"
    # were authored on parallel branches off the same parent state (both
    # entries' doc_before_hash equal that parent's doc_after_hash), later
    # reconciled by a "merge-main-taxonomy-into-econ-wi-a" entry. entries[]
    # is a flat list and cannot represent two branches sharing a parent.
    # Pre-existing, out of scope for #196.
    ("traigent-analyze-guidance", "9e8947db2d7bad68", "51a8c8aea0c8cf0f"): (
        "parallel-branch entry (economics-bounded-investment-posture); "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-analyze-results", "6432031d644c8756", "39352a037b3de5b2"): (
        "parallel-branch entry (plugin-taxonomy-metadata); "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-analyze-results", "90f6042298762b22", "39352a037b3de5b2"): (
        "parallel-branch entry (economics-bounded-investment-posture); "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-boost-agent", "a1ba7cac8c65847e", "23c57e5772586d93"): (
        "parallel-branch entry (economics-bounded-investment-posture); "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-dataset-curate", "fceec8f630dddba9", "f5481ef2791c45ef"): (
        "parallel-branch entry (economics-bounded-investment-posture); "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-eval-audit", "e1dc3f964df22735", "0cfbd5cc6be2f30e"): (
        "parallel-branch entry (economics-bounded-investment-posture); "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-optimize-run", "c583ed2a9cf5b838", "ad8b4d5c3c32a975"): (
        "parallel-branch entry (economics-bounded-investment-posture); "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-setup-decorator", "56d38399635cfff3", "3db71bdafe5e0a1a"): (
        "parallel-branch entry (economics-bounded-investment-posture); "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-setup-quickstart", "59f3b56507cbe500", "3a19554c5624fb4f"): (
        "parallel-branch entry (economics-bounded-investment-posture); "
        "pre-existing, out of scope for #196"
    ),
    # ---- gaps recorded by an unhashed entry, hashes not reconstructed --
    # A human did record that something changed here (a "sync"-style entry
    # with no doc_before_hash/doc_after_hash), but never computed the hashes
    # that would let this check verify it. Not a silent, entirely-unrecorded
    # restamp — but not proven continuous either. Pre-existing, needs its
    # own follow-up (reconstruct hashes or accept the marker as sufficient
    # evidence), out of scope for #196.
    ("traigent-analyze-results", "1304fd657c6d23e6", "340a0a2fcbcad0a8"): (
        "recorded by unhashed entry 'interaction-policy-v1'; hashes not "
        "reconstructed; pre-existing, out of scope for #196"
    ),
    ("traigent-analyze-results", "fa7179e14caa7e5d", "bddd73a79633f84d"): (
        "recorded by unhashed entry "
        "'experiment-name-is-agent-identity-2026-07-31'; hashes not "
        "reconstructed; pre-existing, out of scope for #196"
    ),
    ("traigent-dataset-curate", "4b56d7384f50327c", "66f94132aa33a1c9"): (
        "recorded by unhashed entry 'cold-start-reachable-on-0270'; hashes "
        "not reconstructed; pre-existing, out of scope for #196"
    ),
    ("traigent-eval-audit", "d15b6fdda96fd741", "47040b9de571bb0e"): (
        "recorded by unhashed entry 'task-type-anchor-hint-2026-09-03'; "
        "hashes not reconstructed; pre-existing, out of scope for #196"
    ),
    ("traigent-setup-decorator", "70b7b9dd90bedca4", "479e7e43caf5632c"): (
        "recorded by unhashed entry "
        "'experiment-name-is-agent-identity-2026-07-31'; hashes not "
        "reconstructed; pre-existing, out of scope for #196"
    ),
    ("traigent-setup-decorator", "eefb5531a7c0f0eb", "8e34812e7e96968d"): (
        "recorded by unhashed entry 'task-type-anchor-hint-2026-09-03'; "
        "hashes not reconstructed; pre-existing, out of scope for #196"
    ),
    # ---- entry-less restamps: no entry at all records the transition ---
    # Same entry-less-restamp class #196 documents, but from commits other
    # than 56b7d22/PR #170 (the specific transition #196 scoped in and
    # backfilled) — some earlier, most later (2026-07 through 2026-09-13).
    # Discovered while adding this check; root commits not archaeologized
    # beyond what is noted. Pre-existing, needs its own follow-up issue(s),
    # out of scope for #196.
    ("traigent-analyze-guidance", "1a9538ec844f62b6", "5418a7b27f43de56"): (
        "entry-less restamp (2026-09-13 wave), not 56b7d22/PR #170; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-analyze-results", "0f5541aff757d0dd", "0d00b6ce0f5f6491"): (
        "entry-less restamp, not 56b7d22/PR #170; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-analyze-results", "c343887a6484b340", "acde24064b27156b"): (
        "tail gap: most recent restamp has no entries[] record at all; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-analyze-variable-importance", "05a4232224a1fbda", "d6a76300a735a4ed"): (
        "tail gap: most recent restamp has no entries[] record at all; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-boost-agent", "c8075d9a69ea3126", "5a83d2a3b6fc907a"): (
        "entry-less restamp (2026-09-13 wave), not 56b7d22/PR #170; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-eval-build", "d608c3e241d120cc", "cc9f6f6cf32aeae7"): (
        "tail gap: most recent restamp has no entries[] record at all; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-eval-choose-metric", "9ae5277b1c573049", "04a4cfc25a7ece77"): (
        "tail gap: most recent restamp has no entries[] record at all; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-js", "832faf18089d7a0f", "45c9bde670e83621"): (
        "tail gap: most recent restamp has no entries[] record at all; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-optimize-composite-knobs", "1ebba8e6b8f2d243", "a483d26dd976e3b4"): (
        "entry-less restamp, not 56b7d22/PR #170; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-optimize-composite-knobs", "31680229368b35c3", "f9a13d9a52df48b9"): (
        "tail gap: most recent restamp has no entries[] record at all; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-optimize-run", "b9ed4f4e52c073c4", "3827c7798632a4d9"): (
        "entry-less restamp, not 56b7d22/PR #170; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-optimize-run", "c578e36da860899e", "87cd2c82ec0b39da"): (
        "tail gap: most recent restamp has no entries[] record at all; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-recipe-text2sql", "418baaedb8e56a96", "b27a561f3ca49876"): (
        "entry-less restamp between 56b7d22 and the next entry (PR #208 / "
        "#221 era, confirmed by `git log -- "
        "skills/traigent-recipe-text2sql/SKILL.md`); not 56b7d22 itself, "
        "which #196's backfilled entry accounts for separately; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-recipe-text2sql", "cabf21cdbb60e87d", "030cd36ac0e1e40a"): (
        "entry-less restamp (2026-09-13 wave), not 56b7d22/PR #170; "
        "pre-existing, out of scope for #196"
    ),
    ("traigent-setup-quickstart", "f41343a8272f8da4", "094e4551130954cc"): (
        "tail gap: most recent restamp has no entries[] record at all; "
        "pre-existing, out of scope for #196"
    ),
}


def _hashed_entries(provenance: dict) -> list[dict]:
    return [
        e
        for e in provenance.get("entries", [])
        if "doc_before_hash" in e and "doc_after_hash" in e
    ]


def _chain_gaps(name: str, provenance: dict) -> list[tuple[GapKey, str]]:
    """Walk entries[] in file order and return (gap_key, message) for every
    place the recorded chain does not connect: a mid-chain break, a tail gap
    (most recent doc_hash unaccounted for), or no hashed entries at all. The
    message names any unhashed entries sitting in the gap by edit_id, since
    those may already record the transition without hash proof rather than
    the transition being wholly unrecorded (traigent-skills#296 review, I4)."""
    all_entries = provenance.get("entries", [])
    doc_hash = provenance.get("doc_hash")
    hashed_positions = [
        i
        for i, e in enumerate(all_entries)
        if "doc_before_hash" in e and "doc_after_hash" in e
    ]
    if not hashed_positions:
        return [
            (
                (name, "NO_HASHED_ENTRIES", doc_hash),
                f"{name}: no entry carries both doc_before_hash and "
                "doc_after_hash — nothing here proves doc_hash's history.",
            )
        ]

    def unhashed_between(lo: int, hi: int) -> list[str]:
        return [
            all_entries[i]["edit_id"]
            for i in range(lo, hi)
            if not (
                "doc_before_hash" in all_entries[i]
                and "doc_after_hash" in all_entries[i]
            )
        ]

    gaps: list[tuple[GapKey, str]] = []
    prev_idx: int | None = None
    prev_after: str | None = None
    for idx in hashed_positions:
        entry = all_entries[idx]
        before = entry["doc_before_hash"]
        if prev_after is not None and before != prev_after:
            between = unhashed_between(prev_idx + 1, idx)  # type: ignore[operator]
            if between:
                msg = (
                    f"{name}: gap before {entry['edit_id']!r} (doc_before_hash "
                    f"{before!r} != previous hashed entry's doc_after_hash "
                    f"{prev_after!r}) — recorded by unhashed entry(ies) "
                    f"{between} without hash proof, hashes not reconstructed."
                )
            else:
                msg = (
                    f"{name}: gap before {entry['edit_id']!r} (doc_before_hash "
                    f"{before!r} != previous hashed entry's doc_after_hash "
                    f"{prev_after!r}) — no entries[] record at all for this "
                    "transition."
                )
            gaps.append(((name, prev_after, before), msg))
        prev_idx = idx
        prev_after = entry["doc_after_hash"]

    if prev_after != doc_hash:
        between = unhashed_between(prev_idx + 1, len(all_entries))  # type: ignore[operator]
        if between:
            msg = (
                f"{name}: tail gap after {all_entries[prev_idx]['edit_id']!r} "
                f"(last hashed doc_after_hash {prev_after!r} != doc_hash "
                f"{doc_hash!r}) — recorded by unhashed entry(ies) {between} "
                "without hash proof, hashes not reconstructed."
            )
        else:
            msg = (
                f"{name}: tail gap after "
                f"{all_entries[prev_idx]['edit_id']!r} (last hashed "
                f"doc_after_hash {prev_after!r} != doc_hash {doc_hash!r}) — "
                "the most recent SKILL.md change has no entries[] record at "
                "all, not even a broken one."
            )
        gaps.append(((name, prev_after, doc_hash), msg))
    return gaps


@pytest.mark.parametrize(
    "skill_dir", PROVENANCED_SKILLS, ids=[d.name for d in PROVENANCED_SKILLS]
)
def test_provenance_entry_chain_is_continuous(skill_dir: Path) -> None:
    """Every gap _chain_gaps finds must be named in GAP_EXCEPTIONS. A fresh,
    undocumented restamp produces hashes that were never seen before, so it
    gets a gap key that cannot already be in GAP_EXCEPTIONS — the gate goes
    red pointing at the exact hash pair. If this is a new, real transition,
    add a manual_edit entry that closes the gap instead of excepting it."""
    name = skill_dir.name
    provenance = json.loads(
        (skill_dir / "provenance.json").read_text(encoding="utf-8")
    )
    for key, message in _chain_gaps(name, provenance):
        assert key in GAP_EXCEPTIONS, (
            message
            + " The ledger claims a continuity it does not have. If this is "
            "a new, real transition, add a manual_edit entry that closes "
            "the gap instead of excepting it."
        )


def test_gap_exceptions_are_all_still_present() -> None:
    """Every key in GAP_EXCEPTIONS must correspond to a gap that still
    exists on disk. If a listed gap is ever closed by a later backfill (its
    entries[] grows a real entry spanning it), its key stops appearing here
    — remove the now-stale exception in the same change, so this list can
    never silently accumulate entries for gaps nobody re-checks."""
    root = repo_root()
    current_gaps: set[GapKey] = set()
    for skill_dir in PROVENANCED_SKILLS:
        provenance = json.loads(
            (skill_dir / "provenance.json").read_text(encoding="utf-8")
        )
        current_gaps.update(key for key, _ in _chain_gaps(skill_dir.name, provenance))
    stale = set(GAP_EXCEPTIONS) - current_gaps
    assert not stale, (
        "GAP_EXCEPTIONS names gaps that no longer exist in skills/ under "
        f"{root} (already fixed?) — remove the stale exception(s): "
        + ", ".join(repr(k) for k in sorted(stale))
    )


@pytest.mark.parametrize(
    "skill_dir", PROVENANCED_SKILLS, ids=[d.name for d in PROVENANCED_SKILLS]
)
def test_provenance_entries_have_paired_hashes(skill_dir: Path) -> None:
    """An entry with only one of doc_before_hash/doc_after_hash is not a
    valid partial record — it silently drops out of the chain walk above
    (which requires both) while looking like it might mean something.
    Every entry must carry both hash fields or neither."""
    name = skill_dir.name
    provenance = json.loads(
        (skill_dir / "provenance.json").read_text(encoding="utf-8")
    )
    for entry in provenance.get("entries", []):
        has_before = "doc_before_hash" in entry
        has_after = "doc_after_hash" in entry
        assert has_before == has_after, (
            f"{name}: entry {entry.get('edit_id')!r} has only one of "
            "doc_before_hash/doc_after_hash — both or neither."
        )
