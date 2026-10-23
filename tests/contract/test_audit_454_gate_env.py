"""Issue #454: the CI gate's PR job env must not set a cost limit the SDK rejects.

The PR job set ``TRAIGENT_RUN_COST_LIMIT: "0.00"`` while the same page told
teams to run ``optimize()``/``optimize_sync()`` in that job. Since SDK 0.19.1 a
non-positive limit raises ``ConfigurationError`` as soon as the cost enforcer is
built, so the first wiring call would red-fail the job. It was green only
because the job as written never called ``optimize()``.

The TVL-validator note was also version-dependent and unstamped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from .test_audit_349_fenced_blocks import skip_unless_current_released_sdk

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "skills" / "traigent-ci-safety-gate"
PAGES = (GATE / "SKILL.md", GATE / "references" / "gate-workflow.md")

# `TRAIGENT_RUN_COST_LIMIT: "0.00"` / `=0` / `: 0.0`, in YAML or shell form.
LIMIT_RE = re.compile(
    r"TRAIGENT_RUN_COST_LIMIT\s*[:=]\s*[\"']?(?P<value>-?\d+(?:\.\d+)?)[\"']?"
)


def _scanned_files() -> list[Path]:
    return [
        p
        for p in sorted(ROOT.glob("skills/**/*"))
        if p.is_file()
        and p.suffix in {".md", ".sh", ".yml", ".yaml"}
        and "/tests/" not in p.as_posix()
    ]


def test_no_skill_sets_a_nonpositive_run_cost_limit() -> None:
    violations: list[str] = []
    for path in _scanned_files():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in LIMIT_RE.finditer(line):
                if float(match.group("value")) <= 0:
                    violations.append(
                        f"{path.relative_to(ROOT)}:{lineno}: "
                        f"{match.group(0)!r} — the SDK raises ConfigurationError "
                        "for a non-positive limit as soon as the cost enforcer is built"
                    )
    assert not violations, "\n".join(violations)


def test_the_limit_matcher_has_teeth() -> None:
    assert LIMIT_RE.search('      TRAIGENT_RUN_COST_LIMIT: "0.00"').group("value") == "0.00"
    assert LIMIT_RE.search("TRAIGENT_RUN_COST_LIMIT=0").group("value") == "0"
    assert float(LIMIT_RE.search('TRAIGENT_RUN_COST_LIMIT: "5.00"').group("value")) > 0


def test_the_sdk_still_rejects_a_nonpositive_limit(
    sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(sync_map, sdk_version_label, "the CI gate env")
    traigent = pytest.importorskip("traigent")
    source = (
        Path(traigent.__file__).resolve().parent / "core" / "cost_enforcement.py"
    ).read_text(encoding="utf-8")
    assert "must be > 0 USD" in source, (
        "the SDK no longer rejects a non-positive TRAIGENT_RUN_COST_LIMIT — "
        "re-check the PR-job comment this skill carries"
    )


def test_the_pr_job_explains_why_the_limit_is_unset() -> None:
    for path in PAGES:
        text = path.read_text(encoding="utf-8")
        assert "TRAIGENT_RUN_COST_LIMIT is deliberately NOT set here" in text, (
            f"{path.relative_to(ROOT)}: a reader who adds the variable back needs "
            "the reason beside the env block"
        )
        assert "TRAIGENT_OFFLINE_MODE" in text


def test_the_tvl_note_is_version_stamped() -> None:
    text = (GATE / "SKILL.md").read_text(encoding="utf-8")
    note = text.split("Name specs `*.tvl.yml`", 1)
    assert len(note) == 2, "the TVL discovery note moved"
    note_text = note[1][:900]
    assert "0.30.0 and earlier" in note_text, "the note must name the versions it holds for"
    assert "--allow-empty" in note_text, "the note must name the flag the next release adds"
    assert "at least one spec exists" in note_text, (
        "keep the assertion step: it is correct on both sides of the change"
    )


def test_the_released_sdk_has_no_allow_empty_flag(
    sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(sync_map, sdk_version_label, "the TVL note")
    traigent = pytest.importorskip("traigent")
    tvl_main = Path(traigent.__file__).resolve().parent / "tvl" / "__main__.py"
    if not tvl_main.is_file():  # pragma: no cover - older layout
        pytest.skip("installed SDK has no traigent.tvl.__main__")
    assert "allow-empty" not in tvl_main.read_text(encoding="utf-8"), (
        "the released SDK now has --allow-empty; the skill's "
        "'0.30.0 and earlier' stamp needs rewriting to name this release"
    )
