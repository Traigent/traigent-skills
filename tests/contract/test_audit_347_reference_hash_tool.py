"""Contract test: the reference-hash tool reports only real provenance changes.

``tools/contract/update_reference_hashes.py --check`` must pass on a tree whose
reference hashes are current, whichever way each provenance.json spells its
non-ASCII text (raw UTF-8 or ``\\uXXXX`` escapes), and a rewrite must keep that
spelling so a hash refresh is not a whole-file reformat.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tools" / "contract" / "update_reference_hashes.py"


def _tool():
    spec = importlib.util.spec_from_file_location("update_reference_hashes", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_passes_on_the_committed_tree() -> None:
    result = subprocess.run(
        [sys.executable, str(TOOL), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("escaped", [False, True])
def test_refresh_keeps_the_files_spelling(tmp_path: Path, escaped: bool) -> None:
    tool = _tool()
    skill = tmp_path / "skill"
    (skill / "references").mkdir(parents=True)
    (skill / "references" / "a.md").write_text("a\n", encoding="utf-8")
    provenance = {
        "doc_hash": "0" * 16,
        "reference_hashes": {"references/a.md": "stale"},
        "entries": [{"note": "before — after § 1"}],
    }
    path = skill / "provenance.json"
    path.write_text(
        json.dumps(provenance, indent=2, ensure_ascii=escaped) + "\n", encoding="utf-8"
    )

    assert tool.update_skill(skill, check=True) is True
    assert tool.update_skill(skill, check=False) is True
    rewritten = path.read_text(encoding="utf-8")
    assert ("\\u2014" in rewritten) is escaped
    assert ("—" in rewritten) is not escaped
    assert json.loads(rewritten)["reference_hashes"] == tool.reference_hashes(skill)
    assert tool.update_skill(skill, check=True) is False
