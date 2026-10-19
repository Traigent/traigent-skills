"""Issue #448: public pages must not link or name non-public repositories.

The forbidden names are assembled from fragments so this file never spells a
non-public repository or plugin name literally (it is itself scanned below).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_PRIVATE_SKILLS_REPO = "agents" + "-" + "skills"
_PRIVATE_PLUGINS = ("traigent-" + "coding-agents", "traigent-" + "spine")
_PRIVATE_JS_REPO = "Traigent/" + "traigent" + "-js"
_PRIVATE_JS_TRACKER = "traigent" + "-js" + "#"

# Tracked publication files: the public pages, every skill document and the
# contract tests (including this file).
_PUBLICATION_GLOBS = (
    "README.md",
    "SYNC_MAP.md",
    "skills/**/*.md",
    "tests/contract/*.py",
)
# The JS skill's clone URL is tracked separately in #30.
_JS_SKILL = ROOT / "skills" / "traigent-js" / "SKILL.md"


def _publication_files() -> list[Path]:
    seen: dict[Path, None] = {}
    for pattern in _PUBLICATION_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            seen[path] = None
    return list(seen)


def test_publication_files_do_not_reference_non_public_repos() -> None:
    always = (_PRIVATE_SKILLS_REPO, *_PRIVATE_PLUGINS, _PRIVATE_JS_TRACKER)
    hits = []
    for path in _publication_files():
        text = path.read_text(encoding="utf-8")
        needles = always if path == _JS_SKILL else (*always, _PRIVATE_JS_REPO)
        hits += [f"{path.relative_to(ROOT)}: forbidden name #{i}" for i, n in enumerate(needles) if n in text]
    assert not hits, hits


def test_scan_covers_this_file_and_the_public_pages() -> None:
    names = {p.name for p in _publication_files()}
    assert {"README.md", "SYNC_MAP.md", Path(__file__).name} <= names
