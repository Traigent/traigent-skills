"""Semantic skill lints — teaching rules the SDK-signature contract cannot see.

The released/develop contract tests validate that taught imports, symbols, and
``traigent.*``-rooted call kwargs exist in the installed wheel. They are blind to
two whole classes of wrong teaching, because the offending call is on a *user*
object (a ``@traigent.optimize``-decorated function), not a ``traigent.*`` name,
and because the real method signatures are permissive (``**algorithm_kwargs``):

1. ``func.optimize(dataset=...)`` / ``func.optimize_sync(dataset=...)`` — neither
   ``optimize`` nor ``optimize_sync`` has a ``dataset`` parameter (it is swallowed
   by ``**algorithm_kwargs`` and silently ignored). The evaluation dataset belongs
   on the decorator: ``@traigent.optimize(evaluation={"eval_dataset": ...})`` or
   the ``eval_dataset=`` shorthand.
2. ``results = func.optimize(...)`` with no ``await`` — ``OptimizedFunction.optimize``
   is a coroutine; assigning it without ``await`` (or ``asyncio.run(...)``) binds a
   never-run coroutine, not an ``OptimizationResult``. Top-level scripts must use the
   sync convenience ``func.optimize_sync(...)``.

Three more #8 P0 classes the signature contract also cannot catch (the call target
has a ``**kwargs`` so unknown kwargs pass the signature check, the constraint is on a
value rather than a name, or the kwarg is rejected only at runtime):

3. ``ExecutionOptions(runtime=/js_module=/js_function=/...)`` — removed JS-bridge fields;
   ``ExecutionOptions`` is ``extra="forbid"`` so any non-field kwarg raises
   ``ValidationError``. Validated here against the *installed* ``ExecutionOptions`` fields.
4. ``ExecutionOptions(reps_per_trial=<non-1>)`` — a valid field name but enterprise-gated;
   any value other than ``1`` is rejected at construction on the standard tier.
5. ``@traigent.optimize(validate_providers=...)`` — not a real kwarg (absorbed by the
   decorator's ``**runtime_overrides`` at the signature level, rejected at runtime); use
   the ``TRAIGENT_SKIP_PROVIDER_VALIDATION`` env var.
6. ``scoring_function`` / ``metric_functions`` callbacks are bound **by parameter name**;
   the first parameter must be ``output`` (the model output). Naming it ``prediction`` /
   ``pred`` means it is never supplied — the callback raises, is swallowed, and the metric
   silently scores ``0.0`` (pinning the objective to 0). Verified against #8 P1.

All shipped repo-wide (see traigent-skills#8) and survived the signature contract.
These lints gate those classes directly.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import yaml
from packaging.version import Version

from .extract import _iter_fenced_blocks, _paragraph_text_by_line

# .optimize(dataset=  /  .optimize_sync( dataset = ...   (robust to whitespace;
# works on unparseable illustrative blocks too, since it is line-based)
DATASET_ON_OPTIMIZE_RE = re.compile(r"\.optimize(?:_sync)?\s*\(\s*dataset\s*=")
# reps_per_trial=<int> with a literal value other than 1
REPS_PER_TRIAL_RE = re.compile(r"\breps_per_trial\s*=\s*(\d+)")
VALIDATE_PROVIDERS_RE = re.compile(r"\bvalidate_providers\s*=")
# Match installs of the `traigent` package itself (bare, quoted, with extras,
# or with a version spec) — but NOT sibling packages like `traigent-analytics`.
PIP_INSTALL_TRAIGENT_RE = re.compile(
    r"\bpip\s+install\b[^#`]*[\s\"']traigent(?![\w.-])(?:\[[^\]]*\])?", re.IGNORECASE
)


def test_analyze_guidance_sdk_floor_names_a_releasable_final_version(
    repo_root: Path,
) -> None:
    sync_map = yaml.safe_load((repo_root / "sync_map.yml").read_text(encoding="utf-8"))
    floor = sync_map["skills"]["traigent-analyze-guidance"]["min_sdk_version"]
    parsed = Version(str(floor))

    assert parsed == Version("0.21.3")
    assert not parsed.is_devrelease, (
        "a dev floor cannot distinguish an older develop build that lacks "
        "the taught guidance surface"
    )
LITERAL_FIRST_RUN_HEADING_RE = re.compile(
    r"(?m)^### Literal First Run \(execution-only agents\)\s*$"
)
FENCED_BASH_BLOCK_RE = re.compile(r"(?ms)^```bash\n(.*?)\n```")
NEXT_RUN_IP_BANNED_SUBSTRINGS = (
    "difficulty",
    "informativeness",
    "irt",
    "fisher",
    "threshold",
    "formula",
    "seed_signal",
)
NEXT_RUN_LOCAL_DECISION_PATTERNS = {
    "symptom_action_table": re.compile(
        r"(?is)\|\s*symptom\s*\|.*\|\s*(?:action|operation|recommendation|next)\s*\|"
    ),
    "when_do_rule": re.compile(
        r"(?im)^\s*(?:[-*]\s*)?when\s+[^.\n]{1,120}\s+"
        r"(?:do|run|choose|recommend|promote|gate|curate|audit|reflect|score)\b"
    ),
    "if_then_rule": re.compile(
        r"(?im)^\s*(?:[-*]\s*)?if\s+[^.\n]{1,120}\s+then\s+"
        r"(?:do|run|choose|recommend|promote|gate|curate|audit|reflect|score)\b"
    ),
}
ALLOWED_NEXT_STEP_ACTION_LABELS = {
    "add_safety_gate",
    "adjust_config_space",
    "audit_evaluator_quality",
    "compare_with_baseline",
    "curate_evaluation_set",
    "expand_dataset",
    "improve_evaluator",
    "promote_winner",
    "refine_metric",
    "rerun_larger_sample",
    "run_optimization",
    "score_evaluation_set",
    "validate_holdout",
    "wait",
}
FORBIDDEN_EXACT_LIFECYCLE_TOKENS = {
    "artifact_states",
    "audit_evaluator",
    "audit_stale",
    "blocker_codes",
    "compare_baseline",
    "LC_V1_DERIVED",
    "ranked_operations",
    "reason_code",
    "result_stale",
    "run_holdout",
    "score-stale",
    "score_examples",
    "score_stale",
    "scored-against",
    "scored_against",
    "scored-needs-tuning",
    "scored_needs_tuning",
    "smartopt_available",
    "synth_harder_examples",
    "target_artifact",
    "tied_with_baseline",
    "trust_label",
    "unaudited",
    "unknown_freshness",
    "validated_on_holdout",
}
FORBIDDEN_CONTEXTUAL_STATE_TOKENS = {
    "audited",
    "audit_stale",
    "baseline",
    "blocked",
    "broken",
    "defined",
    "degraded",
    "empty",
    "noisy",
    "optimized",
    "optimizing",
    "populated",
    "promotable",
    "regressed",
    "scored",
    "trusted",
    "undefined",
}
LIFECYCLE_CONTEXT_RE = re.compile(
    r"\b("
    r"artifact[-_ ]?(?:lifecycle|state|states)"
    r"|cross[-_ ]artifact"
    r"|per[-_ ]artifact"
    r"|promotion[-_ ]rule"
    r"|state\s+(?:label|labels|machine|machines|vocab|vocabulary|vocabularies)"
    r"|states?\s+(?:for|of)"
    r"|trust\s*/?\s*promotion"
    r")\b",
    re.IGNORECASE,
)
ALGORITHM_GUIDANCE_RESTAMP_FILES = (
    "skills/traigent-boost-agent/SKILL.md",
    "skills/traigent-recipe-text2sql/SKILL.md",
    "skills/traigent-recipe-text2sql/references/quickstart_text2sql.md",
    "skills/traigent-optimize-run/SKILL.md",
    "skills/traigent-optimize-run/references/algorithms.md",
    "skills/traigent-setup-decorator/SKILL.md",
    "skills/traigent-setup-decorator/references/execution-modes.md",
    "skills/traigent-setup-quickstart/SKILL.md",
    "skills/traigent-setup-quickstart/references/installation-extras.md",
    "skills/traigent-analyze-guidance/references/preflight.md",
    "skills/traigent-optimize-config-space/references/structural-spine.md",
)
ALGORITHM_GUIDANCE_BANNED_SNIPPETS = (
    ("stale SDK 0.18 algorithm stamp", "verified against SDK 0.18.x"),
    ("stale SDK 0.19 algorithm stamp", "verified against SDK 0.19.x"),
    (
        "stale no-credentials error",
        "Cloud execution is required, but backend session creation failed",
    ),
    ("stale smart-algorithm error route", "without cloud credentials"),
    (
        "connected real runs must not be steered to local search",
        'For a real run today, use `algorithm="grid"` or `algorithm="random"`',
    ),
    (
        "connected text2SQL runs must not default to random",
        'Real run (`algorithm="random"`',
    ),
    (
        "connected text2SQL runs must not default to random",
        'offline=False`, `algorithm="random"`',
    ),
    (
        "quickstart real path must not default to random",
        'offline, algorithm = False, "random"',
    ),
    (
        "auto is an executable connected path",
        "only `grid` and `random` are executable today",
    ),
    (
        "smart selector failure chain must mention SDK #1752, not just dispatcher rejection",
        "backend session dispatcher also only executes `grid`/`random`",
    ),
    (
        "smart selector failure chain must mention SDK #1752, not just dispatcher rejection",
        "backend session dispatcher only executes `grid`/`random`",
    ),
    (
        "smart selector failure chain must mention SDK #1752, not just dispatcher rejection",
        "backend also rejects them even when connected",
    ),
)
ALGORITHM_GUIDANCE_REQUIRED_SNIPPETS = {
    "skills/traigent-boost-agent/SKILL.md": (
        'For connected real runs, omit `algorithm` or use `algorithm="auto"`.'
    ),
    "skills/traigent-recipe-text2sql/SKILL.md": (
        '`offline=False`, omit `algorithm` or use `algorithm="auto"`'
    ),
    "skills/traigent-recipe-text2sql/references/quickstart_text2sql.md": (
        'offline, algorithm = False, "auto"'
    ),
}

# Fields of the INSTALLED ExecutionOptions (extra="forbid" → any other kwarg is invalid).
# None if the symbol can't be imported, in which case rule 3 no-ops for this run.
try:
    from traigent.api.decorators import ExecutionOptions as _ExecutionOptions

    _EXECUTION_OPTIONS_FIELDS: set[str] | None = set(
        inspect.signature(_ExecutionOptions).parameters
    ) - {"self"}
except Exception:  # pragma: no cover - SDK shape/availability guard
    _EXECUTION_OPTIONS_FIELDS = None

# Fields of the INSTALLED EvaluationOptions (extra="forbid" -> any other kwarg is invalid).
# Twin of the ExecutionOptions guard above -- added after #274 shipped
# `EvaluationOptions(task_type=...)`, a kwarg the released SDK rejects, in prose and a
# markdown table row that neither this fenced-python scan nor the fact-extraction contract
# ever read.
try:
    from traigent.api.decorators import EvaluationOptions as _EvaluationOptions

    _EVALUATION_OPTIONS_FIELDS: set[str] | None = set(
        inspect.signature(_EvaluationOptions).parameters
    ) - {"self"}
except Exception:  # pragma: no cover - SDK shape/availability guard
    _EVALUATION_OPTIONS_FIELDS = None

# Fields of the INSTALLED InjectionOptions -- same shape, cheap twin.
try:
    from traigent.api.decorators import InjectionOptions as _InjectionOptions

    _INJECTION_OPTIONS_FIELDS: set[str] | None = set(
        inspect.signature(_InjectionOptions).parameters
    ) - {"self"}
except Exception:  # pragma: no cover - SDK shape/availability guard
    _INJECTION_OPTIONS_FIELDS = None

# Name -> installed-fields lookup shared by the fenced-python, prose, and table scans below.
# A None value means the symbol could not be imported from the installed SDK, in which case
# every scan keyed off it no-ops for this run (matches the ExecutionOptions guard).
_OPTION_CLASS_NAMES = ("EvaluationOptions", "ExecutionOptions", "InjectionOptions")
_OPTION_CLASS_FIELDS: dict[str, set[str] | None] = {
    "EvaluationOptions": _EVALUATION_OPTIONS_FIELDS,
    "ExecutionOptions": _EXECUTION_OPTIONS_FIELDS,
    "InjectionOptions": _INJECTION_OPTIONS_FIELDS,
}


def _skill_markdown_files(repo_root: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    skills_root = repo_root / "skills"
    for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        out.append((skill_dir.name, skill_file))
        references = skill_dir / "references"
        if references.is_dir():
            out.extend((skill_dir.name, ref) for ref in sorted(references.glob("*.md")))
    return out


def _skill_doc_files(repo_root: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    skills_root = repo_root / "skills"
    for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if skill_file.is_file():
            out.append((skill_dir.name, skill_file))
        references = skill_dir / "references"
        if references.is_dir():
            out.extend(
                (skill_dir.name, ref)
                for ref in sorted(p for p in references.iterdir() if p.is_file())
            )
    return out


def _token_re(token: str) -> re.Pattern[str]:
    """Match a public vocabulary token without catching longer script/file names."""
    return re.compile(
        rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])",
        re.IGNORECASE,
    )


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _contract_skip_fence_lines(text: str) -> set[int]:
    skipped: set[int] = set()
    for block in _iter_fenced_blocks(text.splitlines()):
        if block.lines and block.lines[0].strip() == "# contract: skip":
            skipped.update(range(block.start_line, block.start_line + len(block.lines)))
    return skipped


def _literal_first_run_bash_block(text: str) -> str | None:
    heading = LITERAL_FIRST_RUN_HEADING_RE.search(text)
    if not heading:
        return None
    match = FENCED_BASH_BLOCK_RE.search(text, heading.end())
    if not match:
        return None
    return match.group(1)


def _scan_lifecycle_vocab_leaks(
    name: str, path: Path, text: str, repo_root: Path
) -> list[str]:
    violations: list[str] = []
    rel = path.resolve().relative_to(repo_root.resolve()).as_posix()

    for token in sorted(FORBIDDEN_EXACT_LIFECYCLE_TOKENS):
        if token in ALLOWED_NEXT_STEP_ACTION_LABELS:
            continue
        match = _token_re(token).search(text)
        if match:
            violations.append(
                f"LEAKED NEXT-RUN VOCAB  {rel}:{_line_for_offset(text, match.start())}\n"
                f"  token   : {token}\n"
                f"  problem : client-facing skills must present opaque posture prose and "
                f"returned command templates, not internal lifecycle vocabulary."
            )

    lines = text.splitlines()
    for index, line in enumerate(lines):
        window = "\n".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
        if not LIFECYCLE_CONTEXT_RE.search(window):
            continue
        for token in sorted(FORBIDDEN_CONTEXTUAL_STATE_TOKENS):
            if not _token_re(token).search(line):
                continue
            violations.append(
                f"LEAKED NEXT-RUN VOCAB  {rel}:{index + 1}\n"
                f"  token   : {token}\n"
                f"  problem : lifecycle/state prose in skills must stay opaque; do not "
                f"teach per-artifact state vocabulary."
            )
    return violations


def _python_blocks(text: str):
    for block in _iter_fenced_blocks(text.splitlines()):
        if block.language.lower() not in {"python", "py"}:
            continue
        if block.lines and block.lines[0].strip() == "# contract: skip":
            continue
        yield block


def _decorated_with_traigent_optimize(tree: ast.AST) -> set[str]:
    """Names of functions carrying an ``@traigent.optimize(...)`` decorator."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "optimize"
                and isinstance(target.value, ast.Name)
                and target.value.id == "traigent"
            ):
                names.add(node.name)
    return names


