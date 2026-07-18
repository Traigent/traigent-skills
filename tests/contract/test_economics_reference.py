"""Contract tests for the shared economics reference (WI-A).

Three properties are pinned here, each one a Terra BLOCK finding made executable:

1. **Reachability from the installed layout.** The supported single-skill installs
   (`npx skills add --skill <one>`, `cp -r traigent-skills/skills/<one> .agents/skills/`)
   copy ONE skill directory and nothing else. A SKILL.md that tells an agent to read a
   repo-root `docs/` path is naming a file that install does not have. These tests copy a
   skill directory ALONE into a tmpdir — no repo around it — and assert the reference is
   present and readable there. One source of truth is preserved: the copies are generated
   from docs/shared/ by tools/contract/sync_economics_reference.py and pinned byte-identical
   here.

2. **traigent-analyze-guidance cannot shape economics locally.** It is a thin client whose
   budget is service-authored; local budget computation is the regression this lints for.

3. **All five closed values stay reachable under the three-option cap.** The interaction
   policy caps a presentation at 3 options with exactly one Recommended; every closed field
   has 5 values. The doc's paging rule is simulated against the doc's own parsed enums.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


CANONICAL_RELPATH = "docs/shared/economics-characterization.v0.md"
REFERENCE_RELPATH = "references/economics-characterization.v0.md"
POINTER_MARKER = "`references/economics-characterization.v0.md`"

# Closed fields per the canonical doc §2 — each is an enum of exactly five values.
CLOSED_FIELDS = (
    "value_channel",
    "daily_volume_band",
    "error_cost_band",
    "lifecycle_stage",
    "human_cycle_hours_band",
)
CLOSED_VALUES_PER_FIELD = 5
MAX_OPTIONS_PER_PAGE = 3  # docs/shared/interaction-policy.v1.md: "show at most 3"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _economics_skill_dirs(root: Path) -> list[Path]:
    return [
        d
        for d in sorted((root / "skills").iterdir())
        if d.is_dir()
        and (d / "SKILL.md").is_file()
        and POINTER_MARKER in (d / "SKILL.md").read_text(encoding="utf-8")
    ]


ECONOMICS_SKILLS = _economics_skill_dirs(_repo_root())
ECONOMICS_SKILL_IDS = [d.name for d in ECONOMICS_SKILLS]


def test_economics_skills_are_discovered() -> None:
    """A rename that silently drops every pointer must fail loudly, not vacuously pass."""
    assert ECONOMICS_SKILLS, (
        f"No SKILL.md points at {REFERENCE_RELPATH}. Either the pointer wording changed "
        "(update POINTER_MARKER here and in tools/contract/sync_economics_reference.py) or "
        "the economics posture was dropped from every skill."
    )


# --------------------------------------------------------------------------------------
# 1. Canonical reference availability from the supported INSTALLED layouts
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("skill_dir", ECONOMICS_SKILLS, ids=ECONOMICS_SKILL_IDS)
def test_shipped_reference_is_byte_identical_to_canonical(skill_dir: Path) -> None:
    """One source of truth: each shipped copy is generated, never independently authored."""
    canonical = (_repo_root() / CANONICAL_RELPATH).read_bytes()
    shipped = skill_dir / REFERENCE_RELPATH
    assert shipped.is_file(), (
        f"{skill_dir.name}: SKILL.md points at {REFERENCE_RELPATH} but it is not shipped — "
        "run: python tools/contract/sync_economics_reference.py"
    )
    assert shipped.read_bytes() == canonical, (
        f"{skill_dir.name}: {REFERENCE_RELPATH} has drifted from {CANONICAL_RELPATH}. "
        "The shipped copy is a generated artifact — edit the canonical file, then run: "
        "python tools/contract/sync_economics_reference.py"
    )


@pytest.mark.parametrize("skill_dir", ECONOMICS_SKILLS, ids=ECONOMICS_SKILL_IDS)
def test_single_skill_install_can_read_the_reference(
    skill_dir: Path, tmp_path: Path
) -> None:
    """Prove the INSTALLED layout, not the source-tree path.

    Reproduces `cp -r traigent-skills/skills/<one> .agents/skills/` — one skill directory,
    no repo, no docs/ tree — and asserts every skill-relative path the economics section
    names resolves and is readable there.
    """
    installed = tmp_path / ".agents" / "skills" / skill_dir.name
    installed.parent.mkdir(parents=True)
    shutil.copytree(skill_dir, installed)

    reference = installed / REFERENCE_RELPATH
    assert reference.is_file(), (
        f"{skill_dir.name}: after a single-skill install, {REFERENCE_RELPATH} does not "
        "exist — the skill points its agent at a file the user never received."
    )
    text = reference.read_text(encoding="utf-8")
    assert "Traigent Optimization Economics & Characterization" in text, (
        f"{skill_dir.name}: the installed reference does not contain the economics content."
    )
    # The whole point of the reference: the posture and the closed values travel with it.
    assert "bounded investment, not a cost to avoid by default" in text
    for field in CLOSED_FIELDS:
        assert field in text, (
            f"{skill_dir.name}: installed reference is missing closed field {field!r}"
        )


@pytest.mark.parametrize("skill_dir", ECONOMICS_SKILLS, ids=ECONOMICS_SKILL_IDS)
def test_economics_section_names_no_unreachable_read_path(skill_dir: Path) -> None:
    """A repo-root docs/ path may be cited as provenance, never given as the read instruction.

    `docs/shared/...` does not exist in a single-skill or manual install. The actionable
    pointer must be the skill-relative one.
    """
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    section = _economics_section(text)
    assert POINTER_MARKER in section, (
        f"{skill_dir.name}: economics section must point at {REFERENCE_RELPATH}"
    )
    if CANONICAL_RELPATH in section:
        # The only sanctioned mention is the "generated from <path>" provenance note: it
        # tells contributors where edits go without telling agents to read a path they lack.
        assert "generated from" in section, (
            f"{skill_dir.name}: {CANONICAL_RELPATH} is named in the economics section "
            "without marking it as the generated-from source. Agents must be told to read "
            f"{REFERENCE_RELPATH}; the docs/ path is not present in an installed skill."
        )


def test_sync_tool_check_mode_passes(tmp_path: Path) -> None:
    """The generator is the enforcement path; --check must agree with the committed tree."""
    result = subprocess.run(
        [sys.executable, "tools/contract/sync_economics_reference.py", "--check"],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "sync_economics_reference.py --check failed:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_sync_tool_detects_a_tampered_copy(tmp_path: Path) -> None:
    """Guard the guard: --check must actually fail on drift, not pass vacuously."""
    repo_copy = tmp_path / "repo"
    root = _repo_root()
    shutil.copytree(
        root,
        repo_copy,
        ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"),
    )
    tampered = repo_copy / "skills" / ECONOMICS_SKILLS[0].name / REFERENCE_RELPATH
    tampered.write_text("locally edited generated artifact\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "tools/contract/sync_economics_reference.py", "--check"],
        cwd=repo_copy,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        "sync_economics_reference.py --check passed on a tampered copy — the drift gate "
        "is not actually gating."
    )


# --------------------------------------------------------------------------------------
# 2. No economics skill (all EIGHT) may shape or compute economics locally
# --------------------------------------------------------------------------------------
#
# "Characterize, never compute budgets locally" is not just analyze-guidance's rule — it is
# the boundary for every skill that ships the economics reference. The budget is authored by
# the backend calculator (WI-C); until it ships there is no budget to compute. These lints
# hold across all eight economics skills so no skill hands an agent a local calculator.

# Phrasings that hand budget authorship back to the skill. Kept narrow and positive-form so
# the required "Do not compute ... locally" sentences cannot themselves trip the lint.
LOCAL_BUDGET_AUTHORSHIP_PATTERNS = (
    r"shapes?\s+\*?how much\*?\s+to propose",
    r"weigh(?:ing)?\s+the\s+next\s+run'?s\s+cost\s+against",
    r"\bcompute\s+(?:the\s+)?(?:B_day|budget)\b(?![^.]*\bservice\b)",
    r"\bestimate\s+(?:a|the)\s+(?:daily\s+)?budget\s+(?:locally|yourself)",
    r"\bderive\s+(?:a|the)\s+budget\b",
)

REQUIRED_GUIDANCE_SENTENCES = (
    "Do not compute, adjust, or recommend a budget locally",
    "budget authorship belongs to the service",
    "no budget number at all",
)

# Followable budget arithmetic — a local calculator. Forbidden in every SKILL.md economics
# section AND in the shipped reference itself (it travels inside each skill).
BUDGET_ARITHMETIC_PATTERNS = (
    r"B_day\s*=",
    r"clamp\s*\(",
    r"0\.10\s*×",
    r"payback_days\s*=",
)


def _skill_economics_section(skill_dir: Path) -> str:
    return _economics_section((skill_dir / "SKILL.md").read_text(encoding="utf-8"))


@pytest.mark.parametrize("skill_dir", ECONOMICS_SKILLS, ids=ECONOMICS_SKILL_IDS)
def test_no_skill_authors_a_budget_locally(skill_dir: Path) -> None:
    """Every economics skill is a thin client: the service authors the budget, not markdown."""
    section = _skill_economics_section(skill_dir)
    offenders = [
        pattern
        for pattern in LOCAL_BUDGET_AUTHORSHIP_PATTERNS
        if re.search(pattern, section, flags=re.IGNORECASE)
    ]
    assert not offenders, (
        f"{skill_dir.name}: the Traigent service authors the budget exactly as it authors "
        "the run-plan and the next-step decision. These phrasings hand budget authorship "
        "back to local markdown reasoning: " + ", ".join(repr(o) for o in offenders)
    )


@pytest.mark.parametrize("skill_dir", ECONOMICS_SKILLS, ids=ECONOMICS_SKILL_IDS)
def test_every_skill_states_the_service_owned_budget_boundary(skill_dir: Path) -> None:
    """All eight must state the service-owned budget boundary and the no-payload behaviour."""
    # Collapse whitespace: the required sentences may wrap across lines in the markdown.
    section = re.sub(r"\s+", " ", _skill_economics_section(skill_dir))
    missing = [s for s in REQUIRED_GUIDANCE_SENTENCES if s not in section]
    assert not missing, (
        f"{skill_dir.name}: the economics section must state the service-owned budget "
        "boundary and the no-payload behaviour (say so and stop / fall back with no number — "
        f"never invent one). Missing: {missing}"
    )


@pytest.mark.parametrize("skill_dir", ECONOMICS_SKILLS, ids=ECONOMICS_SKILL_IDS)
def test_no_skill_carries_budget_arithmetic(skill_dir: Path) -> None:
    """No local calculator: a formula in a SKILL.md is a budget the service didn't author."""
    section = _skill_economics_section(skill_dir)
    formula_hits = [p for p in BUDGET_ARITHMETIC_PATTERNS if re.search(p, section)]
    assert not formula_hits, (
        f"{skill_dir.name}: the economics section must not carry budget arithmetic; the "
        f"budget is service-authored. Found: {formula_hits}"
    )


