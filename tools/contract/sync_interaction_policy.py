#!/usr/bin/env python3
"""Inject or refresh the shared Traigent Interaction Policy managed block in every SKILL.md.

Source of truth: docs/shared/interaction-policy.v1.md
Markers: <!-- INTERACTION_POLICY v1 ... --> ... <!-- /INTERACTION_POLICY v1 -->

Placement: the managed block is always appended at the END of each SKILL.md, as the
final section. Appending at EOF guarantees that injecting the block never disrupts
proximity relationships between existing lines that other contract lints depend on.
If the block already exists somewhere in the file, it is removed from its current
position (collapsing only the blank lines at that splice boundary) and re-appended at
the end; if it is already the trailing section with matching content, the file is
left byte-for-byte unchanged (idempotent).

Usage:
  python tools/contract/sync_interaction_policy.py          # write mode (default)
  python tools/contract/sync_interaction_policy.py --check  # exit 1 if any SKILL.md is missing
                                                             # or has a stale block
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


START_MARKER = "<!-- INTERACTION_POLICY v1 (synced — do not edit inline; edit docs/shared/interaction-policy.v1.md) -->"
END_MARKER = "<!-- /INTERACTION_POLICY v1 -->"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_canonical_block(root: Path) -> str:
    """Return the full managed block including start and end markers."""
    source = root / "docs" / "shared" / "interaction-policy.v1.md"
    text = source.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    collecting = False
    block_lines: list[str] = []
    for line in lines:
        stripped = line.rstrip("\n")
        if stripped == START_MARKER:
            collecting = True
        if collecting:
            block_lines.append(line)
        if collecting and stripped == END_MARKER:
            break
    if not block_lines:
        raise SystemExit(
            f"Could not find managed block markers in {source}.\n"
            f"Expected start: {START_MARKER!r}"
        )
    # Ensure block ends with a single newline (no trailing blank lines)
    block = "".join(block_lines)
    if not block.endswith("\n"):
        block += "\n"
    return block


def process_skill(skill_path: Path, canonical_block: str, check: bool) -> bool:
    """Process a single SKILL.md. Returns True if a change was made (or needed in check mode).

    The canonical block is always placed at the END of the file so that injecting it
    never disturbs proximity relationships between existing lines that other lints depend on.
    If the block already exists (anywhere in the file), it is removed from its current
    position and re-appended at the end — unless it is already at the end with matching
    content, in which case the file is unchanged.
    """
    text = skill_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Find existing region if present
    start_idx = -1
    end_idx = -1
    for i, line in enumerate(lines):
        if line.rstrip("\n") == START_MARKER:
            start_idx = i
        if line.rstrip("\n") == END_MARKER and start_idx >= 0:
            end_idx = i
            break

    if start_idx >= 0 and end_idx >= 0:
        # Remove existing region from current position, collapsing blank lines ONLY at
        # the splice boundary where the block was removed. Blank lines elsewhere in the
        # document (including intentional double blanks) are left byte-for-byte intact.
        pre = lines[:start_idx]
        post = lines[end_idx + 1 :]
        # Drop blank lines trailing pre (left over above the removed block)
        while pre and pre[-1].strip() == "":
            pre.pop()
        # Drop blank lines leading post (left over below the removed block)
        while post and post[0].strip() == "":
            post.pop(0)
        # Rejoin: restore exactly one blank line at the splice (if post is non-empty)
        if pre and post:
            body_lines = pre + ["\n"] + post
        else:
            body_lines = pre + post
    else:
        body_lines = list(lines)

    # Strip trailing blank lines before appending the canonical block
    while body_lines and body_lines[-1].strip() == "":
        body_lines.pop()

    # Rebuild: body + blank separator + canonical block
    body_text = "".join(body_lines)
    if body_text and not body_text.endswith("\n"):
        body_text += "\n"
    new_text = body_text + "\n" + canonical_block

    if new_text == text:
        return False  # already up to date and in correct position

    if check:
        if start_idx < 0:
            print(f"MISSING: {skill_path}")
        else:
            print(f"STALE: {skill_path}")
        return True

    skill_path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inject or refresh the shared interaction-policy block in every SKILL.md."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any SKILL.md is missing or has a stale block; print which.",
    )
    args = parser.parse_args()

    root = repo_root()
    canonical_block = load_canonical_block(root)

    skills_root = root / "skills"
    skill_files = sorted(
        p / "SKILL.md"
        for p in skills_root.iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file()
    )

    if not skill_files:
        print("No SKILL.md files found.", file=sys.stderr)
        return 1

    changed: list[Path] = []
    for skill_path in skill_files:
        if process_skill(skill_path, canonical_block, check=args.check):
            changed.append(skill_path)

    if args.check:
        if changed:
            print(
                f"\n{len(changed)} SKILL.md file(s) are missing or have a stale interaction-policy block.",
                file=sys.stderr,
            )
            return 1
        print(f"All {len(skill_files)} SKILL.md files have the current interaction-policy block.")
        return 0

    if changed:
        print(f"Updated {len(changed)} SKILL.md file(s):")
        for p in changed:
            print(f"  {p.relative_to(root)}")
    else:
        print(f"All {len(skill_files)} SKILL.md files already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
