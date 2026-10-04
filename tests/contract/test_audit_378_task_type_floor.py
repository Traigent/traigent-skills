"""``EvaluationOptions.task_type`` guidance is floored at its first release (traigent-skills#378).

The ``evaluation-task-type`` row of docs/version-matrix.md names the first SDK
whose ``EvaluationOptions`` accepts ``task_type`` (the floor); older SDKs reject
it at construction (pydantic ``extra_forbidden``). The two skills that teach the
field split their guidance by version, and the #270 rule must keep holding: an
SDK below the floor (0.27.x included) is never told to pass ``task_type``.

- **Pinned raw-text spans: a review tripwire, not a proof.** No Markdown is
  modelled. ``PINNED_TASK_TYPE_SPANS`` pins, by the first 16 hex digits of a
  sha256, one span of raw text per file: each ``references/task-type.md`` whole,
  and in each SKILL.md the section holding the guidance, from an exactly named
  anchor line (it must occur once) up to, not including, the next column-0
  heading of the anchor's level or shallower (a line starting with 1 to the
  anchor's level of ``#`` and a space), or EOF. Files are read as bytes and
  decoded as strict UTF-8; only CRLF is normalized to LF. A lone CR is NOT
  normalized, so it changes the hash like any other byte: anything changed
  inside a span trips, however it renders (setext underline, HTML heading,
  fenced or indented block). Every mention of the field in every ``*.md`` file
  under both skill directories (``IN_SCOPE_RE``: ``task_type``, "task type" or
  "task category", with ``_``, ``\\_``, ``-``, whitespace or nothing between
  the words, as in ``TaskType``) must lie inside a pinned span of its file. The
  pattern runs over the whole text and its whitespace separator includes line
  breaks, so a mention soft-wrapped across lines counts, and every line it
  covers must lie inside the span. A ``#`` line hidden inside a span ends it
  early; the hash then changes, and a field mention after it falls outside
  every span and trips too. Each failure lists the changed spans, the anchor
  problems and the out-of-span mentions (``path:first-last: text``) and carries
  the #270 re-check instruction, so the change is deliberate and reviewable.
- **Why not a Markdown parser.** The previous fingerprint hashed each in-scope
  paragraph with its heading path, which needed a hand-written block parser.
  Markdown structure is not reliably modelled lexically: each patch to it
  (setext headings, indented code) was followed by structures it still
  mis-read (``|``-prefixed setext text, indented fence markers around an ATX
  heading, HTML ``<hN>`` headings). Raw-text spans need no such model.
- **Residual, review only:** framing placed outside the pinned spans (a heading
  or note above the anchor line that re-scopes the whole section),
  instructions that avoid the field's names, and a mention in a skill outside
  these two skills' folders (the check scans only eval-audit and
  setup-decorator; e.g. a third skill saying "set the task type to
  exact_match" in words). The SKILL.md files stay whole-file
  pinned by the provenance ``doc_hash``.
- The SKILL.md text is version-conditional: a floor-and-later path pointing at
  the ``evaluation-task-type`` matrix row, and a below-the-floor "do not pass"
  path that states the ValidationError and the abstain outcome. The stale
  universal claims ("in no released version", "expected in a later SDK
  release") are gone.
- The runnable recipe lives in ``references/task-type.md``, floored in
  sync_map.yml at exactly the matrix row's ``changed_in_version``.
- The installed SDK accepts ``task_type`` iff it is at or above that floor. The
  CI buckets (0.21.3, 0.24.0, 0.27.0, 0.30.0, develop) prove only that
  0.27.0 < floor <= 0.30.0. The exact 0.28.0 boundary rests on offline
  construction probes of 0.27.0, 0.28.0, 0.29.0 and 0.30.0 recorded for #378.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest
from packaging.version import Version

from .conftest import _sdk_version_label
from .extract import collect_runnable_file
from .test_version_matrix import POINTER_RE, _parse_matrix

SKILLS = ("traigent-eval-audit", "traigent-setup-decorator")
REFERENCE = "references/task-type.md"
FACT_ID = "evaluation-task-type"

TASK_TYPE_RE = re.compile(r"\btask_type\b")
# Any mention of the field: task_type, task\_type, task type(s), task-type,
# tasktype, task category, task-category, task_category; not "multitask typechecker".
# Run over whole texts: the whitespace separator also matches a line break.
IN_SCOPE_RE = re.compile(
    r"(?<![A-Za-z0-9])task(?:\\?_|[\s-]+)?(?:types?(?![A-Za-z0-9])|categor)", re.I
)
DO_NOT_PASS_RE = re.compile(r"\bdo\s+(?:\*\*)?not(?:\*\*)?\s+pass\b", re.I)
VALIDATION_ERROR_RE = re.compile(r"ValidationError")
EXTRA_FORBIDDEN_RE = re.compile(r"Extra inputs are not\s+permitted")
ABSTAIN_RE = re.compile(r"\babstain", re.I)
STALE_CLAIMS = ("in no released version", "expected in a later SDK release")

EVAL_AUDIT = "skills/traigent-eval-audit/SKILL.md"
SETUP_DECORATOR = "skills/traigent-setup-decorator/SKILL.md"
EVAL_AUDIT_REFERENCE = f"skills/traigent-eval-audit/{REFERENCE}"
SETUP_DECORATOR_REFERENCE = f"skills/traigent-setup-decorator/{REFERENCE}"
EVALUATION_OPTIONS = "skills/traigent-setup-decorator/references/evaluation-options.md"

# Approved raw-text spans: anchor line (None = whole file) and sha256 prefix.
PINNED_TASK_TYPE_SPANS: dict[str, dict[str, str | None]] = {
    EVAL_AUDIT: {"anchor": "## Claim Scope", "sha256_16": "00974496e1cd08a1"},
    EVAL_AUDIT_REFERENCE: {"anchor": None, "sha256_16": "1846eca9dfd0d725"},
    SETUP_DECORATOR: {"anchor": "### Fields", "sha256_16": "3afc942b1d850544"},
    SETUP_DECORATOR_REFERENCE: {"anchor": None, "sha256_16": "e6201449c6f90853"},
}


def _pin_instruction(floor: str) -> str:
    """The #270 re-check every pin failure carries, worded from the matrix floor."""
    version = Version(floor)
    below = f"below {floor}"
    if version.micro == 0 and version.minor:
        below += f" ({version.major}.{version.minor - 1}.x included)"
    return (
        f"Before re-pinning, confirm no sentence in the listed text tells an SDK "
        f"{below} to pass, set or declare task_type (issue #270); this pin is a "
        "review tripwire, not a proof — framing outside the pinned spans and "
        "instructions that avoid the field's names are review-only."
    )


