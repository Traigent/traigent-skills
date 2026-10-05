"""In-run ``safety_constraints`` guidance is floored at its first release (traigent-skills#385).

The ``safety-constraints-impl`` row of docs/version-matrix.md names the first
SDK whose ``@traigent.optimize`` accepts a non-empty ``safety_constraints``
value (the floor); older SDKs raise ``NotImplementedError`` at decoration time.
The two skills that teach the kwarg split their guidance by version, and the
#270 rule must keep holding: an SDK below the floor (0.27.x included) is never
told to pass ``safety_constraints``. It is held by five checks:

- The SKILL.md text is version-conditional: a floor-and-later path pointing at
  the ``safety-constraints-impl`` matrix row, and a below-the-floor "do not
  pass" path that states the ``NotImplementedError`` at decoration. Both
  floor-and-later paths say the constraint does not filter trials (in
  boost-agent, the bullet item carrying the matrix pointer); the
  ci-safety-gate one also names ``best_config``. The stale "planned / not yet
  available" claims are gone from both skills and README.md.
- The runnable recipe lives in ``references/in-run-safety.md``, floored in
  sync_map.yml at exactly the matrix row's ``changed_in_version``, so released
  buckets below the floor never execute it; it states that the constraint does
  not filter trials, and its runnable block passes ``safety_constraints=`` to
  ``traigent.optimize`` and checks ``stop_reason == "safety_constraint"``. The
  skill's ``min_sdk_version`` is not raised above the default, so
  0.24.0-0.27.x users keep the "it raises" guidance. (That SKILL.md cannot be
  floored, and that a floored file states ``Requires `traigent>=X` ``, are
  enforced repo-wide by conftest and test_python_version_floors.py.)
- The floor sits above ``LAST_RELEASE_RAISING``, and the released CI buckets,
  taken from ``tools/contract/list_buckets.py``, include at least one release
  below the floor and at least one at or above it. No particular bucket is
  pinned, so an unrelated skill's ``min_sdk_version`` change does not fail
  this module unless it empties one side.
- The installed SDK decorates with a non-empty ``safety_constraints`` iff it
  is at or above that floor (or develop); below it, decoration raises
  ``NotImplementedError``. The buckets prove only that some bucket < floor <=
  some bucket; the exact boundary rests on the offline decoration probes
  recorded for #385 (see ``LAST_RELEASE_RAISING``).
- **Residual, review only:** new ``safety_constraints`` prose outside these
  assertions is caught by review, not by this module. So are semantic edits
  inside the asserted paragraphs that keep every matched phrase (e.g. a claim
  that the constraint filters some trials, a wrong ``min_samples`` default, or
  a workaround offered to a below-the-floor SDK), and a paragraph that pairs
  the right phrases with the wrong version (the floor phrase and the
  below-floor phrase are matched independently): the checks are phrase
  presence over blank-line paragraphs, not meaning. The halt semantics
  themselves are pinned only by the floored runnable recipe executing on
  buckets at or above the floor.
"""

from __future__ import annotations

import ast
import importlib.metadata
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.version import Version

from .conftest import _sdk_version_label, skill_floor
from .extract import collect_runnable_file
from .test_version_matrix import POINTER_RE, _parse_matrix

SKILLS = ("traigent-ci-safety-gate", "traigent-boost-agent")
GATE_SKILL = "traigent-ci-safety-gate"
REFERENCE = "references/in-run-safety.md"
FACT_ID = "safety-constraints-impl"

SAFETY_RE = re.compile(r"\bsafety_constraints\b")
DO_NOT_PASS_RE = re.compile(r"\bdo\s+(?:\*\*)?not(?:\*\*)?\s+pass\b", re.I)
NOT_IMPLEMENTED_RE = re.compile(r"\bNotImplementedError\b")
DECORATION_RE = re.compile(r"\bdecoration\b", re.I)
DOES_NOT_FILTER_RE = re.compile(r"\bdoes\s+(?:\*\*)?not(?:\*\*)?\s+filter\b", re.I)
BEST_CONFIG_RE = re.compile(r"\bbest_config\b")
STOP_REASON_RE = re.compile(r"""\bstop_reason\b.*?["']safety_constraint["']""", re.S)
STALE_CLAIMS = (
    "Not Yet Available",
    "planned but not yet implemented",
    "is planned to filter",
    "do not teach it as usable today",
    "planned in-run",
)
# The SDK stamp the old ci-safety-gate text carried (#301); checked there only.
STALE_GATE_CLAIMS = ("verified against SDK 0.18.x",)
# Offline decoration probes recorded for traigent-skills#385:
# @traigent.optimize(..., safety_constraints=[hallucination_rate().below(0.1)])
# raises NotImplementedError at decoration on 0.21.3, 0.24.0 and 0.27.0;
# 0.28.0 and 0.30.0 decorate.
LAST_RELEASE_RAISING = "0.27.0"


