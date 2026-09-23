"""The analyze skills must say how to install and register the analytics MCP (#314).

Both analyze skills make the ``traigent-analytics`` MCP server their default
cloud path (``analytics_get_*`` tools), but the server's console command exits
on a plain ``pip install traigent`` and needs the ``mcp`` extra, and the
Pareto recipe's ``to_aggregated_dataframe()`` needs pandas from the
``analytics`` extra. These tests fail when a skill that calls the tools lacks
the install and registration line, and pin the SDK packaging facts the text
relies on against the installed wheel.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

import pytest

MCP_SKILLS = (
    Path("skills/traigent-analyze-results/SKILL.md"),
    Path("skills/traigent-analyze-guidance/SKILL.md"),
    Path("skills/traigent-analyze-results/references/mcp-analytics-tools.md"),
)


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.mark.parametrize("rel", MCP_SKILLS, ids=lambda p: p.as_posix())
def test_skill_calling_analytics_tools_names_install_and_registration(
    repo_root: Path, rel: Path
) -> None:
    text = _flat(repo_root / rel)
    assert "analytics_get_" in text, f"{rel}: expected to call analytics_get_* tools"
    assert "traigent[mcp" in text, f"{rel}: must name the traigent[mcp] extra"
    assert "`traigent-analytics-mcp`" in text, (
        f"{rel}: must name the traigent-analytics-mcp command"
    )
    assert re.search(r"regist\w*", text, re.IGNORECASE), (
        f"{rel}: must say how to register the server with the coding assistant"
    )


def test_results_prerequisites_show_a_registration_entry(repo_root: Path) -> None:
    text = (repo_root / MCP_SKILLS[0]).read_text(encoding="utf-8")
    assert "### Prerequisites (one time)" in text
    assert (
        '{"mcpServers": {"traigent-analytics": {"command": "traigent-analytics-mcp"}}}'
        in text
    )


def test_pareto_recipe_names_the_pandas_extra(repo_root: Path) -> None:
    text = (repo_root / MCP_SKILLS[0]).read_text(encoding="utf-8")
    section = text.split("## The Quality / Cost / Latency Trade-off", 1)[1]
    recipe_at = section.index("to_aggregated_dataframe(primary_objective")
    assert 'pip install "traigent[analytics]>=0.19"' in section[:recipe_at]


def test_mcp_unreachable_fallback_is_unchanged(repo_root: Path) -> None:
    text = _flat(repo_root / MCP_SKILLS[0])
    assert (
        "**If the call itself fails or the `traigent-analytics` MCP server is unreachable** "
        "(as opposed to the tool returning `ok=False` or an empty payload for a real portal "
        "run), do not retry it silently or fabricate a brief."
    ) in text
    assert (
        "For a portal-tracked run, say the analytics service is unreachable and fall back to "
        "the portal deep-link."
    ) in text


def test_installed_sdk_packaging_matches_the_prerequisites() -> None:
    try:
        dist = metadata.distribution("traigent")
    except metadata.PackageNotFoundError:
        pytest.skip("traigent SDK not installed")
    scripts = {ep.name for ep in dist.entry_points if ep.group == "console_scripts"}
    assert "traigent-analytics-mcp" in scripts
    extras = set(dist.metadata.get_all("Provides-Extra") or [])
    assert {"mcp", "analytics", "recommended"} <= extras
    requires = [req.replace(" ", "") for req in dist.requires or []]

    def needs(extra: str, prefix: str) -> bool:
        return any(
            req.startswith(prefix) and f'extra=="{extra}"' in req for req in requires
        )

    assert needs("mcp", "mcp")
    assert needs("analytics", "pandas")
    recommended = next(
        req
        for req in requires
        if req.startswith("traigent[") and 'extra=="recommended"' in req
    )
    bundled = set(recommended.split("[", 1)[1].split("]", 1)[0].split(","))
    assert "analytics" in bundled
    assert "hybrid" in bundled and needs("hybrid", "mcp"), (
        "the prerequisites say traigent[recommended] includes the MCP dependency"
    )
