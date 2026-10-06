#!/usr/bin/env python3
"""Read current project-scoped decision evidence; never run an agent or model."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys


def _text(value, limit):
    return isinstance(value, str) and 1 <= len(value) <= limit


def _validate_visible_fields(payload):
    """Validate frozen v0 display fields; preserve additive service fields."""
    if not _text(payload.get("headline"), 500) or payload.get("confidence") not in ("low", "medium", "high"):
        raise ValueError("Decision headline or confidence is invalid")
    action = payload.get("recommended_action")
    if not isinstance(action, dict) or not _text(action.get("kind"), 100) or not _text(action.get("why"), 500):
        raise ValueError("Decision action is invalid")
    if action.get("config_id") is not None and (not isinstance(action["config_id"], str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", action["config_id"]) is None):
        raise ValueError("Decision configuration identity is invalid")
    for field, members in (("evidence", (("type", 100), ("summary", 500))),
                           ("drilldowns", (("label", 200), ("tool", 100)))):
        values = payload.get(field)
        if not isinstance(values, list) or len(values) > 50 or any(
            not isinstance(item, dict) or any(not _text(item.get(key), limit) for key, limit in members)
            for item in values
        ):
            raise ValueError(f"Decision {field} is invalid")
    warnings = payload.get("warnings")
    if not isinstance(warnings, list) or len(warnings) > 50 or any(not _text(item, 500) for item in warnings):
        raise ValueError("Decision warnings are invalid")


async def read_decision_brief(project_id: str, run_id: str, intent: str, client):
    """Read once from the service and preserve its complete payload."""
    payload = await client.get_run_decision_brief(project_id, run_id, intent=intent)
    if not isinstance(payload, dict):
        raise ValueError("Decision brief must be an object")
    if (payload.get("project_id"), payload.get("run_id"), payload.get("intent")) != (
        project_id, run_id, intent
    ):
        raise ValueError("Decision brief identity does not match the requested project, run and intent")
    required = {"headline", "confidence", "recommended_action", "evidence", "warnings", "drilldowns"}
    if not required.issubset(payload):
        raise ValueError("Decision brief is incomplete")
    _validate_visible_fields(payload)
    # Validate the whole output before anything reaches stdout.
    return json.dumps(payload, ensure_ascii=False, allow_nan=False)


async def _read(args):
    from traigent.cloud.analytics_client import BackendAnalyticsClient

    async with BackendAnalyticsClient() as client:
        return await read_decision_brief(args.project_id, args.run_id, args.intent, client)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--project-id", default=os.environ.get("TRAIGENT_PROJECT_ID"))
    parser.add_argument("--intent", choices=("iterate", "deploy", "debug", "report"), default="iterate")
    args = parser.parse_args(argv)
    if not args.project_id or not args.project_id.strip() or not args.run_id.strip():
        parser.error("a nonempty project ID and run ID are required")
    try:
        output = asyncio.run(_read(args))
        sys.stdout.write(output + "\n")
    except Exception as exc:
        # SDK/network exceptions can include headers or server-controlled bodies.
        # Refuse without printing their contents or falling back to local evidence.
        print(f"Decision verification failed ({type(exc).__name__}); no run was verified.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
