#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from packaging.version import Version


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    data: dict[str, Any] = yaml.safe_load((repo_root() / "sync_map.yml").read_text(encoding="utf-8"))
    default_floor = str(data["default_min_sdk_version"])
    floors = {default_floor}
    for entry in (data.get("skills") or {}).values():
        if isinstance(entry, dict) and entry.get("min_sdk_version"):
            floors.add(str(entry["min_sdk_version"]))

    for floor in sorted(floors, key=Version):
        print(floor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
