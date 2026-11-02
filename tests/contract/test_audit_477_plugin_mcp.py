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


def _run_launcher(tmp_path: Path, stubs: tuple[str, ...]):
    import subprocess

    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in stubs:
        stub = bindir / name
        stub.write_text(f'#!/bin/sh\necho "ran:{name}:$*"\n', encoding="utf-8")
        stub.chmod(0o755)
    env = {"PATH": str(bindir)}
    return subprocess.run(
        ["/bin/sh", str(LAUNCHER)], env=env, capture_output=True, text=True, check=False,
        timeout=20,
    )


def test_the_launcher_prefers_the_installed_console_script(tmp_path: Path) -> None:
    out = _run_launcher(tmp_path, ("traigent-analytics-mcp", "uvx"))
    assert out.returncode == 0 and out.stdout.strip() == "ran:traigent-analytics-mcp:"


def test_the_launcher_falls_back_to_uvx_from_the_mcp_extra(tmp_path: Path) -> None:
    out = _run_launcher(tmp_path, ("uvx",))
    assert out.returncode == 0
    assert out.stdout.strip() == "ran:uvx:--from traigent[mcp,analytics]>=0.24.0 traigent-analytics-mcp"


def test_the_launcher_fails_with_a_message_when_neither_exists(tmp_path: Path) -> None:
    out = _run_launcher(tmp_path, ())
    assert out.returncode == 127
    assert "install traigent[mcp,analytics] or uv" in out.stderr


def test_the_launcher_is_posix_sh() -> None:
    assert LAUNCHER.read_text(encoding="utf-8").startswith("#!/bin/sh\n")


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