def _awaited_or_runner_call_ids(tree: ast.AST) -> set[int]:
    """ids() of Call nodes that are awaited or wrapped in ``asyncio.run(...)``."""
    ok: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            ok.add(id(node.value))
        if isinstance(node, ast.Call):
            fn = node.func
            is_asyncio_run = (
                isinstance(fn, ast.Attribute)
                and fn.attr == "run"
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "asyncio"
            )
            if is_asyncio_run:
                for arg in node.args:
                    if isinstance(arg, ast.Call):
                        ok.add(id(arg))
    return ok


def _scan_dataset_kwarg(name: str, path: Path, text: str, repo_root: Path) -> list[str]:
    violations: list[str] = []
    for block in _python_blocks(text):
        for offset, line in enumerate(block.lines):
            if DATASET_ON_OPTIMIZE_RE.search(line):
                lineno = block.start_line + offset
                rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
                violations.append(
                    f"DEAD TEACHING  {rel}:{lineno}\n"
                    f"  teaches : {line.strip()}\n"
                    f"  problem : optimize()/optimize_sync() have no `dataset` param; it is "
                    f"silently swallowed by **algorithm_kwargs and ignored.\n"
                    f"  fix     : move the dataset onto the decorator — "
                    f'@traigent.optimize(eval_dataset="...") — and call '
                    f"func.optimize_sync() / await func.optimize() with no dataset."
                )
    return violations


