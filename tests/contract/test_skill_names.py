"""Contract tests for the skill-name taxonomy after the 2026-07 consolidation.

Guards against stale skill-name prose (renamed/merged dirs referenced by their
old name), retired names leaking back in, wrong backend hosts/key prefixes in
skill text, and sync_map.yml drifting from the skills/ directory listing.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

SKILL_TOKEN_RE = re.compile(r"\btraigent-[a-z0-9]+(?:-[a-z0-9]+)*\b")

# Tokens that match the `traigent-<word>[-<word>...]` shape but are NOT skill
# directory names — packages, repo URLs, project strings, anchors, etc. Each
# entry is commented with why it is not a skill.
ALLOWLIST = {
    # Python package / MCP server, not a skill dir.
    "traigent-analytics",
    # Integration name referenced in traigent-setup-integrations references
    # (the LangChain integration path), not a skill dir.
    "traigent-langchain",
    # Sibling repo (traigent-smartopt), referenced by name/URL, not a skill dir.
    "traigent-smartopt",
    # wandb project string used in traigent-setup-integrations references, not
    # a skill dir.
    "traigent-optimization",
    # Substring captured out of the markdown anchor
    # `#get-your-traigent-api-key`; not a skill dir.
    "traigent-api-key",
    # Workflow/template identifier (`traigent-sdk-caller.yml`), not a skill dir.
    "traigent-sdk-caller",
    # This repo's own name, referenced in prose/URLs (e.g.
    # `Traigent/traigent-skills`), not a skill dir.
    "traigent-skills",
    # Suggested GitHub Actions workflow filename
    # (`.github/workflows/traigent-safety-gate.yml`) in traigent-ci-safety-gate's
    # reference doc — a filename for the user's own repo, not a skill dir.
    "traigent-safety-gate",
}

# The 16 retired names from the 2026-07 taxonomy consolidation (12 renames +
# 4 skills merged away). The bare `traigent` name folded into
# traigent-boost-agent is NOT included here because "traigent" alone doesn't
# match the \btraigent-[a-z0-9]+(?:-[a-z0-9]+)*\b token shape these names use,
# and it is a substring of every other skill name — it was verified manually
# during the consolidation instead (git grep for "the `traigent` skill" and
# ../traigent/SKILL.md).
RETIRED_NAMES = {
    "traigent-quickstart",
    "traigent-decorator-setup",
    "traigent-curate-dataset",
    "traigent-choose-metric",
    "traigent-build-evaluator",
    "traigent-evaluator-audit",
    "traigent-configuration-space",
    "traigent-composite-knobs",
    "traigent-run-optimization",
    "traigent-text2sql-optimize",
    "traigent-run-plan",
    "traigent-next-run",
    "traigent-iterate",
    "traigent-reflect-hard-examples",
    "show-significant-tuned-variables",
    "traigent-integrations",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _skill_dir_names(root: Path) -> set[str]:
    return {p.name for p in (root / "skills").iterdir() if p.is_dir()}


def test_prose_skill_references_exist() -> None:
    """Every traigent-<word>... token in skills/**/*.md is a real skill dir or allowlisted."""
    root = repo_root()
    skill_dirs = _skill_dir_names(root)
    bad: dict[str, set[str]] = {}
    for md_path in (root / "skills").rglob("*.md"):
        text = md_path.read_text(encoding="utf-8")
        for token in SKILL_TOKEN_RE.findall(text):
            if token in skill_dirs or token in ALLOWLIST:
                continue
            bad.setdefault(str(md_path.relative_to(root)), set()).add(token)
    assert not bad, (
        "Found traigent-* tokens in skill prose that are neither an existing "
        "skills/ dir nor allowlisted (fix the stale reference or extend "
        f"ALLOWLIST with justification): {bad}"
    )


README_RENAME_NOTE_RE = re.compile(
    r"(?ms)^### Renamed in the 2026-07 consolidation.*?(?=^## |\Z)"
)


def test_retired_names_absent() -> None:
    """Retired skill names must not appear anywhere in the live surface (docs/ excluded — historical)."""
    root = repo_root()
    this_file = Path(__file__).resolve()

    # provenance.json genesis entries are an append-only audit trail: the
    # merge-target skills' genesis note records the retired names they were
    # merged FROM as historical lineage (same rationale as the docs/
    # carve-out below), e.g. skills/traigent-analyze-guidance/provenance.json.
    provenance_files = {
        p.resolve() for p in (root / "skills").rglob("provenance.json")
    }

    search_paths: list[Path] = []
    search_paths.extend((root / "skills").rglob("*"))
    search_paths.append(root / "README.md")
    search_paths.append(root / "sync_map.yml")
    search_paths.append(root / "SYNC_MAP.md")
    search_paths.extend((root / "tools").rglob("*"))

    retired_patterns = {
        name: re.compile(r"\b" + re.escape(name) + r"\b") for name in RETIRED_NAMES
    }

    hits: dict[str, list[str]] = {}
    for path in search_paths:
        if not path.is_file():
            continue
        if path.resolve() == this_file:
            continue
        if path.resolve() in provenance_files:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if path.resolve() == (root / "README.md").resolve():
            # The "Renamed in the 2026-07 consolidation" note is a deliberate
            # old->new mapping table — historical record, same rationale as
            # the docs/ carve-out.
            text = README_RENAME_NOTE_RE.sub("", text)
        for name, pattern in retired_patterns.items():
            if pattern.search(text):
                hits.setdefault(str(path.relative_to(root)), []).append(name)

    assert not hits, f"Retired skill names found outside docs/ (historical): {hits}"


def test_no_wrong_backend_hosts_or_key_prefixes() -> None:
    """Skill text must not teach the wrong backend host or a fake API key prefix."""
    root = repo_root()
    offenders: dict[str, list[str]] = {}
    for md_path in (root / "skills").rglob("*"):
        if not md_path.is_file():
            continue
        try:
            text = md_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found = []
        if "api.traigent.ai" in text:
            found.append("api.traigent.ai")
        if "trg_" in text:
            found.append("trg_")
        if found:
            offenders[str(md_path.relative_to(root))] = found
    assert not offenders, f"Found disallowed host/key-prefix strings: {offenders}"


def test_sync_map_matches_skill_dirs() -> None:
    """sync_map.yml's skills: keys must exactly match the skills/ directory names."""
    root = repo_root()
    data = yaml.safe_load((root / "sync_map.yml").read_text(encoding="utf-8"))
    mapped = set((data.get("skills") or {}).keys())
    skill_dirs = _skill_dir_names(root)
    assert mapped == skill_dirs, (
        f"sync_map.yml skills keys != skills/ dirs. "
        f"Only in sync_map.yml: {mapped - skill_dirs}; "
        f"Only in skills/: {skill_dirs - mapped}"
    )
