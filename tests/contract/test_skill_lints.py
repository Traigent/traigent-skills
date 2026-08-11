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

from .extract import _iter_fenced_blocks

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


def test_planner_v2_sdk_floor_names_a_releasable_final_version(
    repo_root: Path,
) -> None:
    sync_map = yaml.safe_load((repo_root / "sync_map.yml").read_text(encoding="utf-8"))
    floor = sync_map["skills"]["traigent-analyze-guidance"]["min_sdk_version"]
    parsed = Version(str(floor))

    assert parsed == Version("0.21.3")
    assert not parsed.is_devrelease, (
        "a dev floor cannot distinguish an older develop build that lacks "
        "the Planner V2 guidance surface"
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
    # `traigent guidance` / `traigent next-steps` were retired from the SDK CLI on 2026-08-03
    # (Traigent 6aff6ee7 / 9b308539) with no CLI replacement -- confirmed by introspection
    # against SDK 0.26.0 (`traigent.cli.main.cli.commands` lists 26 commands, neither among
    # them; `traigent guidance --help` errors "No such command 'guidance'" even on the last
    # released build that still had `next-steps`). The capability moved to the Python API in
    # `traigent.generation`, so this lint now pins the successor thin-client surface instead of
    # the retired CLI's next-action-decision protocol (Traigent/traigent-skills#254/#255).
    assert "BackendGuidanceProvider" in text, (
        "traigent-analyze-guidance must fetch the guidance plan via BackendGuidanceProvider"
    )
    assert "optimize_with_guidance" in text, (
        "traigent-analyze-guidance must run the guided round via optimize_with_guidance()"
    )
    assert "the plan carries selection only, never executable content" in text, (
        "the guidance plan must stay non-executable (selection only, no shell fragment)"
    )


def test_next_steps_protocol_uses_portable_backend_url_flag(repo_root: Path) -> None:
    path = repo_root / "skills" / "traigent-analyze-guidance" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(repo_root).as_posix()

    # The retired CLI resolved `--backend-url` as flag -> env var -> stored auth-login URL.
    # `BackendGuidanceProvider` has no such flag at all -- it is Python, not a CLI, and simply
    # inherits whatever backend/credentials its `post_json`/`async_post` callable already
    # targets. This lint now guards that the doc says so explicitly instead of teaching a flag
    # that no longer exists.
    assert "There is no `--backend-url` flag any more" in text, (
        f"{rel}: Mode B must say the backend-url flag is gone, not show it on a retired command"
    )
    assert "with no CLI replacement for either" in text, (
        f"{rel}: the retirement of both commands must be stated plainly, not silently dropped"
    )
    assert "`TRAIGENT_BACKEND_URL` must be set" not in text, (
        f"{rel}: next-steps docs must not teach env-var-only setup as mandatory"
    )
    assert "if `TRAIGENT_BACKEND_URL` is not set" not in text, (
        f"{rel}: --backend-url is not just a fallback for unset env vars"
    )
    assert "connection-refused" not in text.lower(), (
        f"{rel}: do not predict the old default failure mode"
    )


def test_next_steps_protocol_validates_authoritative_guidance_decision(
    repo_root: Path,
) -> None:
    path = repo_root / "skills" / "traigent-analyze-guidance" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(repo_root).as_posix()

    # The retired CLI's decision JSON schema (treatment/profile arms, meta.served_variant,
    # certified_session_utility_advantage_no_kpi_guarantee, rules_parity/rules_fallback, etc.)
    # has no successor -- it is gone, not renamed (verified: `traigent.generation.GuidancePlan`
    # carries none of these fields). This lint now pins the REAL GuidancePlan contract the
    # skill must validate instead.
    required = (
        "plan_id",
        "policy_version",
        "plan_token",
        "expires_at",
        "seed_ref",
        "BackendGuidanceError",
        "benchmark_guide",
        "prompt_rewrite",
    )
    missing = [marker for marker in required if marker not in text]
    assert not missing, f"{rel}: missing GuidancePlan contract markers: {missing}"

    assert "no controlled-experiment arm to precommit" in text, (
        f"{rel}: plan_kind is a plain user choice now, not a randomized experiment arm -- say so"
    )
    assert "invent a successor schema for it" in text, (
        f"{rel}: must forbid reconstructing the retired v2 decision schema"
    )


def test_next_steps_protocol_treats_wait_as_non_executable(repo_root: Path) -> None:
    path = repo_root / "skills" / "traigent-analyze-guidance" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(repo_root).as_posix()

    # The retired CLI's `decision.category=wait` was a signal the skill had to interpret and
    # pause on. The successor `GuidanceLoop` has no such signal to interpret at all -- it stops
    # itself once a round adds nothing new. This lint now pins that real, verified behavior.
    required = (
        "The loop stops itself once a round adds no\n"
        "   new candidates or examples (nothing left to search); there is no separate wait signal to\n"
        "   interpret and no way to force another round past that point.",
    )
    missing = [marker for marker in required if marker not in text]
    assert not missing, f"{rel}: missing non-executable wait protocol markers: {missing}"


def test_next_steps_experiment_arm_is_precommitted_before_outcomes(repo_root: Path) -> None:
    path = repo_root / "skills" / "traigent-analyze-guidance" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(repo_root).as_posix()

    # The retired CLI ran a precommitted, randomized rules-vs-policy experiment arm. The
    # successor `plan_kind` (benchmark_guide / prompt_rewrite) is a plain user choice, not a
    # controlled comparison -- there is no arm to precommit any more. This lint now pins the
    # analogous discipline that DOES still apply: choose plan_kind from the diagnosis before
    # running, not by cherry-picking whichever scored higher after the fact.
    required = (
        "no controlled-experiment arm to precommit",
        "choose it from the Mode C\ndiagnosis before running, not by trying both and keeping whichever scored higher after the fact.",
    )
    missing = [marker for marker in required if marker not in text]
    assert not missing, f"{rel}: missing precommitted-choice protocol: {missing}"


def test_planner_v2_stop_and_receipt_protocol_fail_closed(repo_root: Path) -> None:
    path = repo_root / "skills" / "traigent-analyze-guidance" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(repo_root).as_posix()

    # The retired CLI's stop/receipt protocol (decision.category=stop, result_ref,
    # verification_status=pending, ...) has no successor. `BackendGuidanceProvider`'s actual
    # fail-closed behavior -- verified against traigent/generation/backend_provider.py -- is
    # simpler: raise BackendGuidanceError rather than fabricate a plan. This lint now pins that
    # real contract instead of the retired receipt/reopen machinery.
    required = (
        "BackendGuidanceError",
        "fails closed (raises `BackendGuidanceError`) on a\n"
        "   missing or malformed response rather than fabricating a plan.",
        "It is gone, not renamed; do not reconstruct any part",
    )
    missing = [marker for marker in required if marker not in text]
    assert not missing, f"{rel}: missing fail-closed markers: {missing}"


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