def _scan_unawaited_optimize(
    name: str, path: Path, text: str, repo_root: Path
) -> list[str]:
    violations: list[str] = []
    for block in _python_blocks(text):
        try:
            tree = ast.parse(block.text)
        except SyntaxError:
            continue  # illustrative fragment; signature contract handles imports
        decorated = _decorated_with_traigent_optimize(tree)
        if not decorated:
            continue
        ok_ids = _awaited_or_runner_call_ids(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            ):
                continue
            if node.func.attr != "optimize":
                continue
            recv = node.func.value
            if not (isinstance(recv, ast.Name) and recv.id in decorated):
                continue
            if id(node) in ok_ids:
                continue
            lineno = block.start_line + node.lineno - 1
            rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
            violations.append(
                f"DEAD TEACHING  {rel}:{lineno}\n"
                f"  teaches : {recv.id}.optimize(...) bound without await\n"
                f"  problem : OptimizedFunction.optimize is a coroutine; without await "
                f"(or asyncio.run) this binds a never-run coroutine, not a result.\n"
                f"  fix     : use {recv.id}.optimize_sync(...) at top level, or "
                f"await {recv.id}.optimize(...) inside async code."
            )
    return violations


def _callee_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _scan_executionoptions_kwargs(
    name: str, path: Path, text: str, repo_root: Path
) -> list[str]:
    if _EXECUTION_OPTIONS_FIELDS is None:
        return []
    violations: list[str] = []
    for block in _python_blocks(text):
        try:
            tree = ast.parse(block.text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and _callee_name(node.func) == "ExecutionOptions"
            ):
                continue
            bad = [
                kw.arg
                for kw in node.keywords
                if kw.arg and kw.arg not in _EXECUTION_OPTIONS_FIELDS
            ]
            if not bad:
                continue
            lineno = block.start_line + node.lineno - 1
            rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
            violations.append(
                f"DEAD TEACHING  {rel}:{lineno}\n"
                f"  teaches : ExecutionOptions({', '.join(b + '=' for b in bad)}...)\n"
                f"  problem : not a field of the installed ExecutionOptions (extra='forbid' "
                f"→ ValidationError at construction).\n"
                f"  fix     : remove the field; for JS apps use the native @traigent/sdk."
            )
    return violations


def _scan_evaluationoptions_kwargs(
    name: str, path: Path, text: str, repo_root: Path
) -> list[str]:
    if _EVALUATION_OPTIONS_FIELDS is None:
        return []
    violations: list[str] = []
    for block in _python_blocks(text):
        try:
            tree = ast.parse(block.text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and _callee_name(node.func) == "EvaluationOptions"
            ):
                continue
            bad = [
                kw.arg
                for kw in node.keywords
                if kw.arg and kw.arg not in _EVALUATION_OPTIONS_FIELDS
            ]
            if not bad:
                continue
            lineno = block.start_line + node.lineno - 1
            rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
            violations.append(
                f"DEAD TEACHING  {rel}:{lineno}\n"
                f"  teaches : EvaluationOptions({', '.join(b + '=' for b in bad)}...)\n"
                f"  problem : not a field of the installed EvaluationOptions (extra='forbid' "
                f"→ ValidationError at construction).\n"
                f"  fix     : remove the field; see references/evaluation-options.md for "
                f"the real fields."
            )
    return violations


def _scan_injectionoptions_kwargs(
    name: str, path: Path, text: str, repo_root: Path
) -> list[str]:
    if _INJECTION_OPTIONS_FIELDS is None:
        return []
    violations: list[str] = []
    for block in _python_blocks(text):
        try:
            tree = ast.parse(block.text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and _callee_name(node.func) == "InjectionOptions"
            ):
                continue
            bad = [
                kw.arg
                for kw in node.keywords
                if kw.arg and kw.arg not in _INJECTION_OPTIONS_FIELDS
            ]
            if not bad:
                continue
            lineno = block.start_line + node.lineno - 1
            rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
            violations.append(
                f"DEAD TEACHING  {rel}:{lineno}\n"
                f"  teaches : InjectionOptions({', '.join(b + '=' for b in bad)}...)\n"
                f"  problem : not a field of the installed InjectionOptions (extra='forbid' "
                f"→ ValidationError at construction).\n"
                f"  fix     : remove the field; see references/injection-modes.md for "
                f"the real fields."
            )
    return violations


