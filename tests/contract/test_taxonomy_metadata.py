from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "catalog" / "skills.json").read_text(encoding="utf-8"))


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    _, raw, _ = text.split("---", 2)
    return yaml.safe_load(raw)


def test_catalog_matches_public_skill_directories() -> None:
    expected = {item["name"] for item in CATALOG["skills"]}
    actual = {path.name for path in (ROOT / "skills").iterdir() if path.is_dir()}
    assert actual == expected


def test_catalog_tracks_plugin_version() -> None:
    plugin = json.loads(
        (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert CATALOG["plugin_version"] == plugin["version"]


def _is_public_skill_name(name: str) -> bool:
    # Every skill is traigent-<lifecycle>-<capability>, with one exception: the
    # short entry that carries the plugin's own name (owner decision on
    # traigent-skills#75, 2026-10-08), so `traigent:traigent` is the one start
    # command. No other bare or non-prefixed name is accepted.
    return name.startswith("traigent-") or name == CATALOG["plugin"]


def test_skill_name_rule_admits_only_the_plugin_named_entry() -> None:
    assert _is_public_skill_name("traigent-boost-agent")
    assert _is_public_skill_name(CATALOG["plugin"])
    for name in ("traigentx", "boost-agent", "traigent_", "start", ""):
        assert not _is_public_skill_name(name), name


def test_public_skills_declare_audience_topic_and_stage() -> None:
    for item in CATALOG["skills"]:
        name = item["name"]
        assert _is_public_skill_name(name)
        data = _frontmatter(ROOT / "skills" / name / "SKILL.md")
        assert data["name"] == name
        metadata = data["metadata"]
        assert metadata["traigent-audience"] == CATALOG["audience"]
        assert metadata["traigent-topic"] == CATALOG["topic"]
        assert metadata["traigent-stage"] == item["stage"]
        assert metadata["traigent-maturity"] == item["maturity"]
