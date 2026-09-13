#!/usr/bin/env python3
"""Tier 1 local audit of an LLM agent project: static inspection plus one
sandboxed probe of the user's own deterministic scorer.

Zero network at runtime, enforced rather than asserted: ``install_network_guard``
replaces the socket entry points with a refusal before any project file is read,
``verify_network_guard`` proves the refusal actually fires, and every subprocess
this module starts installs the same guard as its first statement.

Standard library only, Python 3.11+. This script never imports ``traigent`` and
never reads a Traigent backend; the SDK version is read out of process with
``importlib.metadata``.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = "traigent-setup-audit/v1"
GUARD_MESSAGE = "traigent-setup-audit: network disabled in the free audit"

SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
    }
)

# Dataset row keys, in the order the SDK resolves them
# (traigent/evaluators/base.py `_EXPECTED_OUTPUT_FIELDS` for the gold keys).
INPUT_KEYS = ("input", "input_data", "question", "prompt", "query", "messages")
EXPECTED_KEYS = ("output", "expected", "expected_output", "answer", "target", "label")
HOLDOUT_VALUES = frozenset({"holdout", "test", "validation", "val", "eval"})

# Row-count minimums mirrored from skills/traigent-dataset-curate/SKILL.md.
MIN_SMOKE = 10
MIN_TUNING = 30
MIN_HOLDOUT = 30
MIN_HIGH_VARIANCE = 100

PROVIDER_MODULES = frozenset(
    {
        "openai",
        "anthropic",
        "litellm",
        "google.generativeai",
        "google.genai",
        "cohere",
        "mistralai",
        "groq",
        "ollama",
        "together",
        "replicate",
        "langchain",
        "langchain_openai",
        "llama_index",
    }
)
JUDGE_MODULES = frozenset(
    {
        "openai",
        "anthropic",
        "litellm",
        "google.generativeai",
        "google.genai",
        "cohere",
        "mistralai",
        "groq",
    }
)
EXECUTING_MODULES = frozenset(
    {
        "subprocess",
        "sqlite3",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "duckdb",
        "pymysql",
        "asyncpg",
    }
)
EXECUTING_BUILTINS = frozenset({"exec", "eval", "compile"})
EXECUTING_OS_ATTRS = frozenset({"system", "popen", "execv", "spawnl"})

SCORER_NAME_RE = re.compile(r"(?i)^(score|evaluate|grade|metric)|_(score|scorer)$")
KEY_ENV_NAMES = (
    "TRAIGENT_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "GROQ_API_KEY",
    "COHERE_API_KEY",
)
MODEL_KNOB_NAMES = frozenset({"model", "model_name", "llm", "engine", "model_id"})

PUNCTUATION_RE = re.compile(r"[^\w\s]+")
WHITESPACE_RE = re.compile(r"\s+")

MAX_PYTHON_FILES = 4000
MAX_DATA_FILES = 400
MAX_DATA_BYTES = 25 * 1024 * 1024
MAX_ROWS = 20000
NEAR_DUPLICATE_LIMIT = 5000
NEAR_DUPLICATE_JACCARD = 0.9
PROBE_TIMEOUT_SECONDS = 30
# The JSON report keeps every dataset; the printed card stops here so one tree
# with dozens of eval files stays readable.
MAX_DATASETS_IN_CARD = 10

_VERSION_PROBE_SOURCE = """
import json
import socket


def _refuse(*args, **kwargs):
    raise RuntimeError("traigent-setup-audit: network disabled in the free audit")


socket.socket = _refuse
socket.create_connection = _refuse
socket.getaddrinfo = _refuse
socket.gethostbyname = _refuse

import importlib.metadata as md

try:
    version = md.version("traigent")
except Exception:
    version = None