# --- prose/table coverage -----------------------------------------------------
#
# The three scans above only see fenced ```python blocks. #274 shipped
# `EvaluationOptions(task_type=...)` as *prose* (an inline-backtick call in a
# paragraph) and as a markdown reference-table row -- neither is a fenced code
# block, so neither existing scan nor the fact-extraction contract in
# extract.py (which is also fenced-block-only for Python) ever reads them.
# These two scans are deliberately conservative: a false positive here is a
# spurious CI failure on legitimate "X raises/forbids Y" documentation, so
# both require a strong, local, unambiguous signal before flagging.

_OPTION_CALL_RE = re.compile(r"\b(" + "|".join(_OPTION_CLASS_NAMES) + r")\s*\(")
_KWARG_NAME_IN_SPAN_RE = re.compile(r"(?<![.\w])([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)")
# Same-context signal that a call span is being cited as INVALID (it raises, is
# forbidden, isn't a real field, ...) rather than taught as runnable -- mirrors
# extract.CLI_ABSENCE_RE's role for CLI mentions. Deliberately broad: any of
# these near the span means "do not flag", which only weakens detection in the
# safe direction (a missed real violation, never a false one).
_OPTION_ABSENCE_RE = re.compile(
    r"(?i)\b("
    r"raise[sd]?|rejects?|rejected|forbids?|invalid|"
    r"not\s+a\s+(?:real\s+)?(?:field|kwarg|parameter|argument)|"
    r"no\s+(?:client-side\s+)?field|"
    r"not\s+(?:currently\s+)?(?:supported|available)|"
    r"does(?:n't|\s+not)\s+exist|"
    r"extra\s+inputs\s+are\s+not\s+permitted|"
    r"validationerror|removed|retired|no\s+longer|"
    r"do\s+not\s+pass|never\s+pass|not\s+a\s+valid\b"
    r")\b"
)


def _fenced_line_numbers(text: str) -> set[int]:
    """1-indexed line numbers belonging to ANY fenced block (incl. its fences).

    Prose/table coverage must skip fenced python (already covered by the
    ast-based scans above, which parse it more precisely) and every other
    fenced language, so it only ever looks at true prose/table markdown.
    """
    fenced: set[int] = set()
    lines = text.splitlines()
    for block in _iter_fenced_blocks(lines):
        fenced.update(
            range(block.start_line - 1, block.start_line + len(block.lines) + 1)
        )
    return fenced


def _extract_call_span(
    lines: list[str], start_idx: int, open_pos: int, max_lines: int = 8
) -> str | None:
    """Text strictly between the '(' at (start_idx, open_pos) and its matching
    ')', scanning forward at most ``max_lines`` physical lines. ``None`` if the
    parens never balance within that bound (illustrative/truncated prose)."""
    depth = 0
    collected: list[str] = []
    for li in range(start_idx, min(start_idx + max_lines, len(lines))):
        segment = lines[li][open_pos:] if li == start_idx else lines[li]
        for ci, ch in enumerate(segment):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    collected.append(segment[:ci])
                    return "\n".join(collected)
        collected.append(segment)
    return None


def _scan_option_prose_kwargs(
    name: str, path: Path, text: str, repo_root: Path
) -> list[str]:
    violations: list[str] = []
    lines = text.splitlines()
    fenced = _fenced_line_numbers(text)
    paragraph_by_line = _paragraph_text_by_line(lines)
    for idx, line in enumerate(lines):
        lineno = idx + 1
        if lineno in fenced:
            continue
        for match in _OPTION_CALL_RE.finditer(line):
            cls_name = match.group(1)
            fields = _OPTION_CLASS_FIELDS.get(cls_name)
            if fields is None:
                continue
            open_pos = match.end() - 1
            span = _extract_call_span(lines, idx, open_pos)
            if span is None:
                continue
            kwarg_names = set(_KWARG_NAME_IN_SPAN_RE.findall(span))
            bad = sorted(k for k in kwarg_names if k not in fields)
            if not bad:
                continue
            paragraph = paragraph_by_line.get(idx, line)
            if _OPTION_ABSENCE_RE.search(paragraph):
                continue
            rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
            violations.append(
                f"DEAD TEACHING  {rel}:{lineno}\n"
                f"  teaches : {cls_name}({', '.join(b + '=' for b in bad)}...) in prose\n"
                f"  problem : not a field of the installed {cls_name} (extra='forbid' "
                f"→ ValidationError at construction), and the surrounding text does not "
                f"say so.\n"
                f"  fix     : remove the kwarg, or state plainly that it raises/is not a "
                f"field so the prose cannot be read as a runnable instruction."
            )
    return violations