def test_reference_carries_no_followable_budget_arithmetic() -> None:
    """The shipped reference must not hand agents a local calculator before WI-C exists.

    The reference travels byte-identical inside every economics skill, so a formula, a
    floor/cap dollar table, or a payback recipe there is a budget an agent could author
    locally — exactly what "characterize, never compute budgets locally" forbids.
    """
    text = _canonical_text()
    hits = [p for p in BUDGET_ARITHMETIC_PATTERNS if re.search(p, text)]
    assert not hits, (
        f"{CANONICAL_RELPATH} carries followable budget arithmetic {hits}. The budget is "
        "service-authored — describe WHAT the service computes, never a formula an agent can "
        "run locally before the WI-C backend calculator ships."
    )
    assert not re.search(r"\|\s*Archetype\s*\|\s*Floor\s*\|\s*Cap\s*\|", text), (
        f"{CANONICAL_RELPATH} still ships the archetype floor/cap dollar table — a local "
        "calculator. The service owns floors and caps; describe them, do not tabulate them."
    )


# --------------------------------------------------------------------------------------
# 2b. The documented vocabulary is EXACTLY the canonical TraigentSchema vocabulary
# --------------------------------------------------------------------------------------
#
# Contract-first: TraigentSchema owns the economics characterization vocabulary. The skills
# must document the SAME closed enums and field names — a drift (band_1k_99k vs 1k_to_99k,
# mistake_prevention vs prevent_costly_mistakes, …) is a broken contract. In the multi-repo
# workspace the schema repo is a sibling of traigent-skills; a skills-only CI checkout will
# not have it, so this check SKIPS with a reason when it cannot find the sibling — it never
# passes falsely on a missing schema.