def _floor(repo_root: Path) -> str:
    rows = {row.fact_id: row for row in _parse_matrix(repo_root)}
    assert FACT_ID in rows, f"docs/version-matrix.md has no `{FACT_ID}` row"
    return rows[FACT_ID].changed_in_version


def _scanned(repo_root: Path) -> dict[str, str]:
    """Every markdown file under both skill directories: rel path -> text,
    decoded from bytes as strict UTF-8 (no universal-newline translation, so a
    lone CR survives into the text)."""
    return {
        path.relative_to(repo_root).as_posix(): path.read_bytes().decode("utf-8")
        for skill in SKILLS
        for path in sorted((repo_root / "skills" / skill).rglob("*.md"))
    }


def _lines(text: str) -> list[str]:
    """Split on LF after normalizing CRLF only; a lone CR stays in its line."""
    return text.replace("\r\n", "\n").split("\n")


class _Span(NamedTuple):
    start: int  # first line index
    end: int  # one past the last line index
    sha256_16: str


class _AnchorError(Exception):
    """A pinned anchor line that is missing, renamed or duplicated."""


def _span(rel: str, text: str, anchor: str | None) -> _Span:
    """The raw lines from ``anchor`` up to, not including, the next heading line
    of its level or shallower (lexically: column-0 ``#`` x 1..level, then a
    space), or EOF."""
    lines = _lines(text)
    if anchor is None:
        start, end = 0, len(lines)
    else:
        count = lines.count(anchor)
        if count != 1:
            raise _AnchorError(
                f"{rel}: anchor {anchor!r} occurs {count} times; it must occur once"
            )
        start = lines.index(anchor)
        level = len(anchor) - len(anchor.lstrip("#"))
        end_re = re.compile(rf"#{{1,{level}}} ")
        end = next(
            (i for i in range(start + 1, len(lines)) if end_re.match(lines[i])),
            len(lines),
        )
    raw = "\n".join(lines[start:end]).encode("utf-8")
    return _Span(start, end, hashlib.sha256(raw).hexdigest()[:16])


