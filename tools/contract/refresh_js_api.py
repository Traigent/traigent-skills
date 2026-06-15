#!/usr/bin/env python3
"""Refresh the vendored traigent-js public API snapshot.

Generates ``tests/data/js_api_snapshot.json`` from traigent-js's committed
``tests/integration/fixtures/api-surface.snapshot.json`` (which is itself gated
by the JS repo's ``api-surface.test.ts`` against the built ``dist/*.d.ts``).
We re-key it from the test's camelCase subpath keys to the real ``@traigent/sdk``
import paths that skills actually write, so the JS skill contract can validate
``import { X } from '@traigent/sdk[/sub]'`` against the real exported surface.

Usage (from the traigent-skills repo root):

    python tools/contract/refresh_js_api.py --js-repo /path/to/traigent-js --ref origin/main
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

REPO_SLUG = "Traigent/traigent-js"
DEFAULT_OUT = Path("tests/data/js_api_snapshot.json")
SNAPSHOT_REL = "tests/integration/fixtures/api-surface.snapshot.json"

# api-surface.snapshot.json key -> the import path users write. Derived from the
# JS repo's api-surface.test.ts SUBPATHS + package.json "exports".
KEY_TO_SUBPATH = {
    "root": "@traigent/sdk",
    "openai": "@traigent/sdk/openai",
    "langchain": "@traigent/sdk/langchain",
    "vercelAi": "@traigent/sdk/vercel-ai",
    "routing": "@traigent/sdk/routing",
    "seamless": "@traigent/sdk/babel-plugin-seamless",
    "projects": "@traigent/sdk/projects",
    "prompts": "@traigent/sdk/prompts",
    "evaluation": "@traigent/sdk/evaluation",
    "observability": "@traigent/sdk/observability",
    "coreMetrics": "@traigent/sdk/core-metrics",
    "admin": "@traigent/sdk/admin",
    "schema": "@traigent/sdk/schema",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the vendored traigent-js API snapshot.")
    parser.add_argument("--js-repo", type=Path, required=True, help="Path to a traigent-js checkout.")
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    snapshot = build_snapshot(js_repo=args.js_repo, ref=args.ref)
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(len(v) for v in snapshot["exports"].values())
    print(
        f"wrote {out.as_posix()} with {len(snapshot['exports'])} subpaths / {total} symbols "
        f"from {snapshot['generated_from']['commit_sha']}",
    )
    return 0


def build_snapshot(*, js_repo: Path, ref: str) -> dict[str, Any]:
    source = json.loads((js_repo / SNAPSHOT_REL).read_text(encoding="utf-8"))
    exports: dict[str, list[str]] = {}
    for key, symbols in source.items():
        subpath = KEY_TO_SUBPATH.get(key)
        if subpath is None:
            # New subpath added upstream — surface it rather than silently drop.
            subpath = f"@traigent/sdk/{key}"
            print(f"warning: unknown api-surface key '{key}'; mapped to {subpath}")
        exports[subpath] = sorted(str(s) for s in symbols)

    return {
        "generated_from": {
            "repo": REPO_SLUG,
            "ref": ref,
            "commit_sha": _commit_sha(js_repo, ref),
        },
        "exports": exports,
    }


def _commit_sha(repo: Path, ref: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(repo), "rev-parse", ref], text=True).strip()
    except Exception:
        try:
            return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        except Exception:
            return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