_TABLE_HEADER_TRIGGER_RE = re.compile(r"(?i)\b(field|kwarg|parameter)s?\b")
_TABLE_ROW_RE = re.compile(r"^\s*\|(.*)\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BACKTICK_IDENT_RE = re.compile(r"^`([A-Za-z_][A-Za-z0-9_]*)`$")


def _table_cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _scan_option_field_tables(
    name: str, path: Path, text: str, repo_root: Path
) -> list[str]:
    """A reference table (header row says Field/Kwarg/Parameter) in a section
    that names exactly one of the three option classes must only list real
    fields of that class. Scoped to the innermost heading plus its immediate
    parent (at most two levels) so an unrelated mention elsewhere in a long
    document can never supply the class -- ambiguous or absent context means
    "skip", never "guess"."""
    violations: list[str] = []
    lines = text.splitlines()
    fenced = _fenced_line_numbers(text)
    stack: list[list] = []  # [level, [text parts]]

    idx = 0
    n = len(lines)
    while idx < n:
        lineno = idx + 1
        line = lines[idx]
        if lineno in fenced:
            idx += 1
            continue

        heading_match = _MD_HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append([level, [heading_match.group(2)]])
            idx += 1
            continue

        if stack and line.strip():
            for entry in stack:
                entry[1].append(line)

        if (
            idx + 1 < n
            and _TABLE_ROW_RE.match(line)
            and _TABLE_SEP_RE.match(lines[idx + 1])
        ):
            header_cells = _table_cells(line)
            if any(_TABLE_HEADER_TRIGGER_RE.search(c) for c in header_cells):
                candidates = stack[-2:]
                combined = "\n".join(" ".join(t) for _, t in candidates)
                mentioned = [c for c in _OPTION_CLASS_NAMES if c in combined]
                if len(mentioned) == 1 and _OPTION_CLASS_FIELDS.get(mentioned[0]) is not None:
                    cls_name = mentioned[0]
                    fields = _OPTION_CLASS_FIELDS[cls_name]
                    row_idx = idx + 2
                    while row_idx < n and _TABLE_ROW_RE.match(lines[row_idx]):
                        row_cells = _table_cells(lines[row_idx])
                        if row_cells:
                            ident_match = _BACKTICK_IDENT_RE.match(row_cells[0])
                            if ident_match:
                                field_name = ident_match.group(1)
                                row_text = " ".join(row_cells)
                                if (
                                    field_name not in fields
                                    and not _OPTION_ABSENCE_RE.search(row_text)
                                ):
                                    rel = path.resolve().relative_to(
                                        repo_root.resolve()
                                    ).as_posix()
                                    violations.append(
                                        f"DEAD TEACHING  {rel}:{row_idx + 1}\n"
                                        f"  teaches : {cls_name} field `{field_name}` "
                                        f"in a reference table\n"
                                        f"  problem : not a field of the installed "
                                        f"{cls_name} (extra='forbid' -> ValidationError "
                                        f"at construction).\n"
                                        f"  fix     : remove the row, or state plainly "
                                        f"that the field does not exist on the "
                                        f"installed SDK."
                                    )
                        row_idx += 1
        idx += 1
    return violations


def _scan_reps_per_trial(
    name: str, path: Path, text: str, repo_root: Path
) -> list[str]:
    violations: list[str] = []
    for block in _python_blocks(text):
        for offset, line in enumerate(block.lines):
            m = REPS_PER_TRIAL_RE.search(line)
            if not m or m.group(1) == "1":
                continue
            lineno = block.start_line + offset
            rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
            violations.append(
                f"DEAD TEACHING  {rel}:{lineno}\n"
                f"  teaches : {line.strip()}\n"
                f"  problem : reps_per_trial != 1 is enterprise-gated; rejected at "
                f"ExecutionOptions construction on the standard tier.\n"
                f"  fix     : drop reps_per_trial (default 1), or mark the block "
                f"`# contract: skip` as an Enterprise-only illustration."
            )
    return violations


def _scan_validate_providers(
    name: str, path: Path, text: str, repo_root: Path
) -> list[str]:
    violations: list[str] = []
    for block in _python_blocks(text):
        for offset, line in enumerate(block.lines):
            if VALIDATE_PROVIDERS_RE.search(line):
                lineno = block.start_line + offset
                rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
                violations.append(
                    f"DEAD TEACHING  {rel}:{lineno}\n"
                    f"  teaches : {line.strip()}\n"
                    f"  problem : validate_providers is not a real @traigent.optimize kwarg "
                    f"(rejected at runtime: 'Unknown keyword arguments').\n"
                    f"  fix     : set the TRAIGENT_SKIP_PROVIDER_VALIDATION=true env var instead."
                )
    return violations


def _scan_unfloored_pip_installs(
    name: str, path: Path, text: str, repo_root: Path
) -> list[str]:
    violations: list[str] = []
    skipped_lines = _contract_skip_fence_lines(text)
    for lineno, line in enumerate(text.splitlines(), start=1):
        if lineno in skipped_lines:
            continue
        if not PIP_INSTALL_TRAIGENT_RE.search(line):
            continue
        if re.search(r"[<>=!]=", line):
            continue
        rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
        violations.append(
            f"DEAD TEACHING  {rel}:{lineno}\n"
            f"  teaches : {line.strip()}\n"
            f"  problem : pip can resolve the PyPI placeholder package unless Traigent "
            f"installs carry an explicit >= floor.\n"
            f"  fix     : use `pip install \"traigent>=0.19\"` or "
            f"`pip install \"traigent[recommended]>=0.19\"`."
        )
    return violations


def _scan_scoring_first_param(
    name: str, path: Path, text: str, repo_root: Path
) -> list[str]:
    """A callback whose 2nd param is `expected` (the scoring/metric signature) must name
    its 1st param `output` — the SDK binds these by name; `prediction`/`pred` → silent 0.0."""
    violations: list[str] = []
    for block in _python_blocks(text):
        try:
            tree = ast.parse(block.text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args.args
            if len(args) >= 2 and args[1].arg == "expected" and args[0].arg != "output":
                lineno = block.start_line + node.lineno - 1
                rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
                violations.append(
                    f"DEAD TEACHING  {rel}:{lineno}\n"
                    f"  teaches : def {node.name}({args[0].arg}, expected, ...)\n"
                    f"  problem : scoring_function/metric_functions bind by param NAME; first "
                    f"param must be `output`. `{args[0].arg}` is never supplied → metric "
                    f"silently scores 0.0 and pins the objective to 0.\n"
                    f"  fix     : rename the first parameter to `output`."
                )
    return violations


def test_no_dataset_kwarg_on_optimize(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(
            _scan_dataset_kwarg(name, path, path.read_text(encoding="utf-8"), repo_root)
        )
    assert not violations, "\n\n".join(["", *violations, ""])


def test_scoring_callbacks_first_param_is_output(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(
            _scan_scoring_first_param(
                name, path, path.read_text(encoding="utf-8"), repo_root
            )
        )
    assert not violations, "\n\n".join(["", *violations, ""])


def test_executionoptions_kwargs_are_real_fields(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(
            _scan_executionoptions_kwargs(
                name, path, path.read_text(encoding="utf-8"), repo_root
            )
        )
    assert not violations, "\n\n".join(["", *violations, ""])


def test_evaluationoptions_kwargs_are_real_fields(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(
            _scan_evaluationoptions_kwargs(
                name, path, path.read_text(encoding="utf-8"), repo_root
            )
        )
    assert not violations, "\n\n".join(["", *violations, ""])


def test_injectionoptions_kwargs_are_real_fields(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(
            _scan_injectionoptions_kwargs(
                name, path, path.read_text(encoding="utf-8"), repo_root
            )
        )
    assert not violations, "\n\n".join(["", *violations, ""])


def test_option_prose_kwargs_are_real_fields(repo_root: Path) -> None:
    """The #274 gap: EvaluationOptions(task_type=...) shipped as an inline-backtick
    call in a paragraph, which no fenced-block scan reads. Same validation, applied
    to prose outside fenced code."""
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(
            _scan_option_prose_kwargs(
                name, path, path.read_text(encoding="utf-8"), repo_root
            )
        )
    assert not violations, "\n\n".join(["", *violations, ""])


def test_option_field_tables_are_real_fields(repo_root: Path) -> None:
    """The other #274 gap: task_type shipped as a row in a markdown "Fields"
    reference table. Same validation, applied to table rows scoped to a section
    that unambiguously names one of the three option classes."""
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(
            _scan_option_field_tables(
                name, path, path.read_text(encoding="utf-8"), repo_root
            )
        )
    assert not violations, "\n\n".join(["", *violations, ""])


def test_no_enterprise_reps_per_trial(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(
            _scan_reps_per_trial(
                name, path, path.read_text(encoding="utf-8"), repo_root
            )
        )
    assert not violations, "\n\n".join(["", *violations, ""])


def test_no_validate_providers_kwarg(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(
            _scan_validate_providers(
                name, path, path.read_text(encoding="utf-8"), repo_root
            )
        )
    assert not violations, "\n\n".join(["", *violations, ""])


def test_traigent_pip_installs_are_version_floored(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_doc_files(repo_root):
        violations.extend(
            _scan_unfloored_pip_installs(
                name, path, path.read_text(encoding="utf-8"), repo_root
            )
        )
    assert not violations, "\n\n".join(["", *violations, ""])


def test_literal_quickstart_block_matches_canonical_script(repo_root: Path) -> None:
    skill_path = repo_root / "skills" / "traigent-setup-quickstart" / "SKILL.md"
    script_path = (
        repo_root
        / "skills"
        / "traigent-setup-quickstart"
        / "references"
        / "literal-quickstart.sh"
    )
    skill_rel = skill_path.relative_to(repo_root).as_posix()
    script_rel = script_path.relative_to(repo_root).as_posix()

    block = _literal_first_run_bash_block(skill_path.read_text(encoding="utf-8"))
    assert block is not None, f"{skill_rel}: missing Literal First Run bash block"

    expected = script_path.read_text(encoding="utf-8").rstrip("\n")
    assert block == expected, (
        f"Literal First Run block in {skill_rel} must be byte-identical to {script_rel}"
    )


def test_optimize_method_calls_are_awaited_or_sync(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        violations.extend(
            _scan_unawaited_optimize(
                name, path, path.read_text(encoding="utf-8"), repo_root
            )
        )
    assert not violations, "\n\n".join(["", *violations, ""])


def test_no_leaked_next_run_lifecycle_vocab_in_skill_markdown(repo_root: Path) -> None:
    violations: list[str] = []
    for name, path in _skill_markdown_files(repo_root):
        if path.name != "SKILL.md":
            continue
        text = path.read_text(encoding="utf-8")
        violations.extend(_scan_lifecycle_vocab_leaks(name, path, text, repo_root))
    assert not violations, "\n\n".join(["", *violations, ""])


def test_algorithm_guidance_matches_sdk_020(repo_root: Path) -> None:
    violations: list[str] = []
    for rel in ALGORITHM_GUIDANCE_RESTAMP_FILES:
        path = repo_root / rel
        text = path.read_text(encoding="utf-8")
        for label, snippet in ALGORITHM_GUIDANCE_BANNED_SNIPPETS:
            offset = text.find(snippet)
            if offset == -1:
                continue
            violations.append(
                f"{rel}:{_line_for_offset(text, offset)}: {label}: {snippet!r}"
            )

    for rel, snippet in ALGORITHM_GUIDANCE_REQUIRED_SNIPPETS.items():
        path = repo_root / rel
        text = path.read_text(encoding="utf-8")
        if snippet not in text:
            violations.append(f"{rel}: missing required SDK 0.20.0 guidance {snippet!r}")

    assert not violations, "\n".join(violations)


def test_next_run_skill_stays_service_decided_thin_client(repo_root: Path) -> None:
    path = repo_root / "skills" / "traigent-analyze-guidance" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(repo_root).as_posix()

    # traigent-analyze-guidance is a merged, three-mode skill (2026-07 taxonomy
    # consolidation): Mode A (pre-run plan) and Mode B (post-run, portal-tracked)
    # must stay a thin client that defers next-step decisions to the Traigent
    # service — that is what this lint guards. Mode C is explicitly the
    # offline/local-diagnosis fallback (merged in from the former
    # traigent-iterate skill) for when there is no service payload; local
    # heuristic vocabulary (difficulty, thresholds, symptom/action tables) is
    # its documented purpose, so it is out of scope for this lint.
    mode_c_match = re.search(r"(?m)^## Mode C\b.*$", text)
    next_mode_match = re.search(r"(?m)^## See Also\b", text)
    if mode_c_match and next_mode_match and next_mode_match.start() > mode_c_match.start():
        scoped_text = text[: mode_c_match.start()] + text[next_mode_match.start() :]
    else:
        scoped_text = text
    lowered = scoped_text.lower()

    violations: list[str] = []
    for banned in NEXT_RUN_IP_BANNED_SUBSTRINGS:
        if banned in lowered:
            violations.append(f"{rel}: banned local-decision term {banned!r}")
    for label, pattern in NEXT_RUN_LOCAL_DECISION_PATTERNS.items():
        match = pattern.search(scoped_text)
        if not match:
            continue
        line = text.count("\n", 0, text.find(match.group(0))) + 1
        violations.append(f"{rel}:{line}: banned local-decision pattern {label!r}")

    assert not violations, "\n".join(violations)
    assert re.search(
        r"\bfetch(?:es)?\b[\s\S]{0,160}\bTraigent service\b", text, re.IGNORECASE
    ), "traigent-analyze-guidance must stay service-backed, not standalone"
    assert re.search(
        r"\bdecision comes from the Traigent service\b", text, re.IGNORECASE
    ), "traigent-analyze-guidance must state that the next-step decision comes from the service"
    # The supported surfaces (the retired `traigent guidance *` / `traigent
    # next-steps` CLI has no successor CLI): the post-run decision comes from
    # the backend decision brief on the traigent-analytics MCP server, and the
    # pre-run plan comes from `traigent plan` / `get_optimization_plan`.
    assert "analytics_get_run_decision_brief" in text, (
        "traigent-analyze-guidance must fetch the post-run decision brief via "
        "the traigent-analytics MCP tool"
    )
    assert "traigent plan" in text, (
        "traigent-analyze-guidance must fetch the pre-run plan via the "
        "supported `traigent plan` CLI / `get_optimization_plan` MCP tool"
    )
    assert re.search(
        r"Never execute a server-supplied shell fragment", text
    ), "the decision brief must not be turned into a shell command"


def test_retired_guidance_cli_is_not_reintroduced(repo_root: Path) -> None:
    """The SDK retired `traigent guidance *` and `traigent next-steps` on
    2026-08-03 (absent from 0.26.0). Skills must run the supported surfaces
    instead — the decision brief MCP tool post-run and `traigent plan` pre-run
    — and may describe the retirement only without presenting the retired
    commands as runnable. docs/version-matrix.md is the one place the retired
    command name remains, as version history."""
    banned = ("traigent guidance", "traigent next-steps")
    for rel in (
        "skills/traigent-analyze-guidance/SKILL.md",
        "skills/traigent-analyze-results/SKILL.md",
        "skills/traigent-setup-quickstart/SKILL.md",
        "README.md",
    ):
        text = (repo_root / rel).read_text(encoding="utf-8")
        for command in banned:
            assert command not in text, (
                f"{rel}: teaches the retired command {command!r}; repoint to "
                "the decision brief (analytics_get_run_decision_brief) or "
                "`traigent plan`, or describe the retirement without the "
                "runnable command string"
            )


def test_plan_cli_backend_url_resolution_stays_portable(repo_root: Path) -> None:
    """The portable URL-resolution teaching (flag -> env -> stored auth-login
    URL -> local default) moved with the surviving `traigent plan` command
    when `next-steps` was retired."""
    path = repo_root / "skills" / "traigent-setup-quickstart" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(repo_root).as_posix()

    assert re.search(
        r"`traigent plan` CLI command resolves[\s>]+`--backend-url`", text
    ), f"{rel}: the backend-url exception note must name `traigent plan`"
    for guidance_path in (
        repo_root / "skills" / "traigent-analyze-guidance" / "SKILL.md",
        path,
    ):
        guidance_text = guidance_path.read_text(encoding="utf-8")
        guidance_rel = guidance_path.relative_to(repo_root).as_posix()
        assert "`TRAIGENT_BACKEND_URL` must be set" not in guidance_text, (
            f"{guidance_rel}: must not teach env-var-only setup as mandatory"
        )
        assert "if `TRAIGENT_BACKEND_URL` is not set" not in guidance_text, (
            f"{guidance_rel}: --backend-url is not just a fallback for unset env vars"
        )
        assert "connection-refused" not in guidance_text.lower(), (
            f"{guidance_rel}: do not predict the old default failure mode"
        )


def test_decision_brief_protocol_validates_backend_payload(
    repo_root: Path,
) -> None:
    """Mode B's supported surface is the backend decision brief. The skill
    must show the exact tool invocation, narrate the v0 payload fields in the
    backend's own terms, and preserve the honest limitation that the retired
    guidance CLI's execution/receipt lifecycle has no current SDK
    replacement."""
    path = repo_root / "skills" / "traigent-analyze-guidance" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(repo_root).as_posix()

    assert re.search(
        r"analytics_get_run_decision_brief\(\s*"
        r"project_id\s*=\s*\"[^\"]+\",\s*"
        r"run_id\s*=\s*\"[^\"]+\",\s*"
        r"intent\s*=\s*\"iterate\",?\s*\)",
        text,
    ), f"{rel}: Mode B must show the exact decision-brief tool invocation"

    required = (
        "`decision_brief`",
        "`headline`",
        "`confidence`",
        "`recommended_action`",
        "`evidence`",
        "`drilldowns`",
        "`warnings`",
        "never upgrade a `low`/`medium` confidence",
        "`recommended_action.kind`",
        "exactly as returned",
    )
    missing = [marker for marker in required if marker not in text]
    assert not missing, f"{rel}: missing decision-brief protocol markers: {missing}"

    assert (
        "execution/receipt flows are not currently available from the SDK" in text
    ), (
        f"{rel}: the retired guidance CLI's missing lifecycle must stay an "
        "explicit limitation, not an invented command"
    )


def test_dataset_example_insights_snippet_uses_async_sdk_contract(
    repo_root: Path,
) -> None:
    path = repo_root / "skills" / "traigent-dataset-curate" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(repo_root).as_posix()

    assert "async with ExampleInsightsClient(" in text, (
        f"{rel}: ExampleInsightsClient snippet must use the async context manager"
    )
    assert "job = await client.compute_scores(experiment_run_id=run_id)" in text, (
        f"{rel}: compute_scores must be awaited with the SDK parameter name"
    )
    assert "status = await client.get_job_status(job_id=job[\"job_id\"])" in text, (
        f"{rel}: get_job_status must be awaited with the SDK parameter name"
    )
    assert re.search(
        r"scores = await client\.get_example_scores\(\s*"
        r"experiment_run_id=run_id,\s*"
        r"example_ids=\[\"ex_001\", \"ex_002\"\],\s*\)",
        text,
    ), f"{rel}: get_example_scores must be awaited with the SDK parameter names"
    assert "quality = await client.get_dataset_quality(experiment_run_id=run_id)" in text, (
        f"{rel}: get_dataset_quality must be awaited with the SDK parameter name"
    )
    assert not re.search(r"(?m)^\s*job = client\.compute_scores\(", text), (
        f"{rel}: do not teach the old sync compute_scores call"
    )
    assert "client.close()" not in text, (
        f"{rel}: async context manager should close ExampleInsightsClient"
    )


def test_optimize_lints_have_teeth(tmp_path: Path) -> None:
    """Self-test: the lints must flag known-bad teaching and pass known-good."""
    bad = tmp_path / "skills" / "bad" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "```python\n"
        "import traigent\n"
        "from traigent.api.decorators import ExecutionOptions\n"
        "@traigent.optimize(configuration_space={'model': ['gpt-4o-mini']}, validate_providers=False,\n"
        '    execution=ExecutionOptions(runtime="node", reps_per_trial=5))\n'
        "def f(x):\n"
        "    return x\n"
        'results = f.optimize(dataset="d.jsonl")\n'
        "def score(prediction, expected):\n"
        "    return 1.0\n"
        "```\n",
        encoding="utf-8",
    )
    assert _scan_dataset_kwarg("bad", bad, bad.read_text(), tmp_path), (
        "dataset= lint missed a violation"
    )
    assert _scan_unawaited_optimize("bad", bad, bad.read_text(), tmp_path), (
        "await lint missed a violation"
    )
    assert _scan_reps_per_trial("bad", bad, bad.read_text(), tmp_path), (
        "reps_per_trial lint missed a violation"
    )
    assert _scan_validate_providers("bad", bad, bad.read_text(), tmp_path), (
        "validate_providers lint missed a violation"
    )
    assert _scan_scoring_first_param("bad", bad, bad.read_text(), tmp_path), (
        "scoring first-param lint missed a violation"
    )
    if _EXECUTION_OPTIONS_FIELDS is not None:
        assert _scan_executionoptions_kwargs("bad", bad, bad.read_text(), tmp_path), (
            "ExecutionOptions lint missed runtime="
        )

    good = tmp_path / "skills" / "good" / "SKILL.md"
    good.parent.mkdir(parents=True)
    good.write_text(
        "```python\n"
        "import traigent\n"
        "from traigent.api.decorators import ExecutionOptions\n"
        '@traigent.optimize(eval_dataset="d.jsonl",\n'
        "    execution=ExecutionOptions(reps_per_trial=1))\n"
        "def f(x):\n"
        "    return x\n"
        "results = f.optimize_sync()\n"
        "def score(output, expected):\n"
        "    return 1.0\n"
        "```\n",
        encoding="utf-8",
    )
    assert not _scan_dataset_kwarg("good", good, good.read_text(), tmp_path), (
        "dataset= lint false-positive"
    )
    assert not _scan_unawaited_optimize("good", good, good.read_text(), tmp_path), (
        "await lint false-positive"
    )
    assert not _scan_reps_per_trial("good", good, good.read_text(), tmp_path), (
        "reps_per_trial false-positive"
    )
    assert not _scan_validate_providers("good", good, good.read_text(), tmp_path), (
        "validate_providers false-positive"
    )
    assert not _scan_executionoptions_kwargs(
        "good", good, good.read_text(), tmp_path
    ), "ExecutionOptions false-positive"
    assert not _scan_scoring_first_param("good", good, good.read_text(), tmp_path), (
        "scoring first-param false-positive"
    )


def test_install_contract_lints_have_teeth(tmp_path: Path) -> None:
    bad = tmp_path / "skills" / "bad" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "```bash\n"
        "pip install 'traigent[integrations]'\n"
        "```\n",
        encoding="utf-8",
    )
    assert _scan_unfloored_pip_installs("bad", bad, bad.read_text(), tmp_path), (
        "unfloored pip install lint missed a violation"
    )

    skipped = tmp_path / "skills" / "skipped" / "SKILL.md"
    skipped.parent.mkdir(parents=True)
    skipped.write_text(
        "```bash\n"
        "# contract: skip\n"
        "pip install traigent\n"
        "```\n",
        encoding="utf-8",
    )
    assert not _scan_unfloored_pip_installs(
        "skipped", skipped, skipped.read_text(), tmp_path
    ), "unfloored pip install lint ignored # contract: skip"

    good = tmp_path / "skills" / "good_install" / "SKILL.md"
    good.parent.mkdir(parents=True)
    good.write_text(
        "```bash\n"
        "pip install 'traigent[recommended]>=0.19'\n"
        "python -m pip install --upgrade \"traigent>=0.19\"\n"
        "```\n",
        encoding="utf-8",
    )
    assert not _scan_unfloored_pip_installs(
        "good_install", good, good.read_text(), tmp_path
    ), "unfloored pip install lint false-positive"


def test_lifecycle_vocab_lint_has_teeth(tmp_path: Path) -> None:
    bad = tmp_path / "skills" / "bad" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "Fetch artifact_states and show per-artifact state vocabulary.\n"
        "Dataset state labels: empty/populated/scored/trusted.\n"
        "Then run score_examples.\n",
        encoding="utf-8",
    )
    bad_violations = _scan_lifecycle_vocab_leaks("bad", bad, bad.read_text(), tmp_path)
    assert bad_violations, "lifecycle vocabulary lint missed known leaks"

    good = tmp_path / "skills" / "good" / "SKILL.md"
    good.parent.mkdir(parents=True)
    good.write_text(
        "Present posture.summary_text and next_steps[].action.command_template.\n"
        "Allowed next step labels include expand_dataset, refine_metric, "
        "adjust_config_space, rerun_larger_sample, add_safety_gate, "
        "compare_with_baseline, and promote_winner.\n"
        "Use an empty string only in this generic example, without lifecycle context.\n",
        encoding="utf-8",
    )
    assert not _scan_lifecycle_vocab_leaks("good", good, good.read_text(), tmp_path), (
        "lifecycle vocabulary lint false-positive on allowed next-step labels"
    )


def test_evaluationoptions_and_injectionoptions_kwargs_lints_have_teeth(
    tmp_path: Path,
) -> None:
    """Fenced-python twins of test_executionoptions_kwargs_are_real_fields (#274)."""
    bad = tmp_path / "skills" / "bad" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "```python\n"
        "import traigent\n"
        "from traigent.api.decorators import EvaluationOptions, InjectionOptions\n"
        "@traigent.optimize(\n"
        '    evaluation=EvaluationOptions(eval_dataset="d.jsonl", task_type="exact_match"),\n'
        '    injection=InjectionOptions(injection_mode="context", tags=["x"]),\n'
        ")\n"
        "def f(x):\n"
        "    return x\n"
        "```\n",
        encoding="utf-8",
    )
    if _EVALUATION_OPTIONS_FIELDS is not None:
        assert _scan_evaluationoptions_kwargs("bad", bad, bad.read_text(), tmp_path), (
            "EvaluationOptions lint missed task_type="
        )
    if _INJECTION_OPTIONS_FIELDS is not None:
        assert _scan_injectionoptions_kwargs("bad", bad, bad.read_text(), tmp_path), (
            "InjectionOptions lint missed tags="
        )

    good = tmp_path / "skills" / "good" / "SKILL.md"
    good.parent.mkdir(parents=True)
    good.write_text(
        "```python\n"
        "import traigent\n"
        "from traigent.api.decorators import EvaluationOptions, InjectionOptions\n"
        "@traigent.optimize(\n"
        '    evaluation=EvaluationOptions(eval_dataset="d.jsonl"),\n'
        '    injection=InjectionOptions(injection_mode="context"),\n'
        ")\n"
        "def f(x):\n"
        "    return x\n"
        "```\n",
        encoding="utf-8",
    )
    assert not _scan_evaluationoptions_kwargs("good", good, good.read_text(), tmp_path), (
        "EvaluationOptions lint false-positive"
    )
    assert not _scan_injectionoptions_kwargs("good", good, good.read_text(), tmp_path), (
        "InjectionOptions lint false-positive"
    )


def test_option_prose_kwargs_lint_has_teeth(tmp_path: Path) -> None:
    """The actual #274 gap: a bad kwarg taught in prose, not fenced code."""
    bad = tmp_path / "skills" / "bad" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "## Anchoring\n\n"
        "Pass `evaluation=EvaluationOptions(task_type=\"exact_match\")` on the "
        "decorated function to anchor the audit.\n",
        encoding="utf-8",
    )
    if _EVALUATION_OPTIONS_FIELDS is not None:
        violations = _scan_option_prose_kwargs("bad", bad, bad.read_text(), tmp_path)
        assert violations, "prose kwarg lint missed task_type= taught as runnable"
        assert "task_type" in violations[0] and ":3" in violations[0]

    # Same bad kwarg, but documented as failing -- must NOT be flagged (this is
    # exactly what traigent-eval-audit/SKILL.md and traigent-setup-decorator/SKILL.md
    # do today after #274, and it must stay green).
    hedged = tmp_path / "skills" / "hedged" / "SKILL.md"
    hedged.parent.mkdir(parents=True)
    hedged.write_text(
        "## Anchoring\n\n"
        "`EvaluationOptions` forbids unknown fields, so "
        "`EvaluationOptions(task_type=\"exact_match\")` raises "
        "`ValidationError: Extra inputs are not permitted` -- do not pass it.\n",
        encoding="utf-8",
    )
    assert not _scan_option_prose_kwargs(
        "hedged", hedged, hedged.read_text(), tmp_path
    ), "prose kwarg lint false-positive on a documented-as-failing example"

    good = tmp_path / "skills" / "good" / "SKILL.md"
    good.parent.mkdir(parents=True)
    good.write_text(
        "## Anchoring\n\n"
        "Pass `evaluation=EvaluationOptions(eval_dataset=\"d.jsonl\")` on the "
        "decorated function.\n",
        encoding="utf-8",
    )
    assert not _scan_option_prose_kwargs("good", good, good.read_text(), tmp_path), (
        "prose kwarg lint false-positive on a real field"
    )


def test_option_field_table_lint_has_teeth(tmp_path: Path) -> None:
    """The other #274 gap: a bad field taught as a row in a Fields reference
    table. Scoped to a section that names the class; unrelated tables must not
    be flagged even when their header also says "Field"."""
    bad = tmp_path / "skills" / "bad" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "## Evaluation Setup\n\n"
        "Configure how Traigent evaluates each trial using `EvaluationOptions`.\n\n"
        "### Fields\n\n"
        "| Field | Type | Description |\n"
        "|---|---|---|\n"
        "| `eval_dataset` | `str` | Path to a JSONL dataset |\n"
        '| `task_type` | `str` | Coarse task category |\n',
        encoding="utf-8",
    )
    if _EVALUATION_OPTIONS_FIELDS is not None:
        violations = _scan_option_field_tables("bad", bad, bad.read_text(), tmp_path)
        assert violations, "field-table lint missed a task_type row"
        assert "task_type" in violations[0]

    good = tmp_path / "skills" / "good" / "SKILL.md"
    good.parent.mkdir(parents=True)
    good.write_text(
        "## Evaluation Setup\n\n"
        "Configure how Traigent evaluates each trial using `EvaluationOptions`.\n\n"
        "### Fields\n\n"
        "| Field | Type | Description |\n"
        "|---|---|---|\n"
        "| `eval_dataset` | `str` | Path to a JSONL dataset |\n"
        "| `scoring_function` | `Callable` | A lightweight scorer |\n",
        encoding="utf-8",
    )
    assert not _scan_option_field_tables("good", good, good.read_text(), tmp_path), (
        "field-table lint false-positive on real fields"
    )

    unrelated = tmp_path / "skills" / "unrelated" / "SKILL.md"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text(
        "## Choosing a Model\n\n"
        "| Field | Recommendation |\n"
        "|---|---|\n"
        "| Cheap tasks | `gpt-4o-mini` |\n",
        encoding="utf-8",
    )
    assert not _scan_option_field_tables(
        "unrelated", unrelated, unrelated.read_text(), tmp_path
    ), "field-table lint false-positive on a table not about any option class"
