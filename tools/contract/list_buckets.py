#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from packaging.version import Version


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit the bucket list as a single-line JSON array instead of one "
            "version per line. Used by CI to fan the buckets out into a "
            "matrix (strategy.matrix.bucket); the default line-per-bucket "
            "output is unchanged and remains what tests/README.md and the "
            "test suite exercise."
        ),
    )
    args = parser.parse_args()

    data: dict[str, Any] = yaml.safe_load(
        (repo_root() / "sync_map.yml").read_text(encoding="utf-8")
    )
    default_floor = str(data["default_min_sdk_version"])
    floors = {default_floor}
    current_release = data.get("current_released_sdk_version")
    if current_release:
        floors.add(str(current_release))
    for entry in (data.get("skills") or {}).values():
        if isinstance(entry, dict) and entry.get("min_sdk_version"):
            floors.add(str(entry["min_sdk_version"]))

    ordered = sorted(floors, key=Version)
    if args.json:
        print(json.dumps(ordered))
    else:
        for floor in ordered:
            print(floor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