def _span_problems(
    texts: dict[str, str], pins: dict[str, dict[str, str | None]]
) -> list[str]:
    """Missing pinned files, anchor problems and changed pinned spans, then
    field mentions with a covered line outside every span."""
    problems = [
        f"{rel}: pinned file is not scanned" for rel in pins if rel not in texts
    ]
    spans: dict[str, _Span] = {}
    for rel, pin in pins.items():
        if rel not in texts:
            continue
        try:
            spans[rel] = span = _span(rel, texts[rel], pin["anchor"])
        except _AnchorError as error:
            problems.append(str(error))
            continue
        if span.sha256_16 != pin["sha256_16"]:
            problems.append(
                f"{rel}: span changed from {pin['anchor'] or '(whole file)'!r}, "
                f"lines {span.start + 1}-{span.end}; new sha256_16 {span.sha256_16}"
            )
    for rel, text in texts.items():
        span = spans.get(rel)
        lines = _lines(text)
        joined = "\n".join(lines)
        # (first, last) line index covered by each mention; dict keeps order.
        outside: dict[tuple[int, int], None] = {}
        for match in IN_SCOPE_RE.finditer(joined):
            first = joined.count("\n", 0, match.start())
            last = joined.count("\n", 0, match.end())
            if not (span and span.start <= first and last < span.end):
                outside[first, last] = None
        problems += [
            f"{rel}:{first + 1}-{last + 1}: "
            + " ".join(line.strip() for line in lines[first : last + 1])
            for first, last in outside
        ]
    return problems


def _pin_failure(
    texts: dict[str, str], pins: dict[str, dict[str, str | None]], floor: str
) -> str:
    """Empty if every pin holds, else the problems and the #270 instruction."""
    problems = _span_problems(texts, pins)
    return "\n".join([*problems, _pin_instruction(floor)]) if problems else ""


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs, whitespace collapsed (presence checks only)."""
    return [" ".join(p.split()) for p in re.split(r"\n[ \t]*\n", text) if p.strip()]


def _insert_lines(text: str, line: int, inserted: str) -> str:
    lines = _lines(text)
    lines[line:line] = inserted.split("\n")
    return "\n".join(lines)


IN_SCOPE_SAMPLES = {
    "Set task_type here.": True,
    "Set task\\_type here.": True,
    "Declare the task type.": True,
    "Task Types are coarse.": True,
    "See task-type.md.": True,
    "The TaskType enum.": True,
    "Set the task\ntype here.": True,
    "The task-category kwarg.": True,
    "Add the coarse task category.": True,
    "A task_category field.": True,
    "The multitask typechecker validates unrelated schemas.": False,
    "A subtask_type field.": False,
}

_Edit = Callable[[dict[str, str]], dict[str, str]]


def _in_span(rel: str, offset: int, inserted: str) -> _Edit:
    """Insert ``inserted`` ``offset`` lines below the start of ``rel``'s span."""

    def edit(texts: dict[str, str]) -> dict[str, str]:
        span = _span(rel, texts[rel], PINNED_TASK_TYPE_SPANS[rel]["anchor"])
        assert span.start + offset < span.end, f"{rel}: offset {offset} leaves span"
        return {**texts, rel: _insert_lines(texts[rel], span.start + offset, inserted)}

    return edit