# Each documented closed band field maps to one TraigentSchema enum definition.
SCHEMA_FIELD_TO_DEFINITION = {
    "value_channel": "ValueChannel",
    "daily_volume_band": "DailyVolumeBand",
    "error_cost_band": "ErrorCostBand",
    "lifecycle_stage": "LifecycleStage",
    "human_cycle_hours_band": "HumanCycleHoursBand",
}

SCHEMA_VOCAB_RELPATH = (
    "traigent_schema/schemas/economics/economics_characterization_vocabulary_schema.json"
)


def _schema_vocabulary_path() -> Path | None:
    """Locate the sibling TraigentSchema canonical vocabulary file, or None if absent."""
    candidates: list[Path] = []
    env = os.environ.get("TRAIGENT_SCHEMA_REPO")
    if env:
        candidates.append(Path(env) / SCHEMA_VOCAB_RELPATH)
    parent = _repo_root().parent
    candidates.append(parent / "TraigentSchema" / SCHEMA_VOCAB_RELPATH)
    candidates.extend(
        sibling / SCHEMA_VOCAB_RELPATH for sibling in sorted(parent.glob("TraigentSchema*"))
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load_schema_vocabulary() -> dict:
    path = _schema_vocabulary_path()
    if path is None:
        pytest.skip(
            "sibling TraigentSchema economics vocabulary not found (looked for "
            f"{SCHEMA_VOCAB_RELPATH} under a TraigentSchema* sibling or $TRAIGENT_SCHEMA_REPO)"
            " — cross-repo vocabulary check skipped, not passed"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _survey_json_example(text: str) -> dict:
    """Parse the §6 local-draft survey JSON example from the canonical doc."""
    for block in re.findall(r"```json\n(.*?)\n```", text, flags=re.DOTALL):
        if "traigent-economics-survey" in block:
            return json.loads(block)
    raise AssertionError("no economics-survey JSON example found in the canonical doc")


@pytest.mark.parametrize("field", CLOSED_FIELDS)
def test_documented_band_values_match_schema_enum_exactly(field: str) -> None:
    """Every documented closed value is EXACTLY a TraigentSchema enum for that field."""
    vocab = _load_schema_vocabulary()
    definition = SCHEMA_FIELD_TO_DEFINITION[field]
    schema_enum = vocab["definitions"][definition]["enum"]
    documented = _parse_closed_values(_canonical_text(), field)
    assert set(documented) == set(schema_enum), (
        f"{field}: documented closed values {sorted(documented)} are not the Schema enum "
        f"{sorted(schema_enum)} ({definition}). TraigentSchema is canonical — align "
        f"{CANONICAL_RELPATH}, then re-run tools/contract/sync_economics_reference.py."
    )


def test_documented_field_names_match_schema_field_allowlist() -> None:
    """The five band fields + five typed overrides equal the Schema field-name allowlist."""
    vocab = _load_schema_vocabulary()
    schema_bands = set(vocab["definitions"]["CharacterizationBands"]["properties"])
    schema_overrides = set(vocab["definitions"]["CharacterizationOverrides"]["properties"])
    allowlist = set(vocab["definitions"]["CharacterizationFieldName"]["enum"])

    json_block = _survey_json_example(_canonical_text())
    documented_bands = set(json_block["closed_fields"])
    documented_overrides = set(json_block["typed_overrides"])

    assert set(CLOSED_FIELDS) == schema_bands, (
        f"the doc's five closed band fields {sorted(CLOSED_FIELDS)} are not the Schema band "
        f"fields {sorted(schema_bands)}"
    )
    assert documented_bands == schema_bands, (
        f"§6 local-draft closed_fields {sorted(documented_bands)} != Schema band fields "
        f"{sorted(schema_bands)}"
    )
    assert documented_overrides == schema_overrides, (
        f"§6 local-draft typed_overrides {sorted(documented_overrides)} != Schema overrides "
        f"{sorted(schema_overrides)}"
    )
    assert (documented_bands | documented_overrides) <= allowlist, (
        "documented field names are not all in the Schema CharacterizationFieldName allowlist"
    )


def test_documented_survey_json_values_are_schema_enums() -> None:
    """The §6 local-draft example uses only Schema enum values in its closed band fields."""
    vocab = _load_schema_vocabulary()
    json_block = _survey_json_example(_canonical_text())
    for field, cell in json_block["closed_fields"].items():
        definition = SCHEMA_FIELD_TO_DEFINITION[field]
        schema_enum = set(vocab["definitions"][definition]["enum"])
        assert cell["value"] in schema_enum, (
            f"§6 example: {field}={cell['value']!r} is not a Schema {definition} enum value "
            f"{sorted(schema_enum)}"
        )


# --------------------------------------------------------------------------------------
# 3. Every closed value reachable under the 3-option presentation cap
# --------------------------------------------------------------------------------------


def _canonical_text() -> str:
    return (_repo_root() / CANONICAL_RELPATH).read_text(encoding="utf-8")


def _parse_closed_values(text: str, field: str) -> list[str]:
    """Parse the `Closed value` column of one field's option table in the canonical doc."""
    heading = re.search(rf"^### Q\d+ — `{re.escape(field)}`.*$", text, flags=re.MULTILINE)
    assert heading, f"no section heading found for closed field {field!r}"
    rest = text[heading.end() :]
    next_heading = re.search(r"^#{2,3} ", rest, flags=re.MULTILINE)
    section = rest[: next_heading.start()] if next_heading else rest
    return re.findall(r"^\|[^|]+\|\s*`([a-z0-9_]+)`\s*\|$", section, flags=re.MULTILINE)


@pytest.mark.parametrize("field", CLOSED_FIELDS)
def test_each_closed_field_has_five_values(field: str) -> None:
    values = _parse_closed_values(_canonical_text(), field)
    assert len(values) == CLOSED_VALUES_PER_FIELD, (
        f"{field}: expected {CLOSED_VALUES_PER_FIELD} closed values, parsed {values}"
    )
    assert len(set(values)) == len(values), f"{field}: duplicate closed values {values}"


def test_canonical_doc_documents_the_paging_rule() -> None:
    """The cap/enum tension must be resolved by a stated rule, not left to the reader."""
    # Line wrapping is an editing detail, not a contract: compare on collapsed whitespace.
    text = re.sub(r"\s+", " ", _canonical_text())
    for required in (
        "paging rule",
        "At most three options; exactly one Recommended",
        "carry **the same overall recommendation** forward",
        "Five values need at most two pages",
        "never drop a value because it did not fit on a page",
    ):
        assert required in text, (
            f"canonical economics doc is missing the paging rule element: {required!r}"
        )


def _page_presentations(values: list[str], recommended: str) -> list[list[str]]:
    """Reference implementation of the doc's §4 paging rule.

    Page 1: recommendation + up to 2 alternatives.
    Page N>1: the SAME carried recommendation + up to 2 not-yet-shown values.
    """
    assert recommended in values
    alternatives = [v for v in values if v != recommended]
    pages = [[recommended, *alternatives[:2]]]
    remaining = alternatives[2:]
    while remaining:
        pages.append([recommended, *remaining[:2]])
        remaining = remaining[2:]
    return pages


@pytest.mark.parametrize("field", CLOSED_FIELDS)
def test_every_closed_value_is_reachable_without_breaking_the_option_cap(
    field: str,
) -> None:
    """All 5 selectable; every page ≤3 options with exactly one Recommended; rec is stable."""
    values = _parse_closed_values(_canonical_text(), field)
    for recommended in values:  # the rule must hold whichever value is recommended
        pages = _page_presentations(values, recommended)
        shown: set[str] = set()
        for page_number, page in enumerate(pages, start=1):
            assert len(page) <= MAX_OPTIONS_PER_PAGE, (
                f"{field}: page {page_number} shows {len(page)} options, cap is "
                f"{MAX_OPTIONS_PER_PAGE} (docs/shared/interaction-policy.v1.md)"
            )
            assert len(set(page)) == len(page), f"{field}: page {page_number} repeats a value"
            recommended_marks = [v for v in page if v == recommended]
            assert len(recommended_marks) == 1, (
                f"{field}: page {page_number} must carry exactly one Recommended "
                f"(the same one, {recommended!r}) — found {len(recommended_marks)}"
            )
            shown.update(page)
        assert shown == set(values), (
            f"{field}: recommending {recommended!r} leaves "
            f"{sorted(set(values) - shown)} unreachable — every closed value must be "
            "presentable within the cap"
        )
        assert len(pages) <= 2, (
            f"{field}: five values must need at most two pages, needed {len(pages)}"
        )


def test_paging_worked_example_in_doc_obeys_the_rule() -> None:
    """The doc's own worked example must not contradict the rule it illustrates."""
    text = _canonical_text()
    rows = re.findall(
        r"^\| (?:1|2 \(on request\)) \| ([^|]+) \| ([^|]+) \|$", text, flags=re.MULTILINE
    )
    assert len(rows) == 2, "the §4 worked example must show exactly two pages"
    error_cost_values = set(_parse_closed_values(text, "error_cost_band"))
    shown: set[str] = set()
    recommendations: set[str] = set()
    for options_cell, recommended_cell in rows:
        options = re.findall(r"`([a-z0-9_]+)`", options_cell)
        assert len(options) <= MAX_OPTIONS_PER_PAGE, (
            f"worked example page shows {len(options)} options, cap is {MAX_OPTIONS_PER_PAGE}"
        )
        shown.update(options)
        page_recommendations = re.findall(r"`([a-z0-9_]+)`", recommended_cell)
        assert len(page_recommendations) == 1, (
            "each worked-example page must mark exactly one Recommended"
        )
        recommendations.update(page_recommendations)
    assert shown == error_cost_values, (
        f"worked example leaves {sorted(error_cost_values - shown)} unreachable"
    )
    assert len(recommendations) == 1, (
        f"the worked example must carry the SAME recommendation across pages, "
        f"found {sorted(recommendations)}"
    )


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------

ECONOMICS_HEADING = "## Optimization Economics — Read This Before Sizing a Run"


def _economics_section(skill_text: str) -> str:
    """The economics block of a SKILL.md: its heading up to the next `## ` heading."""
    start = skill_text.find(ECONOMICS_HEADING)
    assert start >= 0, (
        f"SKILL.md is missing the economics heading {ECONOMICS_HEADING!r}"
    )
    rest = skill_text[start + len(ECONOMICS_HEADING) :]
    next_heading = re.search(r"^## ", rest, flags=re.MULTILINE)
    return rest[: next_heading.start()] if next_heading else rest
