"""Contract test: every on-disk skill must appear in the README Skills catalog."""

from __future__ import annotations

import re
from pathlib import Path


SKILL_LINK_RE = re.compile(r"\[([^\]]+)\]\(skills/([^/)]+)/\)")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _skill_dirs(root: Path) -> list[Path]:
    skills_root = root / "skills"
    return sorted(
        skill_dir
        for skill_dir in skills_root.iterdir()
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file()
    )


def _readme_skills_table_links(root: Path) -> set[str]:
    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8")

    skills_heading = re.search(r"(?m)^## Skills\s*$", text)
    assert skills_heading, "README.md is missing the '## Skills' section"

    next_heading = re.search(r"(?m)^##\s+", text[skills_heading.end() :])
    skills_section = (
        text[skills_heading.end() :]
        if next_heading is None
        else text[skills_heading.end() : skills_heading.end() + next_heading.start()]
    )

    return {match.group(2) for match in SKILL_LINK_RE.finditer(skills_section)}


def test_every_skill_dir_is_listed_in_readme_skills_table() -> None:
    """Every skills/*/SKILL.md has a matching skills/<name>/ link in README.md."""
    root = repo_root()
    skill_names = [skill_dir.name for skill_dir in _skill_dirs(root)]
    catalog_links = _readme_skills_table_links(root)

    assert skill_names, "No SKILL.md files found under skills/"

    missing = [skill_name for skill_name in skill_names if skill_name not in catalog_links]
    assert not missing, "README.md Skills table is missing: " + ", ".join(missing)
