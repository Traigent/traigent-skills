"""Contract test: the plugin/marketplace manifests must agree with each other.

The repo ships three thin manifests over one shared ``skills/`` payload:

- ``.claude-plugin/plugin.json``       (Claude Code plugin)
- ``.claude-plugin/marketplace.json``  (Claude Code marketplace; also read by
  GitHub Copilot CLI)
- ``.codex-plugin/plugin.json``        (OpenAI Codex plugin)
- ``.agents/plugins/marketplace.json`` (OpenAI Codex marketplace)

A description or version bumped in one manifest but not the others ships a
silently inconsistent listing, so identity fields are pinned to each other
here.
"""

from __future__ import annotations

import json
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load(relpath: str) -> dict:
    path = repo_root() / relpath
    assert path.is_file(), f"missing manifest: {relpath}"
    return json.loads(path.read_text(encoding="utf-8"))


def _claude_plugin() -> dict:
    return _load(".claude-plugin/plugin.json")


def _claude_marketplace_entry() -> dict:
    marketplace = _load(".claude-plugin/marketplace.json")
    plugins = marketplace.get("plugins", [])
    assert len(plugins) == 1, "expected exactly one plugin entry in .claude-plugin/marketplace.json"
    return plugins[0]


def _codex_plugin() -> dict:
    return _load(".codex-plugin/plugin.json")


def _codex_marketplace_entry() -> dict:
    marketplace = _load(".agents/plugins/marketplace.json")
    plugins = marketplace.get("plugins", [])
    assert len(plugins) == 1, "expected exactly one plugin entry in .agents/plugins/marketplace.json"
    return plugins[0]


def test_plugin_identity_agrees_across_manifests() -> None:
    manifests = {
        ".claude-plugin/plugin.json": _claude_plugin(),
        ".claude-plugin/marketplace.json plugins[0]": _claude_marketplace_entry(),
        ".codex-plugin/plugin.json": _codex_plugin(),
        ".agents/plugins/marketplace.json plugins[0]": _codex_marketplace_entry(),
    }
    names = {where: manifest["name"] for where, manifest in manifests.items()}
    assert set(names.values()) == {"traigent"}, names

    versioned = {
        where: manifest["version"]
        for where, manifest in manifests.items()
        if "version" in manifest
    }
    assert len(set(versioned.values())) == 1, f"version drift: {versioned}"

    described = {
        where: manifest["description"]
        for where, manifest in manifests.items()
        if "description" in manifest
    }
    assert len(set(described.values())) == 1, f"description drift: {described}"


def test_keywords_and_license_agree() -> None:
    claude = _claude_plugin()
    codex = _codex_plugin()
    assert claude["keywords"] == codex["keywords"]
    assert claude["license"] == codex["license"] == "Apache-2.0"


def test_codex_marketplace_policy_is_valid() -> None:
    entry = _codex_marketplace_entry()
    policy = entry["policy"]
    assert policy["installation"] == "AVAILABLE"
    assert policy["authentication"] in {"ON_INSTALL", "ON_USE"}
    source = entry["source"]
    assert source["source"] == "local"
    assert source["path"].startswith("./")


def test_category_only_in_marketplace_entries() -> None:
    # `claude plugin validate` warns on category in plugin.json — keep it out.
    assert "category" not in _claude_plugin()
    assert _claude_marketplace_entry()["category"] == "agent-optimization"
    assert _codex_marketplace_entry()["category"] == "agent-optimization"


def test_readme_documents_plugin_install() -> None:
    readme = (repo_root() / "README.md").read_text(encoding="utf-8")
    for command in (
        "/plugin marketplace add Traigent/traigent-skills",
        "copilot plugin marketplace add Traigent/traigent-skills",
    ):
        assert command in readme, f"README.md is missing plugin install command: {command}"
    # Note: "codex plugin marketplace add" is intentionally absent from the main install
    # section because Codex does not auto-load skills from the marketplace. Users are
    # directed to the "Using with Codex CLI" section instead (issue #205).
