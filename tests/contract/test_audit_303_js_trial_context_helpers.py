"""Trial-context helpers named in JS skill prose must be real `@traigent/sdk` exports (#303).

`test_js.py` validates only `import { X } from '@traigent/sdk'` statements in code
blocks. A helper named in prose, such as `isInTrial`, escapes that check although a
reader will import it. Here every backticked helper-shaped name in a `js: true`
skill must be a root export in `tests/data/js_api_snapshot.json`, or be written as
`<ExportedClass>.<method>` (for example `TrialContext.isInTrial()`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT_MODULE = "@traigent/sdk"

# `name`, `name()`, `Class.method` or `Class.method()` inside backticks.
BACKTICKED_RE = re.compile(r"`([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*))?(?:\(\))?`")
# Bare helper-shaped names: getTrialParam, isInTrial, wrapCallback, bindContext, ...
HELPER_RE = re.compile(r"^(?:get|is|has|set|with|wrap|bind|run)[A-Z]\w*$")


def _root_exports(repo_root: Path) -> set[str]:
    snapshot = json.loads(
        (repo_root / "tests/data/js_api_snapshot.json").read_text(encoding="utf-8")
    )
    return set((snapshot.get("exports") or {}).get(ROOT_MODULE) or ())


def unexported_helpers(text: str, exports: set[str]) -> list[tuple[int, str]]:
    problems: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in BACKTICKED_RE.finditer(line):
            owner, member = match.group(1), match.group(2)
            if member is None:
                if HELPER_RE.match(owner) and owner not in exports:
                    problems.append((line_number, owner))
            elif (
                owner[0].isupper() and HELPER_RE.match(member) and owner not in exports
            ):
                problems.append((line_number, f"{owner}.{member}"))
    return problems


def _js_skills(sync_map: dict) -> list[str]:
    return sorted(
        name
        for name, entry in (sync_map.get("skills") or {}).items()
        if (entry or {}).get("js")
    )


def test_js_skill_prose_names_only_exported_trial_helpers(
    repo_root: Path, sync_map: dict
) -> None:
    skills = _js_skills(sync_map)
    assert skills, "no skill declares `js: true` in sync_map.yml"
    exports = _root_exports(repo_root)
    assert exports, f"js_api_snapshot.json has no {ROOT_MODULE} exports"
    violations: list[str] = []
    for skill in skills:
        for path in sorted((repo_root / "skills" / skill).glob("**/*.md")):
            text = path.read_text(encoding="utf-8")
            for line_number, name in unexported_helpers(text, exports):
                violations.append(
                    f"{path.relative_to(repo_root)}:{line_number}: `{name}` is not a "
                    f"{ROOT_MODULE} export; name the exported helper or write "
                    "`<ExportedClass>.<method>()`"
                )
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("Use `getTrialParam` and `wrapCallback`.", []),
        ("Use `TrialContext.isInTrial()`.", []),
        ("Use `isInTrial`.", ["isInTrial"]),
        ("Use `NotExported.isInTrial()`.", ["NotExported.isInTrial"]),
        ("Set `offline` and `requireCloud`.", []),
    ],
)
def test_helper_check_has_teeth(text: str, flagged: list[str]) -> None:
    exports = {"getTrialParam", "wrapCallback", "TrialContext"}
    assert [name for _, name in unexported_helpers(text, exports)] == flagged