print(json.dumps({"traigent_version": version}))
"""


# --------------------------------------------------------------------------
# network guard
# --------------------------------------------------------------------------


def install_network_guard() -> None:
    """Replace the socket entry points with a refusal.

    Called as the first statement of ``main`` and of every subprocess this
    module starts, so no project file is read before the refusal is in place.
    """
    import socket

    def _refuse(*args, **kwargs):
        raise RuntimeError(GUARD_MESSAGE)

    socket.socket = _refuse
    socket.create_connection = _refuse
    socket.getaddrinfo = _refuse
    socket.gethostbyname = _refuse


def verify_network_guard() -> str:
    """Return ``active`` only when every guarded entry point actually refuses.

    The audit reports this value instead of claiming zero network in prose.
    """
    import socket

    attempts = (
        lambda: socket.socket(),
        lambda: socket.create_connection(("localhost", 9)),
        lambda: socket.getaddrinfo("localhost", 80),
        lambda: socket.gethostbyname("localhost"),
    )
    for attempt in attempts:
        try:
            attempt()
        except RuntimeError as exc:
            if str(exc) != GUARD_MESSAGE:
                return "uncertain"
        except Exception:
            return "uncertain"
        else:
            return "inactive"
    return "active"


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def normalize_text(value: object) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, sort_keys=True, default=str)
    text = PUNCTUATION_RE.sub(" ", text.lower())
    return WHITESPACE_RE.sub(" ", text).strip()


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def iter_project_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIP_DIRS and not name.startswith(".")
        )
        for name in sorted(filenames):
            found.append(Path(dirpath) / name)
    return found


# --------------------------------------------------------------------------
# knob wiring (ast)
# --------------------------------------------------------------------------


@dataclass
class Knob:
    name: str
    values: list[object]
    status: str
    file: str
    line: int


@dataclass
class EntryPoint:
    function: str
    file: str
    line: int
    knobs: list[Knob] = field(default_factory=list)


def _decorator_is_traigent_optimize(node: ast.expr, optimize_aliases: set[str]) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr == "optimize" and isinstance(target.value, ast.Name)
    if isinstance(target, ast.Name):
        return target.id in optimize_aliases
    return False


def _literal(node: ast.expr) -> object:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def function_read_surface(node: ast.AST) -> tuple[set[str], set[str], bool]:
    """Names the function could read a knob through.

    Returns ``(parameter names, string literals, reads a config mapping)``.

    Only the parameter list and the function BODY are inspected. Walking the
    whole node would include the decorator that declares the configuration
    space, and every declared knob name would then look like a literal the body
    reads — the exact defect this check exists to catch.
    """
    parameters: set[str] = set()
    literals: set[str] = set()
    dynamic = False

    body: list[ast.stmt] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = node.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            parameters.add(arg.arg)
        if args.vararg:
            parameters.add(args.vararg.arg)
        if args.kwarg:
            parameters.add(args.kwarg.arg)
        body = list(node.body)

    for child in (sub for stmt in body for sub in ast.walk(stmt)):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            literals.add(child.value)
        if isinstance(child, ast.Attribute) and child.attr in {
            "get_config",
            "current_config",
        }:
            dynamic = True
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            if child.func.id in {"get_config", "current_config"}:
                dynamic = True
        if isinstance(child, ast.Subscript) and isinstance(child.value, ast.Name):
            if child.value.id in {"config", "cfg", "kwargs", "configuration"}:
                dynamic = True
    return parameters, literals, dynamic


def knob_status(key: str, parameters: set[str], literals: set[str], dynamic: bool) -> str:
    if key in parameters or key in literals:
        return "read"
    if dynamic:
        return "possibly read through a config mapping"
    return "declared, never read"


def collect_entry_points(tree: ast.AST, rel_path: str) -> list[EntryPoint]:
    optimize_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "traigent"
        ):
            for alias in node.names:
                if alias.name == "optimize":
                    optimize_aliases.add(alias.asname or alias.name)

    entry_points: list[EntryPoint] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorator = next(
            (
                dec
                for dec in node.decorator_list
                if _decorator_is_traigent_optimize(dec, optimize_aliases)
            ),
            None,
        )
        if decorator is None:
            continue
        entry = EntryPoint(function=node.name, file=rel_path, line=node.lineno)
        parameters, literals, dynamic = function_read_surface(node)
        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if keyword.arg not in {"configuration_space", "config_space"}:
                    continue
                space = keyword.value
                if not isinstance(space, ast.Dict):
                    continue
                for key_node, value_node in zip(space.keys, space.values):
                    key = _literal(key_node) if key_node is not None else None
                    if not isinstance(key, str):
                        continue
                    values = _literal(value_node)
                    entry.knobs.append(
                        Knob(
                            name=key,
                            values=list(values)
                            if isinstance(values, (list, tuple))
                            else [],
                            status=knob_status(key, parameters, literals, dynamic),
                            file=rel_path,
                            line=getattr(key_node, "lineno", node.lineno),
                        )
                    )
        entry.knobs.sort(key=lambda knob: knob.name)
        entry_points.append(entry)
    entry_points.sort(key=lambda item: (item.file, item.line))
    return entry_points


# --------------------------------------------------------------------------
# python inventory
# --------------------------------------------------------------------------


@dataclass
class ScorerCandidate:
    function: str
    file: str
    line: int
    kind: str
    signals: list[str]
    parameters: list[str]


@dataclass
class PythonInventory:
    files_scanned: int = 0
    files_unparsed: list[str] = field(default_factory=list)
    entry_points: list[EntryPoint] = field(default_factory=list)
    llm_call_sites: list[dict] = field(default_factory=list)
    scorers: list[ScorerCandidate] = field(default_factory=list)


def module_imports(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
                modules.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module:
                modules.add(module)
                modules.add(module.split(".", 1)[0])
    return modules


def classify_scorer(tree: ast.AST, node: ast.AST) -> tuple[str, list[str]]:
    modules = module_imports(tree)
    signals: list[str] = []
    judge = sorted(modules & JUDGE_MODULES)
    executing = sorted(modules & EXECUTING_MODULES)

    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            if child.func.id in EXECUTING_BUILTINS:
                executing.append(f"builtin {child.func.id}")
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            value = child.func.value
            if isinstance(value, ast.Name) and value.id == "os":
                if child.func.attr in EXECUTING_OS_ATTRS:
                    executing.append(f"os.{child.func.attr}")

    if judge:
        signals.append("imports " + ", ".join(judge))
    if executing:
        signals.append("uses " + ", ".join(sorted(set(executing))))

    if judge and executing:
        return "hybrid", signals
    if judge:
        return "llm-judge", signals
    if executing:
        return "executing", signals
    return "deterministic", signals


def scan_python(files: list[Path], root: Path) -> PythonInventory:
    inventory = PythonInventory()
    for path in files[:MAX_PYTHON_FILES]:
        rel = relative(path, root)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            inventory.files_unparsed.append(rel)
            continue
        inventory.files_scanned += 1
        inventory.entry_points.extend(collect_entry_points(tree, rel))

        modules = module_imports(tree)
        providers = sorted(modules & PROVIDER_MODULES)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            parameters = [arg.arg for arg in node.args.args]
            looks_like_scorer = bool(SCORER_NAME_RE.search(node.name)) or (
                len(parameters) >= 2 and parameters[1] == "expected"
            )
            if looks_like_scorer:
                kind, signals = classify_scorer(tree, node)
                inventory.scorers.append(
                    ScorerCandidate(
                        function=node.name,
                        file=rel,
                        line=node.lineno,
                        kind=kind,
                        signals=signals,
                        parameters=parameters,
                    )
                )
            if providers and not node.name.startswith("_"):
                inventory.llm_call_sites.append(
                    {
                        "function": node.name,
                        "file": rel,
                        "line": node.lineno,
                        "providers": providers,
                    }
                )
    inventory.scorers.sort(key=lambda item: (item.file, item.line))
    inventory.llm_call_sites.sort(key=lambda item: (item["file"], item["line"]))
    return inventory


# --------------------------------------------------------------------------
# dataset inventory
# --------------------------------------------------------------------------


@dataclass
class DatasetRow:
    index: int
    input_key: str
    normalized_input: str
    expected_key: str | None
    expected: object
    split: str | None


@dataclass
class DatasetReport:
    file: str
    rows: int
    input_key_counts: dict[str, int]
    expected_key_counts: dict[str, int]
    missing_expected: list[int]
    exact_duplicate_groups: list[list[int]]
    near_duplicate_pairs: list[list[int]]
    split_counts: dict[str, int]
    holdout_rows: int
    holdout_overlap: list[int]
    label_counts: dict[str, int]
    findings: list[str]


def _row_split(row: dict) -> str | None:
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("split")
        if isinstance(value, str):
            return value.strip().lower()
    value = row.get("split")
    if isinstance(value, str):
        return value.strip().lower()
    return None


def load_rows(path: Path) -> list[dict] | None:
    suffix = path.suffix.lower()
    try:
        if path.stat().st_size > MAX_DATA_BYTES:
            return None
    except OSError:
        return None
    try:
        if suffix == ".jsonl":
            rows = []
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    if isinstance(item, dict):
                        rows.append(item)
                    if len(rows) >= MAX_ROWS:
                        break
            return rows
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(payload, list):
                return [item for item in payload[:MAX_ROWS] if isinstance(item, dict)]
            return None
        if suffix == ".csv":
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle)
                return [dict(item) for _, item in zip(range(MAX_ROWS), reader)]
    except (OSError, ValueError, csv.Error):
        return None
    return None


def _tokenize(text: str) -> frozenset[str]:
    return frozenset(text.split())


def near_duplicate_pairs(rows: list[DatasetRow]) -> list[list[int]]:
    """Row-index pairs whose normalized inputs are close but not identical.

    Identical inputs are reported separately as exact duplicates; including them
    here would report the same defect twice.
    """
    if len(rows) > NEAR_DUPLICATE_LIMIT:
        return []
    token_sets = {row.index: _tokenize(row.normalized_input) for row in rows}
    text_by_index = {row.index: row.normalized_input for row in rows}
    index: dict[str, list[int]] = defaultdict(list)
    for row_index, tokens in token_sets.items():
        for token in tokens:
            index[token].append(row_index)
    common_cutoff = max(50, int(0.2 * len(rows)))
    candidates: set[tuple[int, int]] = set()
    for members in index.values():
        if len(members) > common_cutoff:
            continue
        for position, left in enumerate(members):
            for right in members[position + 1 :]:
                candidates.add((left, right) if left < right else (right, left))
    pairs: list[list[int]] = []
    for left, right in sorted(candidates):
        if text_by_index[left] == text_by_index[right]:
            continue
        left_tokens = token_sets[left]
        right_tokens = token_sets[right]
        union = left_tokens | right_tokens
        if not union:
            continue
        overlap = len(left_tokens & right_tokens) / len(union)
        if overlap >= NEAR_DUPLICATE_JACCARD:
            pairs.append([left, right])
    return pairs


def analyse_dataset(path: Path, root: Path, rows: list[dict]) -> DatasetReport:
    parsed: list[DatasetRow] = []
    input_key_counts: Counter[str] = Counter()
    expected_key_counts: Counter[str] = Counter()
    missing_expected: list[int] = []

    for position, row in enumerate(rows):
        input_key = next((key for key in INPUT_KEYS if key in row), None)
        if input_key is None:
            continue
        input_key_counts[input_key] += 1
        expected_key = next((key for key in EXPECTED_KEYS if key in row), None)
        if expected_key is None:
            missing_expected.append(position)
        else:
            expected_key_counts[expected_key] += 1
        parsed.append(
            DatasetRow(
                index=position,
                input_key=input_key,
                normalized_input=normalize_text(row[input_key]),
                expected_key=expected_key,
                expected=row.get(expected_key) if expected_key else None,
                split=_row_split(row),
            )
        )

    by_input: dict[str, list[int]] = defaultdict(list)
    for row in parsed:
        by_input[row.normalized_input].append(row.index)
    exact_groups = sorted(
        (indices for indices in by_input.values() if len(indices) > 1),
        key=lambda group: group[0],
    )

    split_counts = Counter(row.split for row in parsed if row.split)
    holdout_inputs = {
        row.normalized_input for row in parsed if row.split in HOLDOUT_VALUES
    }
    other_inputs = {
        row.normalized_input
        for row in parsed
        if row.split is not None and row.split not in HOLDOUT_VALUES
    }
    overlap_texts = holdout_inputs & other_inputs
    holdout_overlap = sorted(
        row.index for row in parsed if row.normalized_input in overlap_texts
    )

    label_counts: dict[str, int] = {}
    scalar_expected = [
        row.expected
        for row in parsed
        if isinstance(row.expected, (str, int, float, bool))
    ]
    if len(scalar_expected) >= 20:
        counted = Counter(str(value) for value in scalar_expected)
        if len(counted) <= 10:
            label_counts = dict(sorted(counted.items()))

    findings: list[str] = []
    count = len(parsed)
    if count < MIN_SMOKE:
        findings.append(
            f"{count} rows is under the {MIN_SMOKE}-row smoke minimum"
        )
    elif count < MIN_TUNING:
        findings.append(
            f"{count} rows is under the {MIN_TUNING}-row first-tuning-slice minimum"
        )
    if missing_expected:
        findings.append(
            f"{len(missing_expected)} row(s) carry no gold key "
            f"({'/'.join(EXPECTED_KEYS)})"
        )
    if exact_groups:
        findings.append(
            f"{len(exact_groups)} group(s) of rows share a normalized input"
        )
    near_pairs = near_duplicate_pairs(parsed)
    if near_pairs:
        findings.append(f"{len(near_pairs)} near-duplicate input pair(s)")
    holdout_rows = sum(
        value for key, value in split_counts.items() if key in HOLDOUT_VALUES
    )
    if not split_counts:
        findings.append("no split marker on any row, so no holdout slice is declared")
    elif holdout_rows == 0:
        findings.append(
            "split markers present but none name a holdout slice "
            f"({'/'.join(sorted(HOLDOUT_VALUES))})"
        )
    elif holdout_rows < MIN_HOLDOUT:
        findings.append(
            f"holdout slice has {holdout_rows} rows, under the {MIN_HOLDOUT}-row minimum"
        )
    if holdout_overlap:
        findings.append(
            f"{len(holdout_overlap)} row(s) appear in both the holdout slice and another slice"
        )
    if label_counts:
        largest = max(label_counts.values())
        if largest >= 0.8 * sum(label_counts.values()):
            findings.append(
                f"one label covers {largest} of {sum(label_counts.values())} labelled rows"
            )

    return DatasetReport(
        file=relative(path, root),
        rows=count,
        input_key_counts=dict(sorted(input_key_counts.items())),
        expected_key_counts=dict(sorted(expected_key_counts.items())),
        missing_expected=missing_expected[:20],
        exact_duplicate_groups=[group[:5] for group in exact_groups[:20]],
        near_duplicate_pairs=near_pairs[:20],
        split_counts=dict(sorted(split_counts.items())),
        holdout_rows=holdout_rows,
        holdout_overlap=holdout_overlap[:20],
        label_counts=label_counts,
        findings=findings,
    )


def scan_datasets(files: list[Path], root: Path) -> tuple[list[DatasetReport], int]:
    candidates = [
        path for path in files if path.suffix.lower() in {".jsonl", ".json", ".csv"}
    ]
    reports: list[DatasetReport] = []
    for path in candidates[:MAX_DATA_FILES]:
        rows = load_rows(path)
        if not rows:
            continue
        with_input = sum(
            1 for row in rows if any(key in row for key in INPUT_KEYS)
        )
        if with_input == 0 or with_input < 0.5 * len(rows):
            continue
        reports.append(analyse_dataset(path, root, rows))
    reports.sort(key=lambda report: report.file)
    return reports, len(candidates)


# --------------------------------------------------------------------------
# scorer probe
# --------------------------------------------------------------------------


def build_probe_payload(datasets: list[DatasetReport], root: Path):
    """Return ``(good, partial, bad, source)`` probe values.

    Prefers two real expected outputs from the largest dataset; falls back to
    synthetic strings when the project has no gold values to work from.
    """
    for report in sorted(datasets, key=lambda item: -item.rows):
        rows = load_rows(root / report.file)
        if not rows:
            continue
        values: list[str] = []
        for row in rows:
            key = next((name for name in EXPECTED_KEYS if name in row), None)
            if key is None:
                continue
            value = row[key]
            if isinstance(value, str) and value.strip():
                if value not in values:
                    values.append(value)
            if len(values) >= 2:
                break
        if len(values) >= 2:
            return values[0], perturb(values[0]), values[1], "dataset"
    return (
        "traigent setup audit probe value",
        "traigent setup audit probe",
        "an unrelated answer",
        "synthetic",
    )


def perturb(text: str) -> str:
    tokens = text.split()
    if len(tokens) > 1:
        return " ".join(tokens[:-1])
    lowered = text.lower()
    if lowered != text:
        return lowered
    return text[:-1] if len(text) > 1 else text + "?"


def run_scorer_probe(
    interpreter: str,
    scorer: ScorerCandidate,
    root: Path,
    payload: tuple[str, str, str, str],
    repeats: int,
) -> dict:
    probe_script = Path(__file__).resolve().parent / "scorer_probe.py"
    good, partial, bad, source = payload
    request = {
        "module": str((root / scorer.file).resolve()),
        "function": scorer.function,
        "good": good,
        "partial": partial,
        "bad": bad,
        "repeats": repeats,
    }
    command = [interpreter, str(probe_script), "--request-stdin"]
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ran": False,
            "reason": f"the probe did not finish within {PROBE_TIMEOUT_SECONDS} seconds",
            "payload_source": source,
        }
    except OSError as exc:
        return {"ran": False, "reason": str(exc), "payload_source": source}

    try:
        result = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {
            "ran": False,
            "reason": "the probe produced no readable result",
            "stderr_tail": completed.stderr.strip()[-400:],
            "payload_source": source,
        }
    result["payload_source"] = source
    return result


def _show(scores: list[float]) -> str:
    """One probe score, rounded for reading. The JSON keeps the full value."""
    if not scores:
        return "n/a"
    return f"{scores[0]:.4g}"


def summarize_probe(result: dict) -> tuple[str, list[str]]:
    if result.get("network_blocked"):
        return "blocked", [
            "the scorer tried to open a network connection and the audit's "
            "network guard refused it, so no score was produced",
        ]
    if not result.get("ran"):
        return "not-run", [str(result.get("reason", "the probe did not run"))]

    evidence: list[str] = []
    scores = result.get("scores") or {}
    good = scores.get("good") or []
    partial = scores.get("partial") or []
    bad = scores.get("bad") or []
    stable = bool(good) and len(set(good)) == 1
    evidence.append(
        f"repeat-scoring the same pair {len(good)} times returned "
        + ("one identical score" if stable else f"{len(set(good))} different scores")
    )
    ordered = bool(good and bad) and good[0] > bad[0]
    if partial:
        ordered = ordered and good[0] >= partial[0] >= bad[0]
    evidence.append(
        "known-good / partial / known-bad probes scored "
        f"{_show(good)} / {_show(partial)} / {_show(bad)}"
        + (" (ordered as expected)" if ordered else " (not ordered as expected)")
    )
    if result.get("errors"):
        evidence.append(f"{len(result['errors'])} probe call(s) raised an exception")
    status = "ok" if stable and ordered and not result.get("errors") else "attention"
    return status, evidence


# --------------------------------------------------------------------------
# setup checks
# --------------------------------------------------------------------------


def project_interpreter(root: Path) -> str:
    candidate = root / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def read_sdk_version(interpreter: str) -> dict:
    command = [interpreter, "-c", _VERSION_PROBE_SOURCE]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"interpreter": interpreter, "traigent_version": None, "error": str(exc)}
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {
            "interpreter": interpreter,
            "traigent_version": None,
            "error": "the version probe produced no readable result",
        }
    return {"interpreter": interpreter, "traigent_version": payload["traigent_version"]}


def key_presence(root: Path, files: list[Path]) -> dict:
    """Report only whether a key name is set. No value is read, printed or stored."""
    env_files = sorted(
        path
        for path in files
        if path.name == ".env" or path.name.startswith(".env.")
    )
    in_environment = sorted(name for name in KEY_ENV_NAMES if name in os.environ)
    in_files: dict[str, list[str]] = {}
    for path in env_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        names = []
        for name in KEY_ENV_NAMES:
            if re.search(rf"(?m)^\s*(export\s+)?{re.escape(name)}\s*=", text):
                names.append(name)
        if names:
            in_files[relative(path, root)] = names
    return {
        "env_files": [relative(path, root) for path in env_files],
        "names_set_in_environment": in_environment,
        "names_declared_in_env_files": in_files,
    }


def env_file_ignored(root: Path) -> str:
    if not (root / ".env").exists():
        return "no .env file"
    command = ["git", "-C", str(root), "check-ignore", "-q", ".env"]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=15, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"
    if completed.returncode == 0:
        return "ignored"
    if completed.returncode == 1:
        return "not ignored"
    return "unknown"


# --------------------------------------------------------------------------
# report assembly
# --------------------------------------------------------------------------


def agent_area(inventory: PythonInventory) -> dict:
    evidence: list[str] = []
    if inventory.entry_points:
        for entry in inventory.entry_points:
            evidence.append(
                f"`@traigent.optimize` on `{entry.function}` at "
                f"{entry.file}:{entry.line}, {len(entry.knobs)} declared knob(s)"
            )
        unread = [
            knob
            for entry in inventory.entry_points
            for knob in entry.knobs
            if knob.status == "declared, never read"
        ]
        for knob in unread:
            evidence.append(
                f"knob `{knob.name}` is declared at {knob.file}:{knob.line} and the "
                "decorated function body never reads it"
            )
        no_knobs = [entry for entry in inventory.entry_points if not entry.knobs]
        for entry in no_knobs:
            evidence.append(
                f"`{entry.function}` at {entry.file}:{entry.line} declares no "
                "configuration space, so there is nothing to search"
            )
        status = "attention" if unread or no_knobs else "ok"
        if unread:
            meaning = (
                "A knob the function never reads cannot change the output, so every "
                "trial that varies it is spend with no effect."
            )
        elif no_knobs:
            meaning = (
                "A decorated function with no configuration space gives the "
                "optimizer one point to evaluate, so there is nothing to compare."
            )
        else:
            meaning = (
                "Every declared knob reaches the function body, so a search over "
                "them can change the output."
            )
    else:
        evidence.append(
            f"searched for `@traigent.optimize` in {inventory.files_scanned} "
            "Python file(s), found none"
        )
        if inventory.llm_call_sites:
            for site in inventory.llm_call_sites[:5]:
                evidence.append(
                    f"`{site['function']}` at {site['file']}:{site['line']} sits in a "
                    f"module importing {', '.join(site['providers'])}"
                )
        else:
            evidence.append(
                f"searched for provider imports ({', '.join(sorted(PROVIDER_MODULES)[:6])}, "
                f"and others) in {inventory.files_scanned} Python file(s), found none"
            )
        status = "not-found"
        meaning = (
            "Nothing is instrumented yet, so there is no search space to optimize; "
            "`traigent-setup-decorator` is where a first decorated function comes from."
        )
    return {"status": status, "evidence": evidence, "meaning": meaning}


def dataset_area(reports: list[DatasetReport], candidates: int) -> dict:
    if not reports:
        return {
            "status": "not-found",
            "evidence": [
                f"searched {candidates} JSONL/JSON/CSV file(s) for rows carrying an "
                f"input-like key ({'/'.join(INPUT_KEYS)}), found none"
            ],
            "meaning": (
                "With no examples there is nothing to score a configuration against; "
                "`traigent-dataset-curate` covers building a first slice."
            ),
        }
    evidence: list[str] = []
    shown = reports[:MAX_DATASETS_IN_CARD]
    for report in shown:
        evidence.append(
            f"{report.file}: {report.rows} row(s), "
            f"gold key(s) {', '.join(report.expected_key_counts) or 'none'}, "
            f"split marker(s) {', '.join(f'{k}={v}' for k, v in report.split_counts.items()) or 'none'}"
        )
        for finding in report.findings:
            evidence.append(f"{report.file}: {finding}")
        if report.missing_expected:
            evidence.append(
                f"{report.file}: first row indexes with no gold key: "
                f"{report.missing_expected[:5]}"
            )
        if report.exact_duplicate_groups:
            evidence.append(
                f"{report.file}: first duplicate row-index group: "
                f"{report.exact_duplicate_groups[0]}"
            )
        if report.near_duplicate_pairs:
            evidence.append(
                f"{report.file}: first near-duplicate row-index pair: "
                f"{report.near_duplicate_pairs[0]}"
            )
    if len(reports) > len(shown):
        evidence.append(
            f"{len(reports) - len(shown)} further dataset file(s) are in the JSON "
            "report and not printed here"
        )
    status = "attention" if any(report.findings for report in reports) else "ok"
    meaning = (
        "Row shortfalls, duplicates and a missing holdout slice all widen the "
        "error bars on a measured score, so a small movement between "
        "configurations may be sampling, not improvement."
        if status == "attention"
        else "Row counts, gold coverage and a disjoint holdout slice are all within "
        "the documented minimums, so a measured movement has something to rest on."
    )
    return {"status": status, "evidence": evidence, "meaning": meaning}


def scorer_area(
    inventory: PythonInventory, probe: dict | None, probed: ScorerCandidate | None
) -> dict:
    if not inventory.scorers:
        return {
            "status": "not-found",
            "evidence": [
                "searched for functions named score*/evaluate*/grade*/metric* or "
                f"taking `expected` as a second parameter in "
                f"{inventory.files_scanned} Python file(s), found none"
            ],
            "meaning": (
                "Without a scorer there is no objective, so no configuration can be "
                "ranked; `traigent-eval-build` covers wiring one."
            ),
        }
    evidence = [
        f"`{candidate.function}` at {candidate.file}:{candidate.line} "
        f"classified {candidate.kind}"
        + (f" ({'; '.join(candidate.signals)})" if candidate.signals else "")
        for candidate in inventory.scorers
    ]
    not_probed = [c for c in inventory.scorers if c.kind != "deterministic"]
    for candidate in not_probed:
        evidence.append(
            f"`{candidate.function}` was not run: a {candidate.kind} scorer either "
            "calls a provider or executes code, and this audit does neither — "
            "`traigent-eval-audit` is the skill that assesses one"
        )
    if probe is None or probed is None:
        status = "attention"
        evidence.append(
            "no deterministic scorer was probed; pass `--scorer FILE.py:FUNCTION` "
            "to choose one"
        )
        meaning = (
            "An unprobed scorer's repeatability is unmeasured, so a score movement "
            "cannot yet be separated from scorer variation."
        )
        return {"status": status, "evidence": evidence, "meaning": meaning}

    probe_status, probe_evidence = summarize_probe(probe)
    evidence.append(
        f"probed `{probed.function}` at {probed.file}:{probed.line} in a separate "
        f"process with the network guard installed ({probe.get('payload_source')} probe values)"
    )
    evidence.extend(probe_evidence)
    status = "ok" if probe_status == "ok" else "attention"
    if probe_status == "blocked":
        meaning = (
            "A scorer that reaches the network is not a local deterministic scorer; "
            "its score depends on a service this audit will not call."
        )
    elif probe_status == "ok":
        meaning = (
            "The scorer returns the same number for the same pair and separates a "
            "known-good answer from a known-bad one, so a score movement is at "
            "least not scorer variation."
        )
    else:
        meaning = (
            "A scorer that returns different numbers for the same pair makes a "
            "configuration comparison unreliable: the movement you measure may be "
            "the scorer moving."
        )
    return {"status": status, "evidence": evidence, "meaning": meaning}


def setup_area(sdk: dict, keys: dict, ignored: str, model_ids: list[str]) -> dict:
    evidence: list[str] = []
    version = sdk.get("traigent_version")
    if version:
        evidence.append(
            f"traigent {version} is importable by {sdk['interpreter']}"
        )
    else:
        evidence.append(
            f"traigent is not installed for {sdk['interpreter']}"
            + (f" ({sdk['error']})" if sdk.get("error") else "")
        )
    if keys["names_set_in_environment"]:
        evidence.append(
            "set in this environment: "
            + ", ".join(keys["names_set_in_environment"])
            + " (name only; the audit reads no value)"
        )
    else:
        evidence.append(
            f"searched the environment for {len(KEY_ENV_NAMES)} known key names, "
            "found none set"
        )
    for env_file, names in sorted(keys["names_declared_in_env_files"].items()):
        evidence.append(f"{env_file} declares {', '.join(names)} (name only)")
    evidence.append(f".env git status: {ignored}")
    if model_ids:
        evidence.append(
            "model ids in the configuration space: "
            + ", ".join(model_ids)
            + " — not validated here, because validating an id is a provider call"
        )
    problems = (
        not version
        or ignored == "not ignored"
        or not (
            keys["names_set_in_environment"] or keys["names_declared_in_env_files"]
        )
    )
    return {
        "status": "attention" if problems else "ok",
        "evidence": evidence,
        "meaning": (
            "A missing SDK, a missing key or a tracked `.env` each stop the first "
            "real run before it starts."
            if problems
            else "The SDK, a key name and `.env` handling are all in place for a "
            "first run."
        ),
    }


def open_questions(areas: dict, datasets: list[DatasetReport]) -> list[str]:
    questions: list[str] = []
    if areas["scorer"]["status"] != "not-found":
        questions.append(
            "Whether the scorer agrees with a human on real model output. Repeat "
            "scoring measures repeatability, not correctness. Traigent's evaluator "
            "quality service settles this from a completed run; `traigent-eval-audit` "
            "is the skill that asks for it."
        )
    if datasets:
        questions.append(
            "Which individual rows are mislabelled, redundant or too hard. That "
            "needs per-example scores from a completed run, which Traigent's example "
            "scoring and dataset quality services produce; `traigent-dataset-curate` "
            "is the skill that asks for them."
        )
    questions.append(
        "Whether tuning moves the score at all, and which knob moves it. Only a "
        "real run answers that; `traigent-optimize-run` starts one and "
        "`traigent-analyze-variable-importance` ranks the knobs afterwards."
    )
    questions.append(
        "What to do next given your own numbers. Traigent's planning service "
        "returns that before a run and its decision brief after one; "
        "`traigent-analyze-guidance` is the skill that fetches both."
    )
    return questions


NOT_ESTABLISHED = (
    "Repeat-scoring measures repeatability, not correctness. A scorer that returns "
    "the same wrong number every time passes this probe.",
    "No lift is promised. This audit says nothing about whether optimization will "
    "improve your agent, and a flat or negative result is a real outcome.",
    "Knob wiring is detected statically. A knob read through a mapping the audit "
    "cannot follow is reported as possibly read, not as unread.",
    "Model ids are collected, not validated. Checking an id against a provider is a "
    "network call, which Tier 1 does not make.",
    "Only Python is inventoried in this version. A JavaScript or TypeScript project "
    "is not searched for entry points or scorers.",
)


def build_report(root: Path, args: argparse.Namespace, guard: str) -> dict:
    files = iter_project_files(root)
    python_files = [path for path in files if path.suffix == ".py"]
    inventory = scan_python(python_files, root)

    if args.dataset:
        dataset_paths = [Path(args.dataset)]
        reports = []
        for path in dataset_paths:
            rows = load_rows(path)
            if rows:
                reports.append(analyse_dataset(path, root, rows))
        dataset_candidates = len(dataset_paths)
    else:
        reports, dataset_candidates = scan_datasets(files, root)

    probed: ScorerCandidate | None = None
    if args.scorer:
        file_part, _, function_part = args.scorer.rpartition(":")
        if not file_part or not function_part:
            raise ValueError("--scorer must be given as FILE.py:FUNCTION")
        chosen_file = relative(Path(file_part), root)
        probed = next(
            (
                candidate
                for candidate in inventory.scorers
                if candidate.file == chosen_file
                and candidate.function == function_part
            ),
            None,
        ) or ScorerCandidate(
            function=function_part,
            file=chosen_file,
            line=0,
            kind="deterministic",
            signals=["selected with --scorer"],
            parameters=[],
        )
    else:
        deterministic = [c for c in inventory.scorers if c.kind == "deterministic"]
        if len(deterministic) == 1:
            probed = deterministic[0]

    interpreter = project_interpreter(root)
    probe: dict | None = None
    if probed is not None:
        payload = build_probe_payload(reports, root)
        probe = run_scorer_probe(interpreter, probed, root, payload, args.repeats)

    model_ids: list[str] = []
    for entry in inventory.entry_points:
        for knob in entry.knobs:
            if knob.name in MODEL_KNOB_NAMES:
                model_ids.extend(str(value) for value in knob.values)
    model_ids = sorted(set(model_ids))

    sdk = read_sdk_version(interpreter)
    keys = key_presence(root, files)
    ignored = env_file_ignored(root)

    areas = {
        "agent": agent_area(inventory),
        "dataset": dataset_area(reports, dataset_candidates),
        "scorer": scorer_area(inventory, probe, probed),
        "setup": setup_area(sdk, keys, ignored, model_ids),
    }

    return {
        "schema": SCHEMA,
        "network_guard": guard,
        "root": str(root.resolve()),
        "files": {
            "python_parsed": inventory.files_scanned,
            "python_unparsed": inventory.files_unparsed[:20],
            "dataset_candidates": dataset_candidates,
        },
        "areas": areas,
        "entry_points": [
            {
                "function": entry.function,
                "file": entry.file,
                "line": entry.line,
                "knobs": [
                    {
                        "name": knob.name,
                        "values": knob.values,
                        "status": knob.status,
                        "file": knob.file,
                        "line": knob.line,
                    }
                    for knob in entry.knobs
                ],
            }
            for entry in inventory.entry_points
        ],
        "llm_call_sites": inventory.llm_call_sites[:20],
        "dataset_minimums": {
            "smoke_check": MIN_SMOKE,
            "first_tuning_slice": MIN_TUNING,
            "holdout_slice": MIN_HOLDOUT,
            "high_variance_task": MIN_HIGH_VARIANCE,
            "source": "skills/traigent-dataset-curate/SKILL.md",
        },
        "datasets": [
            {
                "file": report.file,
                "rows": report.rows,
                "input_keys": report.input_key_counts,
                "gold_keys": report.expected_key_counts,
                "missing_gold_rows": report.missing_expected,
                "duplicate_groups": report.exact_duplicate_groups,
                "near_duplicate_pairs": report.near_duplicate_pairs,
                "splits": report.split_counts,
                "holdout_rows": report.holdout_rows,
                "holdout_overlap_rows": report.holdout_overlap,
                "label_counts": report.label_counts,
                "findings": report.findings,
            }
            for report in reports
        ],
        "scorers": [
            {
                "function": candidate.function,
                "file": candidate.file,
                "line": candidate.line,
                "kind": candidate.kind,
                "signals": candidate.signals,
            }
            for candidate in inventory.scorers
        ],
        "scorer_probe": probe,
        "setup": {
            "sdk": sdk,
            "keys": keys,
            "env_file_git_status": ignored,
            "model_ids_declared": model_ids,
        },
        "open_questions": open_questions(areas, reports),
        "not_established": list(NOT_ESTABLISHED),
    }


def render_card(report: dict) -> str:
    lines: list[str] = []
    root_name = Path(report["root"]).name or report["root"]
    lines.append(f"# Traigent setup audit — {root_name}")
    lines.append("")
    lines.append(
        f"Local audit, no network. `network_guard: {report['network_guard']}` — the "
        "audit process and every subprocess it starts replace the socket entry "
        "points with a refusal before reading a project file, and the guard is "
        "re-checked at start rather than assumed."
    )
    lines.append("")
    lines.append(
        f"Scanned {report['files']['python_parsed']} Python file(s) and "
        f"{report['files']['dataset_candidates']} JSONL/JSON/CSV file(s) under "
        f"`{report['root']}`."
    )
    lines.append("")

    titles = {
        "agent": "Agent",
        "dataset": "Dataset",
        "scorer": "Scorer",
        "setup": "Setup",
    }
    for key, title in titles.items():
        area = report["areas"][key]
        lines.append(f"## {title} — {area['status']}")
        lines.append("")
        for item in area["evidence"]:
            lines.append(f"- {item}")
        lines.append("")
        lines.append(f"What this means for optimization: {area['meaning']}")
        lines.append("")

    lines.append("## What code alone could not tell you")
    lines.append("")
    for question in report["open_questions"]:
        lines.append(f"- {question}")
    lines.append("")
    lines.append(
        "Each of those needs a Traigent service call, which sends data off this "
        "machine and can cost money. None of them runs here: the approval-gated "
        "second tier of this skill is where they will be offered."
    )
    lines.append("")
    lines.append("## What this audit does not establish")
    lines.append("")
    for item in report["not_established"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="audit_project.py",
        description="Free local audit of an LLM agent project. No network.",
    )
    parser.add_argument("--root", required=True, help="project directory to audit")
    parser.add_argument("--json", dest="json_out", help="also write the report as JSON")
    parser.add_argument("--dataset", help="audit this dataset file instead of searching")
    parser.add_argument(
        "--scorer", help="probe this scorer, given as FILE.py:FUNCTION"
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="how many times to repeat the known-good probe (default 5)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    install_network_guard()
    guard = verify_network_guard()

    try:
        args = parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit:
        return 2

    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"audit_project.py: not a directory: {root}", file=sys.stderr)
        return 2
    if args.repeats < 1:
        print("audit_project.py: --repeats must be at least 1", file=sys.stderr)
        return 2

    try:
        report = build_report(root, args, guard)
    except ValueError as exc:
        print(f"audit_project.py: {exc}", file=sys.stderr)
        return 2

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(render_card(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