def _around_span(rel: str, inserted: str) -> _Edit:
    """Insert ``inserted`` directly above the anchor and directly below the
    heading that ends the span (a line above that heading is inside the span)."""

    def edit(texts: dict[str, str]) -> dict[str, str]:
        span = _span(rel, texts[rel], PINNED_TASK_TYPE_SPANS[rel]["anchor"])
        assert span.end < len(_lines(texts[rel])), f"{rel}: span runs to EOF"
        below = _insert_lines(texts[rel], span.end + 1, inserted)
        return {**texts, rel: _insert_lines(below, span.start, inserted)}

    return edit


def _trailing_space(rel: str) -> _Edit:
    """Append one space to the second line below the span start."""

    def edit(texts: dict[str, str]) -> dict[str, str]:
        span = _span(rel, texts[rel], PINNED_TASK_TYPE_SPANS[rel]["anchor"])
        lines = _lines(texts[rel])
        lines[span.start + 2] += " "
        return {**texts, rel: "\n".join(lines)}

    return edit


def _version_bump(rel: str) -> _Edit:
    def edit(texts: dict[str, str]) -> dict[str, str]:
        lines = _lines(texts[rel])
        assert lines[0] == "---", f"{rel}: no front matter"
        close = lines.index("---", 1)
        versions = [i for i in range(close) if re.match(r"\s+version: ", lines[i])]
        assert len(versions) == 1, f"{rel}: front matter has {len(versions)} versions"
        lines[versions[0]] = '  version: "99.0.0"'
        return {**texts, rel: "\n".join(lines)}

    return edit


def _on_span_end(rel: str, appended: str) -> _Edit:
    """Append ``appended`` to the heading line that ends ``rel``'s span."""

    def edit(texts: dict[str, str]) -> dict[str, str]:
        span = _span(rel, texts[rel], PINNED_TASK_TYPE_SPANS[rel]["anchor"])
        lines = _lines(texts[rel])
        assert span.end < len(lines), f"{rel}: span runs to EOF"
        lines[span.end] += appended
        return {**texts, rel: "\n".join(lines)}

    return edit


def _append(rel: str, appended: str) -> _Edit:
    return lambda texts: {**texts, rel: f"{texts[rel]}\n{appended}\n"}


def _crlf(rel: str) -> _Edit:
    return lambda texts: {**texts, rel: texts[rel].replace("\n", "\r\n")}


SPAN_CHANGED = "span changed"


def _changed(rel: str) -> str:
    """Regex for a changed-span problem of ``rel``."""
    return rf"^{re.escape(rel)}: {SPAN_CHANGED} "


def _outside(rel: str, text: str = "") -> str:
    """Regex for an out-of-span mention ``rel:first-last: text`` of ``rel``."""
    return rf"^{re.escape(rel)}:\d+-\d+: {text}"


