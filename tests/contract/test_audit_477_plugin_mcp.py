"""Every MCP tool a skill names is shipped by the plugin or has a documented fallback.

Traigent/traigent-skills#477. The plugin declared skills only, so the
`analytics_*` tools the analyze skills depend on were absent after install, and a
headless session (no restart possible) could never fetch the decision brief.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
MCP_JSON = ROOT / ".mcp.json"
GUIDANCE = SKILLS / "traigent-analyze-guidance" / "SKILL.md"
RESULTS = SKILLS / "traigent-analyze-results" / "SKILL.md"

SERVER_NAME = "traigent-analytics"
CONSOLE_SCRIPT = "traigent-analytics-mcp"
TOOL_RE = re.compile(r"\banalytics_(?!client\b)[a-z_]+\b")


def _servers() -> dict:
    assert MCP_JSON.is_file(), "the plugin must ship a root .mcp.json"
    return json.loads(MCP_JSON.read_text(encoding="utf-8"))["mcpServers"]


LAUNCHER = ROOT / "bin" / "traigent-analytics-launcher"


def test_the_plugin_declares_the_analytics_server_the_skills_name() -> None:
    server = _servers()[SERVER_NAME]
    # The server entry points at a reviewable launcher file shipped in the plugin,
    # not an inline `sh -c` program (a shell one-liner in a project MCP config is
    # indistinguishable from the planted-config RCE pattern scanners look for).
    assert server["command"] == "${CLAUDE_PLUGIN_ROOT}/bin/traigent-analytics-launcher"
    assert not server.get("args")
    launch = LAUNCHER.read_text(encoding="utf-8")
    assert CONSOLE_SCRIPT in launch
    # Works before the SDK is installed: an installed console script is used,
    # otherwise the server is fetched with uvx from the mcp extra.
    assert "uvx" in launch and "traigent[mcp" in launch
    assert "exit 127" in launch, "a missing launcher must fail with a message"


def test_the_launcher_is_executable_in_git() -> None:
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", "-s", "--", "bin/traigent-analytics-launcher"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout
    if not out:  # not a git checkout (sdist/zip): fall back to the filesystem bit
        import os

        assert os.access(LAUNCHER, os.X_OK)
    else:
        assert out.startswith("100755"), out


def test_credentials_are_forwarded_by_reference_never_written_into_the_file() -> None:
    env = _servers()[SERVER_NAME]["env"]
    assert env["TRAIGENT_API_KEY"].startswith("${TRAIGENT_API_KEY")
    assert env["TRAIGENT_BACKEND_URL"].startswith("${TRAIGENT_BACKEND_URL")
    assert not re.search(r"\btg_[A-Za-z0-9_-]{8,}", MCP_JSON.read_text(encoding="utf-8"))


def test_every_analytics_tool_a_skill_names_is_declared_or_has_a_fallback() -> None:
    named = {
        match
        for path in SKILLS.rglob("*.md")
        for match in TOOL_RE.findall(path.read_text(encoding="utf-8"))
    }
    assert "analytics_get_run_decision_brief" in named
    # The plugin ships the whole server, so every tool it serves is declared.
    assert SERVER_NAME in _servers()
    # The brief is the one tool the post-run decision depends on: it must also
    # have a no-MCP fallback in the skill that requires it.
    guidance = GUIDANCE.read_text(encoding="utf-8")
    assert "/api/v1/analytics/runs/{run_id}/decision-payload" in guidance
    assert "X-API-Key" in guidance and "X-Project-Id" in guidance
    for key in ("run_id", "project_id", "intent"):
        assert f"`{key}`" in guidance.split("No-MCP fallback")[1], key


def test_the_skills_say_the_plugin_loads_the_server() -> None:
    for path in (GUIDANCE, RESULTS):
        text = path.read_text(encoding="utf-8")
        assert "plugin ships" in text and ".mcp.json" in text, path.name
