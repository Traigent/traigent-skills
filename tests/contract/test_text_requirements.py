from __future__ import annotations

import re
from pathlib import Path

from packaging.version import Version

from .facts import ContractFact
from .conftest import skill_floor


def test_skills_with_traigent_imports_resolve_to_floor(
    all_contract_facts: tuple[ContractFact, ...],
    sync_map: dict,
) -> None:
    skills_with_imports = {
        fact.skill
        for fact in all_contract_facts
        if fact.kind in {"import", "symbol"}
        and fact.module
        and (fact.module == "traigent" or fact.module.startswith("traigent."))
    }
    for skill in sorted(skills_with_imports):
        assert skill_floor(sync_map, skill), (
            f"{skill} teaches Traigent imports but has no floor/default"
        )


def test_sdk_floors_are_pep440(sync_map: dict) -> None:
    Version(str(sync_map["default_min_sdk_version"]))
    for skill, entry in (sync_map.get("skills") or {}).items():
        if entry.get("min_sdk_version"):
            Version(str(entry["min_sdk_version"])), skill


def test_skills_above_default_state_required_sdk_in_when_to_use(
    repo_root: Path, sync_map: dict
) -> None:
    default_floor = Version(str(sync_map["default_min_sdk_version"]))
    for skill, entry in (sync_map.get("skills") or {}).items():
        floor = entry.get("min_sdk_version")
        if not floor or Version(str(floor)) <= default_floor:
            continue
        skill_text = (repo_root / "skills" / skill / "SKILL.md").read_text(
            encoding="utf-8"
        )
        when_to_use = _section(skill_text, "## When to Use")
        required = f"Requires `traigent>={floor}`"
        assert required in when_to_use, (
            f"{skill} floor {floor} requires literal {required!r} in When to Use"
        )


REMOVED_EXECUTION_VOCABULARY = {
    "execution_mode": re.compile(r"\bexecution_mode\b", re.IGNORECASE),
    "privacy_enabled": re.compile(r"\bprivacy_enabled\b", re.IGNORECASE),
    "edge_analytics": re.compile(r"\bedge_analytics\b", re.IGNORECASE),
    "hybrid_api": re.compile(r"\bhybrid_api\b", re.IGNORECASE),
    "attribute injection": re.compile(r"\battribute[-_\s]+injection\b", re.IGNORECASE),
    "JS bridge": re.compile(r"\bjs[-_\s]+bridge\b", re.IGNORECASE),
}


def test_skills_do_not_reintroduce_removed_execution_vocabulary(
    repo_root: Path,
) -> None:
    violations: list[str] = []
    for path in sorted((repo_root / "skills").glob("**/*.md")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(repo_root).as_posix()
        for label, pattern in REMOVED_EXECUTION_VOCABULARY.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(
                    f"{rel}:{line}: removed execution vocabulary {label!r}"
                )
    assert not violations, "\n".join(violations)


def _section(text: str, heading: str) -> str:
    lines = text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        return ""
    collected: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        collected.append(line)
    return "\n".join(collected)
