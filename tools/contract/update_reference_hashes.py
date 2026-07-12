#!/usr/bin/env python3
"""Update provenance.json reference_hashes for skills with references/*.md files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def hash_prefix(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def reference_hashes(skill_dir: Path) -> dict[str, str]:
    references_dir = skill_dir / "references"
    return {
        f"references/{path.name}": hash_prefix(path)
        for path in sorted(references_dir.glob("*.md"))
    }


def skill_dirs(root: Path) -> list[Path]:
    skills_root = root / "skills"
    return sorted(
        d
        for d in skills_root.iterdir()
        if d.is_dir()
        and (d / "provenance.json").is_file()
        and (d / "references").is_dir()
    )


def insert_after_doc_hash(
    provenance: dict[str, Any], hashes: dict[str, str]
) -> dict[str, Any]:
    updated: dict[str, Any] = {}
    inserted = False
    for key, value in provenance.items():
        if key == "reference_hashes":
            continue
        updated[key] = value
        if key == "doc_hash":
            updated["reference_hashes"] = hashes
            inserted = True
    if not inserted:
        updated["reference_hashes"] = hashes
    return updated


def update_skill(skill_dir: Path, check: bool) -> bool:
    provenance_path = skill_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    updated = insert_after_doc_hash(provenance, reference_hashes(skill_dir))
    rendered = json.dumps(updated, indent=2) + "\n"
    current = provenance_path.read_text(encoding="utf-8")
    changed = rendered != current
    if changed and not check:
        provenance_path.write_text(rendered, encoding="utf-8")
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Update provenance.json reference_hashes for all skills with a "
            "references/ directory, or for specific skill directories."
        )
    )
    parser.add_argument(
        "skill_dirs",
        nargs="*",
        type=Path,
        help="Optional skill directories to update, e.g. skills/traigent-debugging.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any provenance.json would change.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repo_root()
    targets = args.skill_dirs or skill_dirs(root)
    changed = []
    for target in targets:
        skill_dir = target if target.is_absolute() else root / target
        if not (skill_dir / "provenance.json").is_file():
            raise SystemExit(f"{skill_dir}: missing provenance.json")
        if not (skill_dir / "references").is_dir():
            continue
        if update_skill(skill_dir, args.check):
            changed.append(skill_dir)

    if args.check and changed:
        for skill_dir in changed:
            print(f"stale reference_hashes: {skill_dir.relative_to(root)}")
        return 1

    action = "Would update" if args.check else "Updated"
    print(f"{action} {len(changed)} provenance file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
