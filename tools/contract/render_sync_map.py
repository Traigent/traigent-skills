#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


HEADER = "<!-- GENERATED from sync_map.yml by tools/contract/render_sync_map.py — edit sync_map.yml -->"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_sync_map(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"{path} did not contain a YAML mapping")
    return data


def _dependency_items(entry: dict[str, Any]) -> list[str]:
    items: list[str] = []
    items.extend(entry.get("sdk_paths") or [])
    items.extend(entry.get("docs") or [])
    return items


def render(data: dict[str, Any]) -> str:
    skills = data.get("skills") or {}
    if not isinstance(skills, dict):
        raise SystemExit("sync_map.yml field 'skills' must be a mapping")

    lines = [
        HEADER,
        "",
        "# Skill-to-SDK Sync Map",
        "",
        "When SDK source files change (in the [`Traigent`](https://github.com/Traigent/Traigent) Python SDK repo or [`traigent-js`](https://github.com/Traigent/traigent-js) JavaScript/TypeScript SDK repo), review the corresponding skills here for accuracy.",
        "",
        "| Skill | SDK Source Dependencies |",
        "|-------|----------------------|",
    ]

    for skill_name, entry in skills.items():
        if not isinstance(entry, dict):
            raise SystemExit(f"skill entry {skill_name!r} must be a mapping")
        deps = ", ".join(f"`{item}`" for item in _dependency_items(entry))
        lines.append(f"| `{skill_name}` | {deps} |")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render SYNC_MAP.md from sync_map.yml.")
    parser.add_argument("--check", action="store_true", help="fail if SYNC_MAP.md is not current")
    parser.add_argument("--write", action="store_true", help="write rendered output to SYNC_MAP.md")
    args = parser.parse_args()

    root = repo_root()
    rendered = render(load_sync_map(root / "sync_map.yml"))
    target = root / "SYNC_MAP.md"

    if args.check:
        current = target.read_text(encoding="utf-8")
        if current != rendered:
            raise SystemExit("SYNC_MAP.md is out of sync with sync_map.yml")
        return 0

    if args.write:
        target.write_text(rendered, encoding="utf-8")
        return 0

    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
