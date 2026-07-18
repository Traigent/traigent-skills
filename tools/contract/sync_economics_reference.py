#!/usr/bin/env python3
"""Propagate the canonical economics reference into every economics skill's references/.

Source of truth: docs/shared/economics-characterization.v0.md
Generated copies: skills/<name>/references/economics-characterization.v0.md

Why copies exist at all: the supported install paths (`npx skills add --skill <one>`,
`cp -r traigent-skills/skills/<one> .agents/skills/`) copy ONE skill directory. A skill
that points at a repo-root `docs/` path is pointing at a file the user does not have.
Every path a SKILL.md tells an agent to read must resolve inside the skill directory.

This does not create eight sources of truth. The doc is authored in exactly one place;
the per-skill files are generated artifacts, byte-identical to the source, refreshed by
this tool and pinned by tests/contract/test_economics_reference.py. Editing a generated
copy is a defect the contract suite fails on. This mirrors the existing
sync_interaction_policy.py pattern for the same reason.

Target skills are discovered, not hardcoded: any SKILL.md carrying the economics pointer
marker gets the reference.

Usage:
  python tools/contract/sync_economics_reference.py          # write mode (default)
  python tools/contract/sync_economics_reference.py --check  # exit 1 if any copy is
                                                             # missing, stale, or orphaned
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


CANONICAL_RELPATH = "docs/shared/economics-characterization.v0.md"
REFERENCE_RELPATH = "references/economics-characterization.v0.md"

# The line every economics SKILL.md carries to point at its local copy. Presence of this
# marker is what marks a skill as an economics skill.
POINTER_MARKER = "`references/economics-characterization.v0.md`"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def canonical_text(root: Path) -> str:
    source = root / CANONICAL_RELPATH
    if not source.is_file():
        raise SystemExit(f"Canonical economics reference not found: {CANONICAL_RELPATH}")
    return source.read_text(encoding="utf-8")


def economics_skill_dirs(root: Path) -> list[Path]:
    """Skill dirs whose SKILL.md points at the local economics reference."""
    skills_root = root / "skills"
    found: list[Path] = []
    for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        if POINTER_MARKER in skill_md.read_text(encoding="utf-8"):
            found.append(skill_dir)
    return found


def orphaned_copies(root: Path, expected: list[Path]) -> list[Path]:
    """Generated copies left behind in skills that no longer point at the reference."""
    expected_names = {d.name for d in expected}
    skills_root = root / "skills"
    return [
        skill_dir / REFERENCE_RELPATH
        for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir())
        if (skill_dir / REFERENCE_RELPATH).is_file() and skill_dir.name not in expected_names
    ]


def sync_skill(skill_dir: Path, text: str, check: bool) -> bool:
    """Write (or verify) one skill's copy. Returns True if it changed / needs changing."""
    target = skill_dir / REFERENCE_RELPATH
    if target.is_file() and target.read_text(encoding="utf-8") == text:
        return False
    if check:
        print("MISSING" if not target.is_file() else "STALE", target)
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync the canonical economics reference into every economics skill."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any copy is missing, stale, or orphaned; print which.",
    )
    args = parser.parse_args()

    root = repo_root()
    text = canonical_text(root)
    targets = economics_skill_dirs(root)

    if not targets:
        print(
            f"No SKILL.md points at {REFERENCE_RELPATH} — nothing to sync. "
            "Did the pointer wording change?",
            file=sys.stderr,
        )
        return 1

    changed = [d for d in targets if sync_skill(d, text, args.check)]
    orphans = orphaned_copies(root, targets)
    for orphan in orphans:
        print(f"ORPHAN (skill no longer points at the reference): {orphan}")

    if args.check:
        if changed or orphans:
            print(
                f"\n{len(changed)} stale/missing copy(ies), {len(orphans)} orphan(s). "
                "Run: python tools/contract/sync_economics_reference.py",
                file=sys.stderr,
            )
            return 1
        print(f"All {len(targets)} economics skill(s) carry the current reference.")
        return 0

    if orphans:
        print(
            "\nOrphaned copies above were NOT deleted automatically — remove them by hand "
            "once you are sure the skill should no longer carry the reference.",
            file=sys.stderr,
        )
    if changed:
        print(f"Updated {len(changed)} skill reference copy(ies):")
        for d in changed:
            print(f"  {(d / REFERENCE_RELPATH).relative_to(root)}")
    else:
        print(f"All {len(targets)} economics skill(s) already up to date.")
    print(
        "\nprovenance.json reference_hashes now need a refresh: "
        "python tools/contract/update_reference_hashes.py"
    )
    return 1 if orphans else 0


if __name__ == "__main__":
    raise SystemExit(main())