def _floor(repo_root: Path) -> str:
    rows = {row.fact_id: row for row in _parse_matrix(repo_root)}
    assert FACT_ID in rows, f"docs/version-matrix.md has no `{FACT_ID}` row"
    return rows[FACT_ID].changed_in_version


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs, whitespace collapsed (presence checks only)."""
    return [" ".join(p.split()) for p in re.split(r"\n[ \t]*\n", text) if p.strip()]


def _items(text: str) -> list[str]:
    """Paragraphs further split at each line-leading list marker, whitespace collapsed."""
    return [
        " ".join(i.split())
        for p in re.split(r"\n[ \t]*\n", text)
        for i in re.split(r"\n[ \t]*(?:[-*]|\d+\.)[ \t]", p)
        if i.strip()
    ]


def test_safety_constraints_guidance_is_version_conditional(repo_root: Path) -> None:
    floor = re.escape(_floor(repo_root))
    newer_sdk_re = re.compile(
        rf"{floor}\s+(?:and|or)\s+(?:later|newer|above)|since\s+{floor}|>=\s*{floor}"
    )
    older_sdk_re = re.compile(
        r"(?:below|before|older\s+than|earlier\s+than|prior\s+to|<)\s*"
        rf"(?:traigent\s+|SDK\s+)?{floor}(?!\.?\d)"
    )

    problems: list[str] = []
    for skill in SKILLS:
        rel = f"skills/{skill}/SKILL.md"
        text = (repo_root / rel).read_text(encoding="utf-8")
        paragraphs = _paragraphs(text)

        if not any(
            newer_sdk_re.search(p)
            and SAFETY_RE.search(p)
            and FACT_ID in POINTER_RE.findall(p)
            for p in paragraphs
        ):
            problems.append(
                f"{rel}: no paragraph ties `safety_constraints` to the floor and "
                f"later with `see version-matrix: {FACT_ID}`"
            )

        if not any(
            older_sdk_re.search(p)
            and DO_NOT_PASS_RE.search(p)
            and SAFETY_RE.search(p)
            and NOT_IMPLEMENTED_RE.search(p)
            and DECORATION_RE.search(p)
            for p in paragraphs
        ):
            problems.append(
                f"{rel}: no below-the-floor paragraph saying do not pass "
                "`safety_constraints`, and that it raises NotImplementedError "
                "at decoration"
            )

        if skill == GATE_SKILL and not any(
            DOES_NOT_FILTER_RE.search(p) and BEST_CONFIG_RE.search(p)
            for p in paragraphs
        ):
            problems.append(
                f"{rel}: no paragraph saying the constraint does not filter "
                "trials and naming `best_config`"
            )

        if skill != GATE_SKILL and not any(
            DOES_NOT_FILTER_RE.search(item) and FACT_ID in POINTER_RE.findall(item)
            for item in _items(text)
        ):
            problems.append(
                f"{rel}: the list item pointing at `see version-matrix: {FACT_ID}` "
                "does not say the constraint does not filter trials"
            )

        flat = " ".join(paragraphs).casefold()
        stale = STALE_CLAIMS + (STALE_GATE_CLAIMS if skill == GATE_SKILL else ())
        problems.extend(
            f"{rel}: stale claim {claim!r}"
            for claim in stale
            if claim.casefold() in flat
        )

    readme = " ".join(
        _paragraphs((repo_root / "README.md").read_text(encoding="utf-8"))
    ).casefold()
    problems.extend(
        f"README.md: stale claim {claim!r}"
        for claim in STALE_CLAIMS
        if claim.casefold() in readme
    )

    assert not problems, "\n".join(problems)


def _passes_safety_constraints_to_optimize(code: str) -> bool:
    for node in ast.walk(ast.parse(code)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == "optimize" and any(
            keyword.arg == "safety_constraints" for keyword in node.keywords
        ):
            return True
    return False


def test_safety_constraints_reference_floor_matches_version_matrix(
    repo_root: Path, sync_map: dict
) -> None:
    floor = _floor(repo_root)
    floors = sync_map["skills"][GATE_SKILL].get("python_version_floors") or {}
    assert floors.get(REFERENCE) == floor, (
        f"sync_map.yml {GATE_SKILL}.python_version_floors[{REFERENCE!r}] = "
        f"{floors.get(REFERENCE)!r}; the `{FACT_ID}` matrix row says {floor!r}"
    )
    default_floor = str(sync_map["default_min_sdk_version"])
    assert Version(skill_floor(sync_map, GATE_SKILL)) <= Version(default_floor), (
        f"{GATE_SKILL}: min_sdk_version {skill_floor(sync_map, GATE_SKILL)} is "
        f"above the default {default_floor}; buckets below the `{FACT_ID}` floor "
        "would lose the 'it raises' guidance"
    )

    path = repo_root / "skills" / GATE_SKILL / REFERENCE
    assert path.is_file(), f"{path.relative_to(repo_root)} is missing"
    assert DOES_NOT_FILTER_RE.search(" ".join(path.read_text(encoding="utf-8").split())), (
        f"{path.relative_to(repo_root)} must state that the constraint does not "
        "filter trials"
    )
    snippets = [
        s
        for s in collect_runnable_file(GATE_SKILL, path)
        if s.language.lower() == "python"
    ]
    assert any(
        _passes_safety_constraints_to_optimize(s.text) and STOP_REASON_RE.search(s.text)
        for s in snippets
    ), (
        f"{path.relative_to(repo_root)}: no ```python runnable block calls "
        "traigent.optimize(..., safety_constraints=...) and checks "
        "stop_reason == \"safety_constraint\""
    )


def test_released_buckets_straddle_the_safety_constraints_floor(
    repo_root: Path,
) -> None:
    # The same command contracts.yml fans out into strategy.matrix.bucket.
    output = subprocess.check_output(
        [sys.executable, str(repo_root / "tools/contract/list_buckets.py"), "--json"],
        cwd=repo_root,
        text=True,
    )
    buckets = sorted(Version(b) for b in json.loads(output))
    floor = Version(_floor(repo_root))

    last_raising = Version(LAST_RELEASE_RAISING)
    assert floor > last_raising, (
        f"the `{FACT_ID}` floor {floor} is not above {last_raising}, the last "
        "release that raises NotImplementedError for safety_constraints (#385 "
        "probes): #270 forbids telling that SDK to pass safety_constraints"
    )
    assert any(b < floor for b in buckets), (
        f"no released CI bucket is below the `{FACT_ID}` floor {floor} "
        f"(buckets {[str(b) for b in buckets]}): the 'below the floor raises' "
        "path would never run"
    )
    assert any(b >= floor for b in buckets), (
        f"no released CI bucket is at or above the `{FACT_ID}` floor {floor} "
        f"(buckets {[str(b) for b in buckets]}): the acceptance path would only "
        "run against develop"
    )


def test_safety_constraints_accepted_iff_installed_sdk_at_or_above_floor(
    repo_root: Path, pytestconfig: pytest.Config
) -> None:
    try:
        from traigent.api.safety import hallucination_rate
    except ImportError:
        pytest.skip("traigent.api.safety.hallucination_rate is not importable")
    import traigent

    floor = Version(_floor(repo_root))
    label = _sdk_version_label(pytestconfig)
    installed = Version(importlib.metadata.version("traigent"))

    def decorate() -> object:
        @traigent.optimize(
            configuration_space={"x": [1, 2]},
            objectives=["accuracy"],
            offline=True,
            safety_constraints=[hallucination_rate().below(0.1)],
        )
        def agent(question: str) -> str:
            traigent.get_config()
            return question

        return agent

    if label == "develop" or installed >= floor:
        assert decorate() is not None
        return

    with pytest.raises(NotImplementedError):
        decorate()
