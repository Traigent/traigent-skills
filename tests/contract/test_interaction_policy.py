"""Contract test: every SKILL.md must contain the canonical interaction-policy block exactly once,
verbatim between the managed markers, and the block must not be nested inside a PROTECTED or
SLOW_UPDATE region.
"""
from __future__ import annotations

from pathlib import Path

import pytest


START_MARKER = "<!-- INTERACTION_POLICY v1 (synced — do not edit inline; edit docs/shared/interaction-policy.v1.md) -->"
END_MARKER = "<!-- /INTERACTION_POLICY v1 -->"

PROTECTED_STARTS = ("<!-- PROTECTED -->", "<!-- SLOW_UPDATE -->")
PROTECTED_ENDS = ("<!-- /PROTECTED -->", "<!-- /SLOW_UPDATE -->")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_canonical_block(root: Path) -> str:
    """Load the canonical block (from START_MARKER through END_MARKER inclusive)."""
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
    assert block_lines, f"Canonical block not found in {source}"
    block = "".join(block_lines)
    if not block.endswith("\n"):
        block += "\n"
    return block


def _protected_line_set(lines: list[str]) -> set[int]:
    """Return the set of 0-based line indices that are inside PROTECTED or SLOW_UPDATE regions.

    An UNCLOSED region (an opening marker with no matching close) is treated as
    protecting through end-of-file, so a dangling marker cannot be used to hide a
    nested block from this check.
    """
    protected: set[int] = set()
    depth = 0
    region_start = -1
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if any(stripped == ps for ps in PROTECTED_STARTS):
            if depth == 0:
                region_start = i
            depth += 1
        elif any(stripped == pe for pe in PROTECTED_ENDS):
            depth = max(0, depth - 1)
            if depth == 0 and region_start >= 0:
                protected.update(range(region_start, i + 1))
                region_start = -1
    # Unclosed region: protect from its opening marker through end-of-file.
    if depth > 0 and region_start >= 0:
        protected.update(range(region_start, len(lines)))
    return protected


def _skill_markdown_files(root: Path) -> list[tuple[str, Path]]:
    skills_root = root / "skills"
    out: list[tuple[str, Path]] = []
    for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if skill_file.is_file():
            out.append((skill_dir.name, skill_file))
    return out


def test_every_skill_has_canonical_interaction_policy_block() -> None:
    """Every skills/*/SKILL.md contains the exact canonical block, exactly once."""
    root = repo_root()
    canonical = _load_canonical_block(root)
    skill_files = _skill_markdown_files(root)

    assert skill_files, "No SKILL.md files found under skills/"

    violations: list[str] = []
    for skill_name, skill_path in skill_files:
        text = skill_path.read_text(encoding="utf-8")
        rel = skill_path.relative_to(root).as_posix()

        # Count occurrences of the start marker
        occurrences = text.count(START_MARKER)
        if occurrences == 0:
            violations.append(f"{rel}: missing interaction-policy block (no start marker)")
            continue
        if occurrences > 1:
            violations.append(
                f"{rel}: interaction-policy block appears {occurrences} times (must be exactly 1)"
            )
            continue

        # The end marker must also appear exactly once.
        end_occurrences = text.count(END_MARKER)
        if end_occurrences != 1:
            violations.append(
                f"{rel}: interaction-policy end marker appears {end_occurrences} times "
                f"(must be exactly 1)"
            )
            continue

        # Extract the block from the file
        lines = text.splitlines(keepends=True)
        start_idx = -1
        end_idx = -1
        for i, line in enumerate(lines):
            if line.rstrip("\n") == START_MARKER:
                start_idx = i
            if line.rstrip("\n") == END_MARKER and start_idx >= 0:
                end_idx = i
                break

        if end_idx < 0:
            violations.append(f"{rel}: start marker found but no matching end marker")
            continue

        actual_block = "".join(lines[start_idx : end_idx + 1])
        if not actual_block.endswith("\n"):
            actual_block += "\n"

        if actual_block != canonical:
            # Produce a helpful diff summary
            violations.append(
                f"{rel}: block content differs from canonical.\n"
                f"  expected len={len(canonical)}, actual len={len(actual_block)}\n"
                f"  Run: python tools/contract/sync_interaction_policy.py"
            )

    assert not violations, "\n\n".join(["", *violations, ""])


def test_interaction_policy_block_not_in_protected_region() -> None:
    """The managed block must not be nested inside PROTECTED or SLOW_UPDATE regions."""
    root = repo_root()
    skill_files = _skill_markdown_files(root)
    violations: list[str] = []

    for skill_name, skill_path in skill_files:
        text = skill_path.read_text(encoding="utf-8")
        rel = skill_path.relative_to(root).as_posix()

        if START_MARKER not in text:
            continue  # missing block checked by the other test

        lines = text.splitlines(keepends=True)
        protected = _protected_line_set(lines)

        for i, line in enumerate(lines):
            if line.rstrip("\n") == START_MARKER and i in protected:
                violations.append(
                    f"{rel}:{i + 1}: interaction-policy block start marker is inside "
                    f"a PROTECTED or SLOW_UPDATE region"
                )
                break

    assert not violations, "\n\n".join(["", *violations, ""])