# Edits that must trip, with regexes that must each match some problem. None of
# the hash cases names the field on its inserted lines.
PIN_TRIPS: dict[str, tuple[_Edit, tuple[str, ...]]] = {
    "setext-pipe-text-in-claim-scope": (
        _in_span(EVAL_AUDIT, 2, "| SDK 0.27.x\n==========\n"),
        (_changed(EVAL_AUDIT),),
    ),
    "indented-fence-hiding-atx-in-reference": (
        _in_span(EVAL_AUDIT_REFERENCE, 2, "    ```\n# SDK 0.27.x\n    ```\n"),
        (_changed(EVAL_AUDIT_REFERENCE),),
    ),
    "html-heading-in-claim-scope": (
        _in_span(EVAL_AUDIT, 2, "<h3>SDK 0.27.x</h3>\n"),
        (_changed(EVAL_AUDIT),),
    ),
    "field-named-outside-every-span": (
        _append(EVALUATION_OPTIONS, "On SDK 0.27.x, set `task_type` to `exact_match`."),
        (_outside(EVALUATION_OPTIONS, r"On SDK 0\.27\.x, set `task_type` "),),
    ),
    **{
        f"soft-wrapped-task-{word}-outside-every-span": (
            _append(
                EVALUATION_OPTIONS,
                f"For SDK 0.27.x, set the task\n{word} to `exact_match`.",
            ),
            (
                _outside(
                    EVALUATION_OPTIONS,
                    rf"For SDK 0\.27\.x, set the task {word} to `exact_match`\.$",
                ),
            ),
        )
        for word in ("category", "type")
    },
    "field-named-on-the-heading-ending-fields": (
        _on_span_end(SETUP_DECORATOR, " (task_type on SDK 0.27.x)"),
        (_outside(SETUP_DECORATOR, r"#{1,3} .*\(task_type on SDK 0\.27\.x\)$"),),
    ),
    "hidden-heading-ends-claim-scope-early": (
        _in_span(EVAL_AUDIT, 2, "## Hidden\n"),
        (_changed(EVAL_AUDIT), _outside(EVAL_AUDIT)),
    ),
    "hidden-heading-ends-fields-early": (
        _in_span(SETUP_DECORATOR, 2, "## Hidden\n"),
        (_changed(SETUP_DECORATOR), _outside(SETUP_DECORATOR)),
    ),
    "trailing-space-in-fields": (
        _trailing_space(SETUP_DECORATOR),
        (_changed(SETUP_DECORATOR),),
    ),
}
# Edits that must stay green.
PIN_HOLDS: dict[str, _Edit] = {
    **{
        f"unrelated-line-around-span-{rel.split('/')[1]}": _around_span(
            rel, "Run the audit weekly.\n"
        )
        for rel in (EVAL_AUDIT, SETUP_DECORATOR)
    },
    **{
        f"front-matter-version-bump-{rel.split('/')[1]}": _version_bump(rel)
        for rel in (EVAL_AUDIT, SETUP_DECORATOR)
    },
    "crlf-line-endings": _crlf(EVAL_AUDIT_REFERENCE),
}


def _rename_anchor(rel: str) -> _Edit:
    def edit(texts: dict[str, str]) -> dict[str, str]:
        span = _span(rel, texts[rel], PINNED_TASK_TYPE_SPANS[rel]["anchor"])
        lines = _lines(texts[rel])
        lines[span.start] += " (renamed)"
        return {**texts, rel: "\n".join(lines)}

    return edit


# Anchor and file problems that must be collected, with the problem expected.
ANCHOR_TRIPS: dict[str, tuple[_Edit, str]] = {
    "duplicated-fields-anchor": (
        _in_span(SETUP_DECORATOR, 2, "### Fields\n"),
        f"{SETUP_DECORATOR}: anchor '### Fields' occurs 2 times; it must occur once",
    ),
    "renamed-claim-scope-anchor": (
        _rename_anchor(EVAL_AUDIT),
        f"{EVAL_AUDIT}: anchor '## Claim Scope' occurs 0 times; it must occur once",
    ),
    "missing-pinned-reference": (
        lambda texts: {
            rel: text for rel, text in texts.items() if rel != SETUP_DECORATOR_REFERENCE
        },
        f"{SETUP_DECORATOR_REFERENCE}: pinned file is not scanned",
    ),
}


def test_in_scope_pattern_names_the_field_only() -> None:
    wrong = {
        sample: expected
        for sample, expected in IN_SCOPE_SAMPLES.items()
        if bool(IN_SCOPE_RE.search(sample)) != expected
    }
    assert not wrong, f"IN_SCOPE_RE misclassifies (sample -> expected): {wrong}"


def test_task_type_spans_are_pinned(repo_root: Path) -> None:
    texts = _scanned(repo_root)
    assert all(f"skills/{skill}/SKILL.md" in texts for skill in SKILLS)
    failure = _pin_failure(texts, PINNED_TASK_TYPE_SPANS, _floor(repo_root))
    assert not failure, failure


