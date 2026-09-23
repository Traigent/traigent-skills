"""The documented environment must keep ``import litellm`` off the network (traigent-skills#355).

LiteLLM downloads its pricing map from GitHub on import unless
``LITELLM_LOCAL_MODEL_COST_MAP`` is already set, and ``import traigent`` does not set
it. The environment-variables reference used to say the SDK sets it, so a customer's
own ``import traigent; import litellm`` script, run in the documented environment,
made an outbound request even with ``offline=True``.

The test reads the documented environment from the reference's table row and runs
``import traigent, litellm`` under a ``socket.getaddrinfo`` spy that records the
lookup and refuses it, so nothing leaves the machine.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from .test_audit_349_fenced_blocks import skip_unless_current_released_sdk

ENV_DOC = "skills/traigent-setup-quickstart/references/environment-variables.md"
VAR = "LITELLM_LOCAL_MODEL_COST_MAP"
SPY = """
import socket
def _refuse(host, *args, **kwargs):
    print("DNS LOOKUP", host, flush=True)
    raise OSError("network disabled by test")
socket.getaddrinfo = _refuse
import traigent
import litellm
print("IMPORTED", flush=True)
"""


def _documented_env(row: str) -> dict[str, str]:
    """Environment a reader ends up with by following the table row."""
    if "set by the SDK" in row:
        return {}  # the row tells the reader the SDK handles it: nothing to set
    match = re.search(rf"Set `{VAR}=(\w+)`", row)
    assert match, f"{VAR} row names neither the SDK default nor a value to set: {row}"
    return {VAR: match.group(1)}


def _table_row(text: str) -> str:
    row = re.search(rf"^\| `{VAR}`.*$", text, re.M)
    assert row, f"no {VAR} row in {ENV_DOC}"
    return row.group(0)


def _lookups(extra_env: dict[str, str]) -> list[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {VAR, "TRAIGENT_API_KEY", "OPENAI_API_KEY", "TRAIGENT_MOCK_LLM"}
    }
    env.update(extra_env)
    env["TRAIGENT_OFFLINE_MODE"] = "true"
    result = subprocess.run(
        [sys.executable, "-c", SPY],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert "IMPORTED" in result.stdout, result.stdout + result.stderr
    return [line for line in result.stdout.splitlines() if line.startswith("DNS")]


def test_documented_environment_imports_litellm_without_a_lookup(
    repo_root: Path, sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(
        sync_map, sdk_version_label, "the LiteLLM cost-map guidance"
    )
    row = _table_row((repo_root / ENV_DOC).read_text(encoding="utf-8"))
    lookups = _lookups(_documented_env(row))
    assert not lookups, (
        f"following {ENV_DOC} ({VAR} row), `import traigent, litellm` still "
        f"looks up the network: {lookups}"
    )


def test_cost_map_egress_check_has_teeth(
    sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(
        sync_map, sdk_version_label, "the LiteLLM cost-map guidance"
    )
    assert _documented_env("| `X` | `True` (set by the SDK) | ... |") == {}
    assert _documented_env(f"| x | Set `{VAR}=True` in the environment |") == {
        VAR: "True"
    }
    assert _lookups({}), "unset variable no longer triggers a lookup; revisit #355"