@pytest.mark.parametrize("case", PIN_TRIPS)
def test_task_type_span_pin_trips(repo_root: Path, case: str) -> None:
    """A pin that flags nothing is no check: each edit, placed by line number
    from the span (never by searching prose), must be reported."""
    texts = _scanned(repo_root)
    assert not _span_problems(texts, PINNED_TASK_TYPE_SPANS)
    edit, expected = PIN_TRIPS[case]
    problems = _span_problems(edit(texts), PINNED_TASK_TYPE_SPANS)
    unmatched = [e for e in expected if not any(re.search(e, p) for p in problems)]
    assert not unmatched, f"{case}: no problem matches {unmatched} among {problems}"


@pytest.mark.parametrize("case", PIN_HOLDS)
def test_task_type_span_pin_holds(repo_root: Path, case: str) -> None:
    texts = _scanned(repo_root)
    problems = _span_problems(PIN_HOLDS[case](texts), PINNED_TASK_TYPE_SPANS)
    assert not problems, f"{case}: {problems}"


@pytest.mark.parametrize("case", ANCHOR_TRIPS)
def test_task_type_anchor_problem_is_reported_with_instruction(
    repo_root: Path, case: str
) -> None:
    floor = _floor(repo_root)
    edit, expected = ANCHOR_TRIPS[case]
    failure = _pin_failure(edit(_scanned(repo_root)), PINNED_TASK_TYPE_SPANS, floor)
    assert expected in failure.split("\n"), f"{case}: {failure}"
    assert _pin_instruction(floor) in failure, f"{case}: {failure}"


@pytest.mark.parametrize("trips", [True, False], ids=["lone-cr-trips", "crlf-holds"])
def test_task_type_span_pin_reads_line_endings_from_bytes(
    repo_root: Path, tmp_path: Path, trips: bool
) -> None:
    """Through the same file loader: a lone CR replacing one LF of a pinned
    reference changes its hash; CRLF for every LF does not."""
    for skill in SKILLS:
        shutil.copytree(repo_root / "skills" / skill, tmp_path / "skills" / skill)
    path = tmp_path / EVAL_AUDIT_REFERENCE
    raw = path.read_bytes()
    if trips:
        # The first LF not followed by LF: one before a blank line would make CRLF.
        raw = re.sub(rb"\n(?!\n)", b"\r", raw, count=1)
        assert b"\r" in raw and b"\r\n" not in raw
    else:
        raw = raw.replace(b"\n", b"\r\n")
    path.write_bytes(raw)
    problems = _span_problems(_scanned(tmp_path), PINNED_TASK_TYPE_SPANS)
    if trips:
        changed = _changed(EVAL_AUDIT_REFERENCE)
        assert any(re.search(changed, p) for p in problems), problems
    else:
        assert not problems, problems


def test_task_type_span_ends_only_at_its_level_or_shallower(repo_root: Path) -> None:
    """A deeper heading inside a span does not end it: re-pinned with a
    ``####`` line inside Claim Scope, a line added below that heading trips."""
    texts = _in_span(EVAL_AUDIT, 2, "#### Detail\n")(_scanned(repo_root))
    anchor = PINNED_TASK_TYPE_SPANS[EVAL_AUDIT]["anchor"]
    pins = {
        **PINNED_TASK_TYPE_SPANS,
        EVAL_AUDIT: {
            "anchor": anchor,
            "sha256_16": _span(EVAL_AUDIT, texts[EVAL_AUDIT], anchor).sha256_16,
        },
    }
    assert not _span_problems(texts, pins)
    edited = _in_span(EVAL_AUDIT, 4, "Run the audit weekly.")(texts)
    assert any(
        f"{EVAL_AUDIT}: {SPAN_CHANGED}" in p for p in _span_problems(edited, pins)
    ), "a line below a deeper heading inside the span was not covered"


def test_task_type_guidance_is_version_conditional(repo_root: Path) -> None:
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
        paragraphs = _paragraphs((repo_root / rel).read_text(encoding="utf-8"))

        if not any(
            newer_sdk_re.search(p)
            and TASK_TYPE_RE.search(p)
            and FACT_ID in POINTER_RE.findall(p)
            for p in paragraphs
        ):
            problems.append(
                f"{rel}: no paragraph ties `task_type` to the floor and later with "
                f"`see version-matrix: {FACT_ID}`"
            )

        if not any(
            older_sdk_re.search(p)
            and DO_NOT_PASS_RE.search(p)
            and TASK_TYPE_RE.search(p)
            and VALIDATION_ERROR_RE.search(p)
            and EXTRA_FORBIDDEN_RE.search(p)
            and ABSTAIN_RE.search(p)
            for p in paragraphs
        ):
            problems.append(
                f"{rel}: no below-the-floor paragraph saying do not pass `task_type`, "
                "that it raises ValidationError 'Extra inputs are not permitted', "
                "and that the audit abstains"
            )

        flat = " ".join(paragraphs)
        problems.extend(
            f"{rel}: stale universal claim {claim!r}"
            for claim in STALE_CLAIMS
            if claim in flat
        )

    assert not problems, "\n".join(problems)


def _passes_task_type_to_evaluation_options(code: str) -> bool:
    for node in ast.walk(ast.parse(code)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == "EvaluationOptions" and any(
            keyword.arg == "task_type" for keyword in node.keywords
        ):
            return True
    return False


def test_task_type_reference_floor_matches_version_matrix(
    repo_root: Path, sync_map: dict
) -> None:
    floor = _floor(repo_root)
    for skill in SKILLS:
        floors = sync_map["skills"][skill].get("python_version_floors") or {}
        assert floors.get(REFERENCE) == floor, (
            f"sync_map.yml {skill}.python_version_floors[{REFERENCE!r}] = "
            f"{floors.get(REFERENCE)!r}; the `{FACT_ID}` matrix row says {floor!r}"
        )
        assert "SKILL.md" not in floors, f"{skill}: SKILL.md must stay unfloored"

        path = repo_root / "skills" / skill / REFERENCE
        assert f"Requires `traigent>={floor}`" in path.read_text(encoding="utf-8"), (
            f"{path.relative_to(repo_root)} must state `Requires `traigent>={floor}``"
        )
        snippets = [
            s
            for s in collect_runnable_file(skill, path)
            if s.language.lower() == "python"
        ]
        assert any(_passes_task_type_to_evaluation_options(s.text) for s in snippets), (
            f"{path.relative_to(repo_root)}: no ```python runnable block calls "
            "EvaluationOptions(..., task_type=...)"
        )


def test_task_type_accepted_iff_installed_sdk_at_or_above_floor(
    repo_root: Path, pytestconfig: pytest.Config
) -> None:
    try:
        from traigent.api.decorators import EvaluationOptions
    except ImportError:
        pytest.skip("traigent.api.decorators.EvaluationOptions is not importable")
    import pydantic

    floor = Version(_floor(repo_root))
    label = _sdk_version_label(pytestconfig)
    installed = Version(importlib.metadata.version("traigent"))
    if label != "develop":
        # Also enforced by test_public_installability; repeated so this module's
        # verdict cannot be about a different SDK than the bucket it reports.
        assert installed == Version(label), (
            f"bucket {label} but traigent {installed} is installed"
        )

    if label == "develop" or installed >= floor:
        options = EvaluationOptions(task_type="exact_match")
        assert options.task_type == "exact_match"
        return

    with pytest.raises(pydantic.ValidationError) as excinfo:
        EvaluationOptions(task_type="exact_match")
    assert any(
        tuple(error["loc"]) == ("task_type",) and error["type"] == "extra_forbidden"
        for error in excinfo.value.errors()
    ), excinfo.value.errors()
