#!/usr/bin/env python3
"""Tier 1 local audit of an LLM agent project: static inspection plus one
sandboxed probe of the user's own deterministic scorer.

The audit process itself opens no socket. The user's scorer is never run in this
process: it runs in a subprocess, and how strongly that subprocess is contained
is measured, not assumed, and reported as ``network_guard``:

``isolated (unshare)`` / ``isolated (bwrap)``
    the probe runs in a Linux network namespace with no route to the host
    network, so ctypes, a subprocess, the private ``_socket`` module and a
    reloaded ``socket`` all reach nothing.
``python-level``
    no namespace was available. Python's socket entry points are replaced with
    a refusal inside the probe, which stops ordinary socket use but NOT ctypes,
    a subprocess or ``_socket`` — so a scorer importing any of those is
    classified ``executing`` and never run at all.

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
GUARD_PYTHON = "python-level"

# Preflighted in order; the first that exits 0 on `<prefix> true` wins. Each
# prefix puts the probe in a network namespace with no route to the host.
# (backend, base arguments, terminator). `--tmpfs /tmp` hides the host's /tmp
# from the probe, which is deliberate — but it also hides a PROJECT that lives
# under /tmp (an extracted tarball, CI scratch, a pytest tmp_path), and the
# scorer then fails to load for a reason that has nothing to do with the scorer.
# `isolation_command` binds the project back in, read-only, after the tmpfs.
ISOLATION_BACKENDS = (
    ("unshare", ["unshare", "-rn"], []),
    ("unshare", ["unshare", "-rn"], ["--"]),
    (
        "bwrap",
        [
            "bwrap",
            "--unshare-net",
            "--unshare-user-try",
            "--die-with-parent",
            "--ro-bind",
            "/",
            "/",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
        ],
        ["--"],
    ),
)
ISOLATION_PREFLIGHT_SECONDS = 5

GUARD_NOTE = {
    GUARD_PYTHON: (
        "the audit itself makes no network call; your scorer runs in a subprocess "
        "with Python's socket entry points disabled — at the python-level guard, "
        "code that uses ctypes, a subprocess or the private `_socket` module can "
        "still reach the network, so only scorers classified deterministic are "
        "probed; that classification is a static read of the module's imports and "
        "calls, not a sandbox"
    ),
    "isolated": (
        "the audit itself makes no network call; your scorer runs in a subprocess "
        "inside a network namespace with no route to the host network, so ctypes, a "
        "subprocess and the private `_socket` module reach nothing either"
    ),
}

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
# A dataset file whose name carries one of these tokens, beside another dataset
# file in the same directory, declares the holdout slice by file name — a
# two-file layout (`tuning.jsonl` + `holdout.jsonl`) that keeps a reserved row
# out of the search by never handing the file to `eval_dataset` at all. This is
# read in the project's own directories only; the guided first run writes its
# own such pair under `traigent-runs/`, which is walkthrough material (see
# WALKTHROUGH_DIR) and is noted on the card, never analysed as the project's
# dataset. Narrower than HOLDOUT_VALUES on purpose: in a file name, `eval` and
# `test` usually name the tuning set (`eval_dataset.jsonl`, `test_cases.jsonl`),
# not a reserved slice.
HOLDOUT_FILE_TOKENS = frozenset({"holdout", "heldout", "validation", "val"})
FILE_TOKEN_RE = re.compile(r"[^a-z0-9]+")
# The directory the guided first run (`traigent-first-run`) writes its
# walkthrough artifacts into: substitute agents, working-copy datasets (its
# `tuning.jsonl` + `holdout.jsonl` pair), the run record. They are listed, never
# counted as the project's own material.
WALKTHROUGH_DIR = "traigent-runs"

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
# Imports that step outside the Python socket layer entirely. A scorer using any
# of them is classified `executing` and never probed, at EVERY guard level: at
# python-level they are the documented hole, and keeping the rule the same on
# every machine means a project audits the same way everywhere.
ESCAPE_MODULES = frozenset({"ctypes", "multiprocessing", "_socket", "socketserver"})
EXECUTING_BUILTINS = frozenset({"exec", "eval", "compile", "__import__"})
# Builtins whose whole purpose is to name something at runtime. A literal
# argument is still readable; anything else is not, and an unreadable import is
# treated as an escape rather than assumed harmless.
DYNAMIC_NAMING_CALLS = frozenset(
    {"getattr", "__import__", "import_module", "exec", "eval"}
)
# `getattr(os, ...)` on one of these is a rebinding of a dangerous surface
# whatever the attribute name turns out to be.
SENSITIVE_GETATTR_TARGETS = frozenset(
    {"os", "sys", "ctypes", "socket", "_socket", "importlib", "subprocess", "builtins"}
)
EXECUTING_OS_ATTRS = frozenset(
    {
        "system",
        "popen",
        "fork",
        "forkpty",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "execl",
        "execle",
        "execlp",
        "posix_spawn",
        "posix_spawnp",
        "spawnl",
        "spawnv",
    }
)
ESCAPE_CALL_ATTRS = frozenset(
    {"reload", "import_module", "create_subprocess_exec", "create_subprocess_shell"}
)

# A name that says "this function scores something" on its own.
SCORER_NAME_RE = re.compile(r"(?i)^(score|evaluate|grade|metric)|_(score|scorer)$")
# A second parameter named like a gold value. On its own this is a weak signal:
# validators such as `check_stage(body, expected)` share the shape, so it needs
# corroboration (see `scorer_candidate_verdict`).
EXPECTED_PARAM_NAMES = frozenset({"expected", "expected_output"})
# The SDK binds a scoring callback by parameter NAME and the first one must be
# `output` (traigent-skills#8 P1), so `output` first is real corroboration.
SCORER_FIRST_PARAM = "output"
EVALUATOR_MODULE_RE = re.compile(r"(?i)(eval|scor|grad|metric|judge|assess)")
TEST_FILE_RE = re.compile(r"(?i)^(test_.+|.+_test|conftest)\.py$")
TEST_DIR_NAMES = frozenset({"test", "tests"})

SKIP_PRIVATE = "a name starting with `_`"
SKIP_TEST_FILE = "a test-file path"
SKIP_WEAK_MATCH = (
    "only a second parameter named `expected`, with neither `output` as its "
    "first parameter nor an evaluator-like module name"
)
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

# Names a knob can be read through without the parser being able to follow it.
CONFIG_MAPPING_NAMES = frozenset(
    {"config", "cfg", "kwargs", "configuration", "params", "settings", "options"}
)
CONFIG_READ_FUNCS = frozenset({"get_config", "get_current_config", "current_config"})
CONFIG_SPACE_WRAPPERS = frozenset({"ConfigurationSpace", "ConfigSpace"})
CHOICES_FACTORIES = frozenset({"Choices", "Categorical"})

KNOB_READ = "read"
KNOB_MAYBE = "possibly read through a config mapping"
KNOB_UNREAD = "declared, never read"

PUNCTUATION_RE = re.compile(r"[^\w\s]+")
WHITESPACE_RE = re.compile(r"\s+")

MAX_PYTHON_FILES = 4000
MAX_DATA_FILES = 400
MAX_DATA_BYTES = 25 * 1024 * 1024
MAX_ROWS = 20000
# Measured 2026-09-13 on synthetic rows of 12 tokens drawn from a 4000-word
# vocabulary: 6003 rows 1.35 s, 20000 rows 18.7 s, 50000 rows 136.8 s. The
# candidate generation is near-linear only when tokens are rare; on dense text
# it is not, so the ceiling stays where a worst case is about a second — and
# crossing it is now a printed finding, never a silent "ok".
NEAR_DUPLICATE_LIMIT = 5000
NEAR_DUPLICATE_JACCARD = 0.9
PROBE_TIMEOUT_SECONDS = 30
# The JSON report keeps everything; the printed card stops here so one tree with
# dozens of eval files or scorers stays readable.
MAX_DATASETS_IN_CARD = 10
MAX_SCORERS_IN_CARD = 8

_VERSION_PROBE_SOURCE = """
import json
import socket


class _Refused(RuntimeError):
    pass


def _refuse(*args, **kwargs):
    raise _Refused("traigent-setup-audit: network disabled in the free audit")


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


class NetworkDisabled(RuntimeError):
    """Raised in place of opening a socket."""


class _RefusingSocket:
    """Stands in for ``socket.socket``.

    A CLASS, not a function: ``ssl`` declares ``class SSLSocket(socket)``, and
    replacing the name with a function made ``import ssl`` raise a TypeError —
    which the first version of this audit then reported as scorer instability.
    """

    def __init__(self, *args, **kwargs):
        raise NetworkDisabled(GUARD_MESSAGE)


def install_network_guard() -> None:
    """Replace the socket entry points, in both ``socket`` and ``_socket``."""
    import socket

    def _refuse(*args, **kwargs):
        raise NetworkDisabled(GUARD_MESSAGE)

    for name in ("socket", "socketpair", "fromfd"):
        if hasattr(socket, name):
            setattr(socket, name, _RefusingSocket if name == "socket" else _refuse)
    for name in ("create_connection", "getaddrinfo", "gethostbyname"):
        if hasattr(socket, name):
            setattr(socket, name, _refuse)

    try:
        import _socket
    except ImportError:  # pragma: no cover - _socket is always present on CPython
        return
    for name in ("socket", "socketpair", "dup"):
        if hasattr(_socket, name):
            setattr(_socket, name, _RefusingSocket if name == "socket" else _refuse)
    for name in ("getaddrinfo", "gethostbyname", "create_connection"):
        if hasattr(_socket, name):
            setattr(_socket, name, _refuse)


def verify_network_guard() -> str:
    """Return ``active`` only when every guarded entry point actually refuses."""
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
        except NetworkDisabled:
            continue
        except Exception:
            return "uncertain"
        else:
            return "inactive"
    return "active"


def detect_isolation() -> tuple[str, str, list[str], list[str]]:
    """Preflight each sandbox and return ``(level, backend, args, terminator)``.

    The preflight is the evidence: a backend is only claimed after
    ``<command> true`` has actually exited 0 on this machine.
    """
    for name, args, terminator in ISOLATION_BACKENDS:
        try:
            completed = subprocess.run(
                [*args, *terminator, "true"],
                capture_output=True,
                timeout=ISOLATION_PREFLIGHT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0:
            return f"isolated ({name})", name, list(args), list(terminator)
    return GUARD_PYTHON, "", [], []


def isolation_command(
    backend: str, args: list[str], terminator: list[str], readable: list[Path]
) -> list[str]:
    """The sandbox prefix, with the paths the probe must still be able to read.

    Under bwrap the binds come AFTER ``--tmpfs /tmp`` so a project under /tmp is
    restored read-only inside the sandbox; without them the probe reports the
    audit's own containment as a fault in the user's scorer.
    """
    if not args:
        return []
    command = list(args)
    if backend == "bwrap":
        seen: set[str] = set()
        for path in readable:
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            text = str(resolved)
            if text == os.sep or text in seen:
                continue
            seen.add(text)
            command += ["--ro-bind", text, text]
    return command + list(terminator)


def guard_note(level: str) -> str:
    return GUARD_NOTE["isolated" if level.startswith("isolated") else GUARD_PYTHON]


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def printable_text(value: object) -> str:
    """Strip terminal control characters out of text read from a project.

    A model id, a dataset file name or a source line quoted into the card is the
    audited project's text, not ours. A planted escape sequence (`\\x1b[2K\\r`)
    inside a string literal rewrites the line the user is reading — including a
    consent line — and nothing else in the pipeline removes it. C0 and C1
    controls go, a tab becomes a space, and `\\n` survives because the caller
    joins lines with it.

    Imported by ``tier2_checks.py`` rather than copied: one implementation, one
    set of tests.
    """
    text = value if isinstance(value, str) else str(value)
    return "".join(
        " " if char == "\t"
        else char
        if char == "\n" or not (ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F)
        else ""
        for char in text
    )


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


def split_walkthrough_files(
    files: list[Path], root: Path
) -> tuple[list[Path], list[Path]]:
    """Separate first-run walkthrough artifacts from the project's own files."""
    project: list[Path] = []
    walkthrough: list[Path] = []
    for path in files:
        first = relative(path, root).split("/", 1)[0]
        (walkthrough if first == WALKTHROUGH_DIR else project).append(path)
    return project, walkthrough


def file_names_holdout(rel_file: str) -> bool:
    stem = Path(rel_file).stem.lower()
    tokens = [token for token in FILE_TOKEN_RE.split(stem) if token]
    if any(token in HOLDOUT_FILE_TOKENS for token in tokens):
        return True
    return any(a == "held" and b == "out" for a, b in zip(tokens, tokens[1:]))


def _expr_text(node: ast.AST, limit: int = 80) -> str:
    try:
        text = ast.unparse(node)
    except Exception:  # pragma: no cover - unparse is total on parsed trees
        return type(node).__name__
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------
# knob wiring (ast)
# --------------------------------------------------------------------------


@dataclass
class Knob:
    name: str
    values: list[object]
    values_readable: bool
    status: str
    file: str
    line: int


@dataclass
class EntryPoint:
    function: str
    file: str
    line: int
    knobs: list[Knob] = field(default_factory=list)
    config_space_note: str | None = None


def _traigent_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """``(module aliases, names bound to traigent.optimize)``.

    Without this an optuna study's ``@study.optimize(...)`` was reported as
    ``@traigent.optimize`` — the decorator name has to resolve to a traigent
    import, not merely end in ``.optimize``.
    """
    modules: set[str] = set()
    optimize_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "traigent" or alias.name.startswith("traigent."):
                    modules.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "traigent" or module.startswith("traigent."):
                for alias in node.names:
                    if alias.name == "optimize":
                        optimize_names.add(alias.asname or alias.name)
                    else:
                        modules.add(alias.asname or alias.name)
    return modules, optimize_names


def _decorator_is_traigent_optimize(
    node: ast.expr, modules: set[str], optimize_names: set[str]
) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute) and target.attr == "optimize":
        return isinstance(target.value, ast.Name) and target.value.id in modules
    if isinstance(target, ast.Name):
        return target.id in optimize_names
    return False


def _literal(node: ast.expr) -> object:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def module_dict_constants(tree: ast.AST) -> dict[str, ast.Dict]:
    """Module-level ``NAME = {...}`` bindings, so a config space passed by name
    can still be inventoried."""
    constants: dict[str, ast.Dict] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value
    return constants


def resolve_config_space(
    node: ast.expr, constants: dict[str, ast.Dict]
) -> tuple[ast.Dict | None, list[tuple[str, ast.expr]] | None]:
    """``(dict node, keyword pairs)`` for a configuration space expression.

    Handles a dict literal, a module-level constant referenced by name,
    ``ConfigurationSpace({...})`` / ``ConfigSpace({...})``, and ``dict(a=[...])``.
    Anything else returns ``(None, None)`` and is reported as unreadable rather
    than as an absent configuration space.
    """
    if isinstance(node, ast.Dict):
        return node, None
    if isinstance(node, ast.Name):
        found = constants.get(node.id)
        return (found, None) if found is not None else (None, None)
    if isinstance(node, ast.Call):
        callee = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if isinstance(node.func, ast.Name):
            callee = node.func.id
        if callee in CONFIG_SPACE_WRAPPERS and node.args:
            return resolve_config_space(node.args[0], constants)
        if callee == "dict" and node.keywords:
            pairs = [(kw.arg, kw.value) for kw in node.keywords if kw.arg]
            return None, pairs
    return None, None


def knob_values(node: ast.expr) -> tuple[list[object], bool]:
    """``(values, readable)``. Understands a literal list plus the
    ``Choices(...)`` / ``Choices.model(...)`` factories."""
    literal = _literal(node)
    if isinstance(literal, (list, tuple, set)):
        return list(literal), True
    if isinstance(node, ast.Call):
        callee = node.func
        name = None
        if isinstance(callee, ast.Name):
            name = callee.id
        elif isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name):
            name = callee.value.id
        if name in CHOICES_FACTORIES:
            values = [_literal(arg) for arg in node.args]
            if values and all(value is not None for value in values):
                return values, True
    return [], False


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
    mapping_names = set(CONFIG_MAPPING_NAMES)

    body: list[ast.stmt] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = node.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            parameters.add(arg.arg)
        if args.vararg:
            parameters.add(args.vararg.arg)
        if args.kwarg:
            parameters.add(args.kwarg.arg)
            mapping_names.add(args.kwarg.arg)
        body = list(node.body)

    def _is_mapping(value: ast.AST) -> bool:
        return isinstance(value, ast.Name) and value.id in mapping_names

    for child in (sub for stmt in body for sub in ast.walk(stmt)):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            literals.add(child.value)
        # Any use of a config mapping at all: `kwargs["k"]`, `kwargs.get("k")`,
        # `kwargs.items()`, `f(**kwargs)`. Requiring a Subscript missed the
        # commonest form and reported a read knob as never read.
        if isinstance(child, (ast.Subscript, ast.Attribute)) and _is_mapping(
            child.value
        ):
            dynamic = True
        if isinstance(child, ast.Call):
            for keyword in child.keywords:
                if keyword.arg is None and _is_mapping(keyword.value):
                    dynamic = True
            callee = child.func
            if isinstance(callee, ast.Attribute) and callee.attr in CONFIG_READ_FUNCS:
                dynamic = True
            if isinstance(callee, ast.Name) and callee.id in CONFIG_READ_FUNCS:
                dynamic = True
    return parameters, literals, dynamic


def knob_status(key: str, parameters: set[str], literals: set[str], dynamic: bool) -> str:
    if key in parameters or key in literals:
        return KNOB_READ
    if dynamic:
        return KNOB_MAYBE
    return KNOB_UNREAD


def collect_entry_points(tree: ast.AST, rel_path: str) -> list[EntryPoint]:
    modules, optimize_names = _traigent_aliases(tree)
    if not (modules or optimize_names):
        return []
    constants = module_dict_constants(tree)

    entry_points: list[EntryPoint] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorator = next(
            (
                dec
                for dec in node.decorator_list
                if _decorator_is_traigent_optimize(dec, modules, optimize_names)
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
                space, pairs = resolve_config_space(keyword.value, constants)
                if space is not None:
                    pairs = [
                        (_literal(k), v)
                        for k, v in zip(space.keys, space.values)
                        if k is not None
                    ]
                    pairs = [(k, v) for k, v in pairs if isinstance(k, str)]
                    key_nodes = {
                        _literal(k): k for k in space.keys if k is not None
                    }
                elif pairs is None:
                    entry.config_space_note = (
                        f"configuration_space is passed as `{_expr_text(keyword.value)}` "
                        f"at {rel_path}:{getattr(keyword.value, 'lineno', node.lineno)}; "
                        "the audit reads only a dict literal, a module-level constant, "
                        "a ConfigurationSpace(...) wrapper or dict(...), so its knobs "
                        "were not inventoried"
                    )
                    continue
                else:
                    key_nodes = {}
                for key, value_node in pairs:
                    values, readable = knob_values(value_node)
                    key_node = key_nodes.get(key)
                    entry.knobs.append(
                        Knob(
                            name=key,
                            values=values,
                            values_readable=readable,
                            status=knob_status(key, parameters, literals, dynamic),
                            file=rel_path,
                            line=getattr(
                                key_node or value_node, "lineno", node.lineno
                            ),
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
class SkippedScorer:
    """A function that matched the scorer search and was then ruled out."""

    function: str
    file: str
    line: int
    reason: str


@dataclass
class PythonInventory:
    files_scanned: int = 0
    files_total: int = 0
    files_unparsed: list[str] = field(default_factory=list)
    entry_points: list[EntryPoint] = field(default_factory=list)
    llm_call_sites: list[dict] = field(default_factory=list)
    scorers: list[ScorerCandidate] = field(default_factory=list)
    skipped_scorers: list[SkippedScorer] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


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


def _is_test_path(rel_path: str) -> bool:
    parts = rel_path.split("/")
    if any(part.lower() in TEST_DIR_NAMES for part in parts[:-1]):
        return True
    return bool(TEST_FILE_RE.match(parts[-1]))


def _module_looks_like_evaluator(rel_path: str) -> bool:
    return bool(EVALUATOR_MODULE_RE.search(Path(rel_path).stem))


def scorer_candidate_verdict(
    name: str, parameters: list[str], rel_path: str
) -> tuple[bool, str | None]:
    """Is this function a scorer worth reporting, and if not, why not?

    A strong NAME is enough on its own. The signature shape alone is not:
    ``check_stage(body, expected)`` and
    ``_read_lines_once_settled(broker, expected, timeout_s)`` are a validator and
    a test helper, and both were reported as scorers before this rule existed.
    """
    strong_name = bool(SCORER_NAME_RE.search(name))
    signature_shape = len(parameters) >= 2 and parameters[1] in EXPECTED_PARAM_NAMES
    if not (strong_name or signature_shape):
        return False, None
    if name.startswith("_"):
        return False, SKIP_PRIVATE
    if _is_test_path(rel_path):
        return False, SKIP_TEST_FILE
    if strong_name:
        return True, None
    if parameters[0] == SCORER_FIRST_PARAM or _module_looks_like_evaluator(rel_path):
        return True, None
    return False, SKIP_WEAK_MATCH


def _dynamic_naming_signal(child: ast.Call, callee: str) -> str | None:
    """A runtime-named import/attribute/eval this audit cannot read.

    Fail closed. Naming ctypes through the import builtin, reaching a shell
    helper through a computed `getattr` on `os`, and asking importlib for
    `subprocess` by string all reached the network while being classified
    deterministic, because the module name never appears as an import.
    """
    if callee not in DYNAMIC_NAMING_CALLS:
        return None
    if callee == "getattr":
        target = child.args[0] if child.args else None
        if isinstance(target, ast.Name) and target.id in SENSITIVE_GETATTR_TARGETS:
            return f"getattr on {target.id}"
        named = child.args[1] if len(child.args) > 1 else None
    else:
        named = child.args[0] if child.args else None
    if not (isinstance(named, ast.Constant) and isinstance(named.value, str)):
        return f"{callee} with a name the audit cannot read"
    return None


def classify_scorer(tree: ast.AST, node: ast.AST) -> tuple[str, list[str]]:
    """Classify one scorer, counting anything that leaves the Python socket
    layer as ``executing`` so it is never run.

    The WHOLE module is inspected, not just the function: ``runpy.run_path``
    executes every module-level statement, and any other function in the file
    can be called by the scorer.
    """
    modules = module_imports(tree)
    signals: list[str] = []
    judge = sorted(modules & JUDGE_MODULES)
    executing = sorted(modules & EXECUTING_MODULES)
    escapes = sorted(modules & ESCAPE_MODULES)

    for child in ast.walk(tree):
        if isinstance(child, ast.Call):
            callee = None
            if isinstance(child.func, ast.Name):
                callee = child.func.id
                if callee in EXECUTING_BUILTINS:
                    executing.append(f"builtin {callee}")
            elif isinstance(child.func, ast.Attribute):
                callee = child.func.attr
                owner = child.func.value
                if isinstance(owner, ast.Name) and owner.id == "os":
                    if callee in EXECUTING_OS_ATTRS:
                        executing.append(f"os.{callee}")
                if callee in ESCAPE_CALL_ATTRS:
                    owner_name = owner.id if isinstance(owner, ast.Name) else "?"
                    escapes.append(f"{owner_name}.{callee}")
            if isinstance(child.func, ast.Name) and callee in ESCAPE_CALL_ATTRS:
                escapes.append(callee)
            if callee is not None:
                dynamic = _dynamic_naming_signal(child, callee)
                if dynamic:
                    escapes.append(dynamic)
        # Touching the module table at all: popping a module and importing it
        # again rebuilds the real entry points, which is a reload spelled
        # differently.
        if (
            isinstance(child, ast.Attribute)
            and child.attr == "modules"
            and isinstance(child.value, ast.Name)
            and child.value.id == "sys"
        ):
            escapes.append("sys.modules")

    if judge:
        signals.append("imports " + ", ".join(judge))
    if executing:
        signals.append("uses " + ", ".join(sorted(set(executing))))
    if escapes:
        signals.append(
            "steps outside the socket layer via " + ", ".join(sorted(set(escapes)))
        )

    if judge and (executing or escapes):
        return "hybrid", signals
    if judge:
        return "llm-judge", signals
    if executing or escapes:
        return "executing", signals
    return "deterministic", signals


def classify_module_function(path: Path, function: str) -> tuple[str, list[str]]:
    """Classify a scorer chosen with ``--scorer`` that the inventory did not
    reach. Never assume deterministic: an unreadable module is `executing`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return "executing", ["the module could not be parsed, so it is not run"]
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function
        ):
            return classify_scorer(tree, node)
    return "executing", ["the function was not found in the module, so it is not run"]


def scan_python(files: list[Path], root: Path) -> PythonInventory:
    inventory = PythonInventory(files_total=len(files))
    considered = files[:MAX_PYTHON_FILES]
    if len(files) > len(considered):
        inventory.notes.append(
            f"scanned the first {len(considered)} of {len(files)} Python file(s); "
            "the rest were not inventoried"
        )
    for path in considered:
        rel = relative(path, root)
        try:
            source = path.read_text(encoding="utf-8-sig", errors="replace")
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
            is_candidate, skip_reason = scorer_candidate_verdict(
                node.name, parameters, rel
            )
            if is_candidate:
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
            elif skip_reason is not None:
                inventory.skipped_scorers.append(
                    SkippedScorer(
                        function=node.name,
                        file=rel,
                        line=node.lineno,
                        reason=skip_reason,
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
    if inventory.files_unparsed:
        inventory.notes.append(
            f"{len(inventory.files_unparsed)} Python file(s) could not be parsed "
            "and were not inventoried"
        )
    inventory.scorers.sort(key=lambda item: (item.file, item.line))
    inventory.skipped_scorers.sort(key=lambda item: (item.file, item.line))
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
class RawDataset:
    rows: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None


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
    # Row indexes by normalized input: kept for the cross-file overlap check,
    # never serialised into the report.
    input_index: dict[str, list[int]] = field(default_factory=dict, repr=False)
    holdout_input_index: dict[str, list[int]] = field(default_factory=dict, repr=False)
    non_holdout_input_index: dict[str, list[int]] = field(
        default_factory=dict, repr=False
    )
    untagged_input_index: dict[str, list[int]] = field(default_factory=dict, repr=False)
    # True when this file IS the holdout slice (declared by its name beside a
    # tuning file): it is judged against the holdout minimum only.
    holdout_by_name: bool = False


NO_HOLDOUT_FINDING = "no split marker on any row, so no holdout slice is declared"


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


def load_rows(path: Path) -> RawDataset:
    """Read a candidate dataset file, recording every truncation and skip.

    A cap or a parse failure that leaves no trace is worse than no check at
    all: it prints a smaller row count, or drops the file entirely, and the
    verdict reads clean.
    """
    suffix = path.suffix.lower()
    result = RawDataset()
    try:
        size = path.stat().st_size
    except OSError as exc:
        result.skipped = f"could not be read ({type(exc).__name__})"
        return result
    if size > MAX_DATA_BYTES:
        result.skipped = (
            f"is {size / 1024 / 1024:.1f} MiB, over the "
            f"{MAX_DATA_BYTES // 1024 // 1024} MiB cap, so it was not analysed"
        )
        return result

    try:
        if suffix == ".jsonl":
            bad_lines = 0
            total_lines = 0
            truncated = False
            with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    total_lines += 1
                    if len(result.rows) >= MAX_ROWS:
                        truncated = True
                        continue
                    try:
                        item = json.loads(line)
                    except ValueError:
                        bad_lines += 1
                        continue
                    if isinstance(item, dict):
                        result.rows.append(item)
            if bad_lines:
                result.notes.append(
                    f"{bad_lines} line(s) were not valid JSON and were skipped"
                )
            if truncated:
                result.notes.append(
                    f"read the first {MAX_ROWS} of {total_lines} line(s); the rest "
                    "were not analysed"
                )
            return result
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
            if not isinstance(payload, list):
                result.skipped = "is not a JSON array of objects"
                return result
            if len(payload) > MAX_ROWS:
                result.notes.append(
                    f"read the first {MAX_ROWS} of {len(payload)} row(s); the rest "
                    "were not analysed"
                )
            result.rows = [
                item for item in payload[:MAX_ROWS] if isinstance(item, dict)
            ]
            return result
        if suffix == ".csv":
            with path.open(
                "r", encoding="utf-8-sig", errors="replace", newline=""
            ) as handle:
                reader = csv.DictReader(handle)
                for index, item in enumerate(reader):
                    if index >= MAX_ROWS:
                        result.notes.append(
                            f"read the first {MAX_ROWS} row(s); the rest were not "
                            "analysed"
                        )
                        break
                    result.rows.append(dict(item))
            return result
    except (OSError, ValueError, csv.Error) as exc:
        result.skipped = f"could not be parsed ({type(exc).__name__})"
        return result
    return result


def _tokenize(text: str) -> frozenset[str]:
    return frozenset(text.split())


def near_duplicate_pairs(rows: list[DatasetRow]) -> list[list[int]]:
    """Row-index pairs whose normalized inputs are close but not identical."""
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


def analyse_dataset(
    path: Path, root: Path, raw: RawDataset
) -> DatasetReport:
    rows = raw.rows
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
    holdout_by_input: dict[str, list[int]] = defaultdict(list)
    non_holdout_by_input: dict[str, list[int]] = defaultdict(list)
    untagged_by_input: dict[str, list[int]] = defaultdict(list)
    for row in parsed:
        by_input[row.normalized_input].append(row.index)
        if row.split in HOLDOUT_VALUES:
            holdout_by_input[row.normalized_input].append(row.index)
        else:
            non_holdout_by_input[row.normalized_input].append(row.index)
        if row.split is None:
            untagged_by_input[row.normalized_input].append(row.index)
    exact_groups = sorted(
        (indices for indices in by_input.values() if len(indices) > 1),
        key=lambda group: group[0],
    )

    split_counts = Counter(row.split for row in parsed if row.split)
    named_holdout = file_names_holdout(relative(path, root))
    holdout_inputs = {
        row.normalized_input for row in parsed
        if row.split in HOLDOUT_VALUES or (row.split is None and named_holdout)
    }
    other_inputs = {
        row.normalized_input
        for row in parsed
        if row.split not in HOLDOUT_VALUES
        and (row.split is not None or not named_holdout)
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

    findings: list[str] = list(raw.notes)
    count = len(parsed)
    if count < MIN_SMOKE:
        findings.append(f"{count} rows is under the {MIN_SMOKE}-row smoke minimum")
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
    if len(parsed) > NEAR_DUPLICATE_LIMIT:
        near_pairs: list[list[int]] = []
        findings.append(
            f"near-duplicate detection skipped: {len(parsed)} rows over the "
            f"{NEAR_DUPLICATE_LIMIT}-row ceiling, so near-duplicates were not "
            "looked for"
        )
    else:
        near_pairs = near_duplicate_pairs(parsed)
        if near_pairs:
            findings.append(f"{len(near_pairs)} near-duplicate input pair(s)")
    holdout_rows = sum(
        value for key, value in split_counts.items() if key in HOLDOUT_VALUES
    )
    if not split_counts:
        findings.append(NO_HOLDOUT_FINDING)
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
        input_index=dict(by_input),
        holdout_input_index=dict(holdout_by_input),
        non_holdout_input_index=dict(non_holdout_by_input),
        untagged_input_index=dict(untagged_by_input),
    )


def apply_sibling_holdouts(reports: list[DatasetReport]) -> None:
    """Read the two-file holdout layout: a holdout-named file beside a tuning
    file in one directory declares the holdout slice for both, and the overlap
    check runs across the pair. Explicit row tags win; untagged rows inherit
    their file's role."""
    by_dir: dict[str, list[DatasetReport]] = defaultdict(list)
    for report in reports:
        by_dir[str(Path(report.file).parent)].append(report)
    for group in by_dir.values():
        holdouts = [r for r in group if file_names_holdout(r.file)]
        tuning = [r for r in group if r not in holdouts]
        if not holdouts or not tuning:
            continue
        holdout_inputs: set[str] = set()
        total = 0
        for report in holdouts:
            if report.split_counts:
                # Tagged rows keep their declared roles. A holdout-named file
                # that contains tuning rows is contradictory; do not silently
                # relabel those rows just to make the sibling layout pass.
                # Untagged rows still inherit the holdout role from the file.
                holdout_inputs.update(report.holdout_input_index)
                holdout_inputs.update(report.untagged_input_index)
                untagged_rows = sum(
                    len(indexes) for indexes in report.untagged_input_index.values()
                )
                report.holdout_rows += untagged_rows
                non_holdout_rows = sum(
                    count
                    for split, count in report.split_counts.items()
                    if split not in HOLDOUT_VALUES
                )
                if non_holdout_rows:
                    report.findings.append(
                        f"holdout-named file contradicts {non_holdout_rows} per-row "
                        "split marker(s) naming a non-holdout slice; per-row markers win"
                    )
                if untagged_rows:
                    report.findings.append(
                        f"{untagged_rows} untagged row(s) inherit the holdout role "
                        "from the file name"
                    )
                report.findings = [
                    finding
                    for finding in report.findings
                    if not (
                        report.holdout_rows
                        and finding.startswith(
                            "split markers present but none name a holdout slice"
                        )
                    )
                    and not finding.startswith("holdout slice has ")
                ]
                if 0 < report.holdout_rows < MIN_HOLDOUT:
                    report.findings.append(
                        f"holdout slice has {report.holdout_rows} rows, under the "
                        f"{MIN_HOLDOUT}-row minimum"
                    )
                report.holdout_by_name = (
                    report.holdout_rows == report.rows and non_holdout_rows == 0
                )
            else:
                holdout_inputs.update(report.input_index)
                report.holdout_rows = report.rows
                report.holdout_by_name = True
                report.findings.append(
                    f"holdout slice declared by file name: {report.rows} row(s), "
                    "no per-row split marker"
                )
                if report.rows < MIN_HOLDOUT:
                    report.findings.append(
                        f"holdout slice has {report.rows} rows, under the "
                        f"{MIN_HOLDOUT}-row minimum"
                    )
            if report.holdout_by_name:
                # A dedicated holdout file is judged against the holdout
                # minimum, not the tuning minimum meant for searchable rows.
                report.findings = [
                    finding
                    for finding in report.findings
                    if finding != NO_HOLDOUT_FINDING
                    and "first-tuning-slice minimum" not in finding
                ]
            total += report.holdout_rows
        names = ", ".join(r.file for r in holdouts)
        for report in tuning:
            if report.holdout_rows == 0 and total:
                report.holdout_rows = total
                report.findings = [
                    finding
                    for finding in report.findings
                    if finding != NO_HOLDOUT_FINDING
                    and not finding.startswith(
                        "split markers present but none name a holdout slice"
                    )
                ]
                report.findings.append(
                    f"holdout slice declared by sibling file {names} ({total} row(s))"
                )
            overlap = sorted(
                index
                for text, indexes in report.non_holdout_input_index.items()
                if text in holdout_inputs
                for index in indexes
            )
            report.holdout_overlap = sorted(
                set(report.holdout_overlap).union(overlap)
            )[:20]
            if overlap:
                report.findings.append(
                    f"{len(overlap)} row(s) appear in both this file and the "
                    f"sibling holdout file"
                )


def scan_datasets(
    files: list[Path], root: Path
) -> tuple[list[DatasetReport], int, list[str], list[str]]:
    candidates = [
        path for path in files if path.suffix.lower() in {".jsonl", ".json", ".csv"}
    ]
    considered = candidates[:MAX_DATA_FILES]
    notes: list[str] = []
    if len(candidates) > len(considered):
        notes.append(
            f"looked at the first {len(considered)} of {len(candidates)} "
            "JSONL/JSON/CSV file(s); the rest were not analysed"
        )
    reports: list[DatasetReport] = []
    skipped: list[str] = []
    for path in considered:
        raw = load_rows(path)
        if raw.skipped:
            skipped.append(f"{relative(path, root)} {raw.skipped}")
            continue
        if not raw.rows:
            continue
        with_input = sum(
            1 for row in raw.rows if any(key in row for key in INPUT_KEYS)
        )
        if with_input == 0 or with_input < 0.5 * len(raw.rows):
            continue
        reports.append(analyse_dataset(path, root, raw))
    reports.sort(key=lambda report: report.file)
    apply_sibling_holdouts(reports)
    return reports, len(candidates), notes, sorted(skipped)


# --------------------------------------------------------------------------
# scorer probe
# --------------------------------------------------------------------------


def build_probe_payload(datasets: list[DatasetReport], root: Path):
    """Return ``(good, partial, bad, source)`` probe values."""
    for report in sorted(datasets, key=lambda item: -item.rows):
        raw = load_rows(root / report.file)
        if not raw.rows:
            continue
        values: list[str] = []
        for row in raw.rows:
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


RESULT_MARKER = "<<<TRAIGENT_SETUP_AUDIT_RESULT>>>"
PROBE_STAGES = frozenset(
    {
        "load",
        "call",
        "timeout",
        "launch",
        "no-result",
        "unreadable-request",
        "tampered-result",
    }
)
GUARD_STATES = frozenset({"active", "inactive", "uncertain"})
SCORE_CASES = frozenset({"good", "partial", "bad"})
ERROR_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
ERROR_SITE_RE = re.compile(r"^[\w./\\-]{1,200}:[0-9]{1,7}$")


def _numbers(value: object) -> list[float] | None:
    if not isinstance(value, list) or len(value) > 1000:
        return None
    out: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        out.append(float(item))
    return out


def _clean_error(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("error_type")
    site = value.get("error_site")
    case = value.get("case")
    cleaned: dict = {}
    if not (isinstance(kind, str) and ERROR_TYPE_RE.match(kind)):
        return None
    cleaned["error_type"] = kind
    if site is None:
        cleaned["error_site"] = None
    elif isinstance(site, str) and ERROR_SITE_RE.match(site):
        cleaned["error_site"] = site
    else:
        cleaned["error_site"] = None
    if case in SCORE_CASES:
        cleaned["case"] = case
    return cleaned


def validate_probe_payload(payload: object) -> tuple[dict, int]:
    """Copy only known keys of known shape out of the child's result.

    The parent used to merge the child's whole JSON object into the report, so a
    scorer with an ``atexit`` handler that printed a JSON line could forge
    ``ran``, its own scores and a free-text field carrying an API key. Nothing
    is copied now unless it is on this list AND passes its type check; every
    other key is dropped and counted.
    """
    if not isinstance(payload, dict):
        return {"ran": False, "stage": "tampered-result"}, 0

    clean: dict = {}
    known = 0

    if isinstance(payload.get("ran"), bool):
        clean["ran"] = payload["ran"]
        known += 1
    if isinstance(payload.get("network_blocked"), bool):
        clean["network_blocked"] = payload["network_blocked"]
        known += 1
    if payload.get("network_guard") in GUARD_STATES:
        clean["network_guard"] = payload["network_guard"]
        known += 1
    if payload.get("stage") in PROBE_STAGES:
        clean["stage"] = payload["stage"]
        known += 1
    if isinstance(payload.get("repeats"), int) and not isinstance(
        payload.get("repeats"), bool
    ):
        clean["repeats"] = payload["repeats"]
        known += 1

    scores = payload.get("scores")
    if isinstance(scores, dict) and set(scores) <= SCORE_CASES:
        converted = {name: _numbers(value) for name, value in scores.items()}
        if all(value is not None for value in converted.values()):
            clean["scores"] = converted
            known += 1

    errors = payload.get("errors")
    if isinstance(errors, list) and len(errors) <= 100:
        cleaned = [_clean_error(item) for item in errors]
        if all(item is not None for item in cleaned):
            clean["errors"] = cleaned
            known += 1

    top_fault = _clean_error(payload)
    if top_fault is not None and "error_type" in payload:
        clean["error_type"] = top_fault["error_type"]
        clean["error_site"] = top_fault["error_site"]
        known += 1

    if "ran" not in clean:
        return {"ran": False, "stage": "tampered-result"}, len(payload)
    return clean, max(0, len(payload) - known)


def _framed_lines(stdout: str) -> list[str]:
    return [
        line[len(RESULT_MARKER) :]
        for line in stdout.splitlines()
        if line.startswith(RESULT_MARKER)
    ]


def run_scorer_probe(
    interpreter: str,
    scorer: ScorerCandidate,
    root: Path,
    payload: tuple[str, str, str, str],
    repeats: int,
    isolation: list[str],
) -> dict:
    probe_script = Path(__file__).resolve().parent / "scorer_probe.py"
    good, partial, bad, source = payload
    module_path = (root / scorer.file).resolve()
    request = {
        "module": str(module_path),
        "root": str(root.resolve()),
        "function": scorer.function,
        "good": good,
        "partial": partial,
        "bad": bad,
        "repeats": repeats,
    }
    command = [*isolation, interpreter, str(probe_script), "--request-stdin"]
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
        return {"ran": False, "stage": "timeout", "payload_source": source}
    except OSError as exc:
        return {
            "ran": False,
            "stage": "launch",
            "error_type": type(exc).__name__,
            "payload_source": source,
        }

    # Never relay the child's stderr text: a scorer that prints a key to stderr
    # before dying would put it in the report. Only its size is recorded.
    stderr_bytes = len(completed.stderr.encode("utf-8", errors="replace"))
    framed = _framed_lines(completed.stdout)
    if len(framed) != 1:
        # Zero: the probe never got to print. More than one: something else in
        # the process printed a result line, so no line can be trusted.
        stage = "no-result" if not framed else "tampered-result"
        return {
            "ran": False,
            "stage": stage,
            "stderr_bytes": stderr_bytes,
            "framed_result_lines": len(framed),
            "payload_source": source,
        }
    try:
        parsed = json.loads(framed[0])
    except ValueError:
        return {
            "ran": False,
            "stage": "tampered-result",
            "stderr_bytes": stderr_bytes,
            "framed_result_lines": 1,
            "payload_source": source,
        }
    result, dropped = validate_probe_payload(parsed)
    result["payload_source"] = source
    result["stderr_bytes"] = stderr_bytes
    result["framed_result_lines"] = 1
    result["dropped_keys"] = dropped
    return result


def _show(scores: list[float]) -> str:
    """One probe score, rounded for reading. The JSON keeps the full value."""
    if not scores:
        return "n/a"
    return f"{scores[0]:.4g}"


def _fault_phrase(result: dict) -> str:
    """A fault named by exception TYPE and location only — never its message."""
    kind = result.get("error_type") or "an error"
    site = result.get("error_site")
    return f"{kind}" + (f" at {site}" if site else "")


PROBE_FAILURE_SENTENCE = {
    "load": "the scorer module raised {fault} while loading, so it never ran",
    "timeout": (
        f"the probe did not finish within {PROBE_TIMEOUT_SECONDS} seconds, so no "
        "score was produced"
    ),
    "launch": "the probe subprocess could not be started ({fault})",
    "no-result": (
        "the probe produced no readable result (the scorer module most likely "
        "ended the process itself)"
    ),
    "tampered-result": (
        "the probe's result line was absent, duplicated or malformed, so nothing "
        "the scorer process printed is trusted"
    ),
    "no-scores": "every probe call raised {fault}, so no score was produced",
}


def probe_metrics(result: dict | None) -> dict:
    """One reading of a probe result, shared by the card and the next step."""
    if result is None:
        return {"verdict": "none"}
    if result.get("network_blocked"):
        return {"verdict": "blocked"}
    if not result.get("ran"):
        stage = result.get("stage", "no-result")
        return {
            "verdict": "failed",
            "stage": stage,
            "sentence": PROBE_FAILURE_SENTENCE.get(
                stage, PROBE_FAILURE_SENTENCE["no-result"]
            ).format(fault=_fault_phrase(result)),
        }
    scores = result.get("scores") or {}
    good = list(scores.get("good") or [])
    partial = list(scores.get("partial") or [])
    bad = list(scores.get("bad") or [])
    errors = list(result.get("errors") or [])
    if not good:
        fault = _fault_phrase(errors[0] if errors else {})
        return {
            "verdict": "failed",
            "stage": "no-scores",
            "sentence": PROBE_FAILURE_SENTENCE["no-scores"].format(fault=fault),
        }
    ordered = bool(good and bad) and good[0] > bad[0]
    if partial:
        ordered = ordered and good[0] >= partial[0] >= bad[0]
    return {
        "verdict": "ran",
        "good": good,
        "partial": partial,
        "bad": bad,
        "repeats": len(good),
        "distinct": len(set(good)),
        "stable": len(set(good)) == 1,
        "ordered": ordered,
        "errors": errors,
    }


UNMEASURED_MEANING = (
    "The scorer could not be run, so its repeatability is unmeasured — a score "
    "movement cannot yet be separated from scorer variation."
)


def summarize_probe(result: dict) -> tuple[str, list[str]]:
    metrics = probe_metrics(result)
    if metrics["verdict"] == "blocked":
        return "blocked", [
            "the scorer tried to open a network connection and the audit's "
            "network guard refused it, so no score was produced",
        ]
    if metrics["verdict"] == "failed":
        return "failed", [metrics["sentence"]]

    evidence = [
        f"repeat-scoring the same pair {metrics['repeats']} times returned "
        + (
            "one identical score"
            if metrics["stable"]
            else f"{metrics['distinct']} different scores"
        ),
        "known-good / partial / known-bad probes scored "
        f"{_show(metrics['good'])} / {_show(metrics['partial'])} / "
        f"{_show(metrics['bad'])}"
        + (
            " (ordered as expected)"
            if metrics["ordered"]
            else " (not ordered as expected)"
        ),
    ]
    if metrics["errors"]:
        faults = ", ".join(
            sorted({_fault_phrase(error) for error in metrics["errors"]})
        )
        evidence.append(f"{len(metrics['errors'])} probe call(s) raised {faults}")
    status = (
        "ok"
        if metrics["stable"] and metrics["ordered"] and not metrics["errors"]
        else "attention"
    )
    return status, evidence


# --------------------------------------------------------------------------
# setup checks
# --------------------------------------------------------------------------


def project_interpreter(root: Path) -> str:
    # `.venv` first; then `.venv-traigent`, the throwaway environment a guided
    # first run creates when the project has none; then this audit's own.
    for name in (".venv", ".venv-traigent"):
        candidate = root / name / "bin" / "python"
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
        return {
            "interpreter": interpreter,
            "traigent_version": None,
            "error_type": type(exc).__name__,
        }
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {
            "interpreter": interpreter,
            "traigent_version": None,
            "error_type": "UnreadableVersionProbe",
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
            text = path.read_text(encoding="utf-8-sig", errors="replace")
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
    evidence.extend(inventory.notes)
    if inventory.entry_points:
        for entry in inventory.entry_points:
            evidence.append(
                f"`@traigent.optimize` on `{entry.function}` at "
                f"{entry.file}:{entry.line}, {len(entry.knobs)} declared knob(s)"
            )
            if entry.config_space_note:
                evidence.append(entry.config_space_note)
        unread = [
            knob
            for entry in inventory.entry_points
            for knob in entry.knobs
            if knob.status == KNOB_UNREAD
        ]
        maybe = [
            knob
            for entry in inventory.entry_points
            for knob in entry.knobs
            if knob.status == KNOB_MAYBE
        ]
        unreadable_values = [
            knob
            for entry in inventory.entry_points
            for knob in entry.knobs
            if not knob.values_readable
        ]
        for knob in unread:
            evidence.append(
                f"knob `{knob.name}` is declared at {knob.file}:{knob.line} and the "
                "decorated function body never reads it"
            )
        for knob in maybe:
            evidence.append(
                f"knob `{knob.name}` at {knob.file}:{knob.line} is read through a "
                "mapping the parser cannot follow, so whether it reaches the body "
                "is unconfirmed"
            )
        for knob in unreadable_values:
            evidence.append(
                f"knob `{knob.name}` at {knob.file}:{knob.line} has values the audit "
                "could not read, so they are not listed"
            )
        no_space = [
            entry
            for entry in inventory.entry_points
            if not entry.knobs and not entry.config_space_note
        ]
        for entry in no_space:
            evidence.append(
                f"`{entry.function}` at {entry.file}:{entry.line} declares no "
                "configuration space, so there is nothing to search"
            )
        unreadable_space = [
            entry for entry in inventory.entry_points if entry.config_space_note
        ]
        problems = bool(unread or no_space or unreadable_space or inventory.notes)
        status = "attention" if problems else ("attention" if maybe else "ok")
        if unread:
            meaning = (
                "A knob the function never reads cannot change the output, so every "
                "trial that varies it is spend with no effect."
            )
        elif no_space:
            meaning = (
                "A decorated function with no configuration space gives the "
                "optimizer one point to evaluate, so there is nothing to compare."
            )
        elif unreadable_space:
            meaning = (
                "The configuration space was not readable statically, so this audit "
                "cannot say whether its knobs reach the function body — check those "
                "by hand."
            )
        elif maybe:
            meaning = (
                f"{len(maybe)} knob(s) are read through a mapping the parser cannot "
                "follow — confirm by hand that each one reaches the body."
            )
        else:
            meaning = (
                "Every declared knob is read directly by the function body, so a "
                "search over them can change the output."
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


def dataset_area(
    reports: list[DatasetReport],
    candidates: int,
    notes: list[str],
    skipped_files: list[str],
) -> dict:
    skip_lines = [f"{item} — not analysed" for item in skipped_files]
    if not reports:
        return {
            "status": "attention" if (notes or skipped_files) else "not-found",
            "evidence": [
                f"searched {candidates} JSONL/JSON/CSV file(s) for rows carrying an "
                f"input-like key ({'/'.join(INPUT_KEYS)}), found none",
                *notes,
                *skip_lines,
            ],
            "meaning": (
                "With no examples there is nothing to score a configuration against; "
                "`traigent-dataset-curate` covers building a first slice."
            ),
        }
    evidence: list[str] = list(notes) + skip_lines
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
    problems = (
        any(report.findings for report in reports) or bool(notes) or bool(skipped_files)
    )
    status = "attention" if problems else "ok"
    meaning = (
        "Row shortfalls, duplicates, a missing holdout slice and anything the audit "
        "could not read all widen the error bars on a measured score, so a small "
        "movement between configurations may be sampling, not improvement."
        if status == "attention"
        else "Row counts, gold coverage and a disjoint holdout slice are all within "
        "the documented minimums, so a measured movement has something to rest on."
    )
    return {"status": status, "evidence": evidence, "meaning": meaning}


KIND_LABEL = {
    "llm-judge": "LLM-judge",
    "executing": "executing",
    "hybrid": "hybrid",
    "deterministic": "deterministic",
}
KIND_REASON = {
    "llm-judge": "this audit makes no provider calls",
    "executing": "this audit runs no user code that itself executes code",
    "hybrid": "this audit neither calls a provider nor executes generated code",
}


def _handles(items, limit: int = 3) -> str:
    shown = [f"{item.file}:{item.line}" for item in items[:limit]]
    if len(items) > limit:
        shown.append(f"and {len(items) - limit} more")
    return ", ".join(shown)


def not_run_lines(candidates) -> list[str]:
    """One line per REASON, not one per scorer."""
    by_kind: dict[str, list[ScorerCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_kind[candidate.kind].append(candidate)
    lines: list[str] = []
    for kind in sorted(by_kind):
        group = by_kind[kind]
        signals = Counter(
            signal for candidate in group for signal in candidate.signals
        )
        detail = ", ".join(
            f"{signal} ×{count}" for signal, count in sorted(signals.items())
        )
        lines.append(
            f"{len(group)} scorer(s) classified {KIND_LABEL.get(kind, kind)} were "
            f"not run{f' ({detail})' if detail else ''}: {_handles(group)} — "
            f"{KIND_REASON.get(kind, 'this audit does not run them')}; "
            "`traigent-eval-audit` assesses those"
        )
    return lines


def skipped_scorer_lines(skipped: list[SkippedScorer]) -> list[str]:
    if not skipped:
        return []
    by_reason: dict[str, list[SkippedScorer]] = defaultdict(list)
    for item in skipped:
        by_reason[item.reason].append(item)
    parts = [
        f"{len(group)} with {reason}" for reason, group in sorted(by_reason.items())
    ]
    return [
        f"skipped {len(skipped)} function(s) that matched the search but are not "
        f"scorers ({'; '.join(parts)}): {_handles(skipped)} — every one is in the "
        "JSON report, so a real scorer ruled out here is visible, not silently "
        "dropped"
    ]


def scorer_area(
    inventory: PythonInventory,
    probe: dict | None,
    probed: ScorerCandidate | None,
    refusal: str | None,
) -> dict:
    if not inventory.scorers and refusal is None:
        return {
            "status": "attention" if inventory.skipped_scorers else "not-found",
            "evidence": [
                "searched for functions named score*/evaluate*/grade*/metric* or "
                f"taking `expected` as a second parameter in "
                f"{inventory.files_scanned} Python file(s), found none",
                *skipped_scorer_lines(inventory.skipped_scorers),
            ],
            "meaning": (
                "Without a scorer there is no objective, so no configuration can be "
                "ranked; `traigent-eval-build` covers wiring one."
            ),
        }
    shown = inventory.scorers[:MAX_SCORERS_IN_CARD]
    evidence = [
        f"`{candidate.function}` at {candidate.file}:{candidate.line} "
        f"classified {candidate.kind}"
        + (f" ({'; '.join(candidate.signals)})" if candidate.signals else "")
        for candidate in shown
    ]
    if len(inventory.scorers) > len(shown):
        evidence.append(
            f"{len(inventory.scorers) - len(shown)} further scorer(s) are in the "
            "JSON report and not printed here"
        )
    evidence.extend(skipped_scorer_lines(inventory.skipped_scorers))
    evidence.extend(
        not_run_lines(c for c in inventory.scorers if c.kind != "deterministic")
    )
    if refusal is not None:
        evidence.append(refusal)
        return {
            "status": "attention",
            "evidence": evidence,
            "meaning": UNMEASURED_MEANING,
        }
    if probe is None or probed is None:
        evidence.append(
            "no deterministic scorer was probed; pass `--scorer FILE.py:FUNCTION` "
            "to choose one"
        )
        return {
            "status": "attention",
            "evidence": evidence,
            "meaning": UNMEASURED_MEANING,
        }

    probe_status, probe_evidence = summarize_probe(probe)
    evidence.append(
        f"probed `{probed.function}` at {probed.file}:{probed.line} in a separate "
        f"process ({probe.get('payload_source')} probe values)"
    )
    evidence.extend(probe_evidence)
    status = "ok" if probe_status == "ok" else "attention"
    if probe_status == "blocked":
        meaning = (
            "A scorer that reaches the network is not a local deterministic scorer; "
            "its score depends on a service this audit will not call."
        )
    elif probe_status == "failed":
        meaning = UNMEASURED_MEANING
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
        evidence.append(f"traigent {version} is importable by {sdk['interpreter']}")
    else:
        evidence.append(
            f"traigent is not installed for {sdk['interpreter']}"
            + (f" ({sdk['error_type']})" if sdk.get("error_type") else "")
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


STOP_LINE = (
    "Stopping after this free audit is a valid choice; nothing here has left "
    "your machine."
)


def next_step(
    inventory: PythonInventory,
    reports: list[DatasetReport],
    probe: dict | None,
    probed: ScorerCandidate | None,
) -> dict:
    """Exactly one next step, chosen by the most blocking finding."""
    metrics = probe_metrics(probe)

    if not inventory.entry_points:
        return {
            "branch": "a",
            "skills": ["traigent-setup-quickstart", "traigent-setup-decorator"],
            "line": (
                f"No `@traigent.optimize` was found in {inventory.files_scanned} "
                "Python file(s), so there is no search space yet — install and "
                "configure the SDK with `traigent-setup-quickstart`, then wire one "
                "decorated function with `traigent-setup-decorator`."
            ),
        }

    blank = next(
        (
            entry
            for entry in inventory.entry_points
            if not entry.knobs and not entry.config_space_note
        ),
        None,
    )
    all_unread = next(
        (
            entry
            for entry in inventory.entry_points
            if entry.knobs
            and all(knob.status == KNOB_UNREAD for knob in entry.knobs)
        ),
        None,
    )
    if blank is not None:
        return {
            "branch": "b",
            "skills": ["traigent-optimize-config-space"],
            "line": (
                f"`{blank.function}` at {blank.file}:{blank.line} declares 0 knobs, "
                "so every trial would evaluate the same configuration — define a "
                "real configuration space with `traigent-optimize-config-space`."
            ),
        }
    if all_unread is not None:
        return {
            "branch": "b",
            "skills": ["traigent-optimize-config-space"],
            "line": (
                f"`{all_unread.function}` at {all_unread.file}:{all_unread.line} "
                f"declares {len(all_unread.knobs)} knob(s) and the body reads none "
                "of them, so varying them cannot change the output — rework the "
                "configuration space with `traigent-optimize-config-space`."
            ),
        }

    if not inventory.scorers:
        return {
            "branch": "c",
            "skills": ["traigent-eval-build"],
            "line": (
                f"No scorer was found in {inventory.files_scanned} Python file(s), "
                "so no configuration can be ranked — wire one with "
                "`traigent-eval-build`."
            ),
        }

    if metrics["verdict"] == "ran" and not (metrics["stable"] and metrics["ordered"]):
        if not metrics["stable"]:
            symptom = (
                f"returned {metrics['distinct']} different scores for the same "
                f"pair across {metrics['repeats']} repeats"
            )
        else:
            symptom = (
                "did not rank a known-good answer above a known-bad one "
                f"({_show(metrics['good'])} vs {_show(metrics['bad'])})"
            )
        return {
            "branch": "d",
            "skills": ["traigent-eval-build", "traigent-eval-audit"],
            "line": (
                f"`{probed.function}` at {probed.file}:{probed.line} {symptom}, so a "
                "configuration comparison would be measuring the scorer — make it "
                "repeatable with `traigent-eval-build`, then assess it with "
                "`traigent-eval-audit`."
            ),
        }

    if metrics["verdict"] != "ran":
        kinds = Counter(candidate.kind for candidate in inventory.scorers)
        summary = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))
        return {
            "branch": "e",
            "skills": ["traigent-eval-audit"],
            "line": (
                f"{len(inventory.scorers)} scorer(s) were found ({summary}) and none "
                "was measured here, so their reliability is unknown — assess them "
                "with `traigent-eval-audit`."
            ),
        }

    if not reports:
        return {
            "branch": "f",
            "skills": ["traigent-dataset-curate"],
            "line": (
                "No evaluation dataset was found, so there is nothing to score a "
                "configuration against — build a first tuning slice and a holdout "
                "slice with `traigent-dataset-curate`."
            ),
        }

    # A file that is itself the holdout slice (declared by name) has no tuning
    # rows to judge: only the holdout minimum applies to it.
    short = [
        report
        for report in reports
        if (not report.holdout_by_name and report.rows < MIN_TUNING)
        or report.holdout_rows < MIN_HOLDOUT
    ]
    if short:
        tuning_short = [r for r in short if not r.holdout_by_name]
        worst = min(tuning_short or short, key=lambda report: report.rows)
        if worst.holdout_by_name:
            line = (
                f"{worst.file} is a {worst.rows}-row holdout slice declared by "
                f"file name, under the {MIN_HOLDOUT}-row holdout minimum, so a "
                "small score movement would not be resolvable — grow it with "
                "`traigent-dataset-curate`."
            )
        else:
            # Name only the minimum(s) actually missed.
            missed = []
            if worst.rows < MIN_TUNING:
                missed.append(f"the {MIN_TUNING}-row tuning minimum")
            if worst.holdout_rows < MIN_HOLDOUT:
                missed.append(f"the {MIN_HOLDOUT}-row holdout minimum")
            line = (
                f"{worst.file} has {worst.rows} row(s) and a {worst.holdout_rows}-row "
                f"holdout slice, under {' and '.join(missed)}, so a small score "
                "movement would not be resolvable — grow and split it with "
                "`traigent-dataset-curate`."
            )
        return {
            "branch": "f",
            "skills": ["traigent-dataset-curate"],
            "line": line,
        }

    return {
        "branch": "g",
        "skills": ["traigent-optimize-run"],
        "line": (
            "Entry point, knobs, dataset and scorer all check out, so the open "
            "question is whether tuning moves anything — run a mock dry-run first, "
            "then one small bounded run, with `traigent-optimize-run`."
        ),
    }


def open_questions(areas: dict, datasets: list[DatasetReport]) -> list[str]:
    questions: list[str] = []
    if areas["scorer"]["status"] != "not-found":
        questions.append(
            "Whether the scorer agrees with an independent signal on real model "
            "output. Repeat scoring measures repeatability, not correctness. A "
            "completed run lets you RETRIEVE Traigent's evaluator-quality verdict "
            "if it has one — it may abstain, which is not a pass; "
            "`traigent-eval-audit` is the skill that asks for it."
        )
    if datasets:
        questions.append(
            "Which individual rows are mislabelled, redundant or too hard. A "
            "completed run lets you RETRIEVE the examples the service flagged and "
            "the per-example metadata it already holds — a flag is not proof, and "
            "the result may be empty; `traigent-dataset-curate` is the skill that "
            "asks for it."
        )
    questions.append(
        "Whether tuning moves the score at all, and which knob moves it. Only a "
        "real run answers that; `traigent-optimize-run` starts one and "
        "`traigent-analyze-variable-importance` ranks the knobs afterwards."
    )
    questions.append(
        "What to do next given your own numbers. Traigent's planning service "
        "returns an advisory plan before a run, and after one you can retrieve "
        "the service's suggested next action with its own confidence; "
        "`traigent-analyze-guidance` is the skill that fetches both."
    )
    questions.append(
        "A completed run is necessary for those retrievals and is not sufficient: "
        "the service can abstain, return zero rows, or hold no computed result. "
        "Stopping after this audit is a valid outcome, and buying a run only to "
        "make an analysis service answer is not."
    )
    return questions


def not_established(guard_level: str) -> list[str]:
    items = [
        "Repeat-scoring measures repeatability, not correctness. A scorer that "
        "returns the same wrong number every time passes this probe.",
        "No lift is promised. This audit says nothing about whether optimization "
        "will improve your agent, and a flat or negative result is a real outcome.",
        "Knob wiring is detected statically. A knob read through a mapping the "
        "parser cannot follow is reported as possibly read, and a configuration "
        "space the parser cannot read is reported as unread, never as absent.",
        "Model ids are collected, not validated. Checking an id against a provider "
        "is a network call, which this tier does not make.",
        "Only Python is inventoried in this version. A JavaScript or TypeScript "
        "project is not searched for entry points or scorers.",
    ]
    if guard_level == GUARD_PYTHON:
        items.insert(
            0,
            "No network namespace was available on this machine, so the containment "
            "is the python-level guard: " + GUARD_NOTE[GUARD_PYTHON] + ".",
        )
    else:
        items.insert(
            0,
            "The probe subprocess ran with " + guard_level + ": " + GUARD_NOTE["isolated"] + ".",
        )
    return items


def build_report(root: Path, args: argparse.Namespace, guard: str) -> dict:
    guard_level, backend, isolation_args, isolation_terminator = detect_isolation()
    files, walkthrough_files = split_walkthrough_files(iter_project_files(root), root)
    python_files = [path for path in files if path.suffix == ".py"]
    inventory = scan_python(python_files, root)

    dataset_notes: list[str] = []
    skipped_files: list[str] = []
    if args.dataset:
        dataset_path = Path(args.dataset)
        raw = load_rows(dataset_path)
        reports = []
        if raw.skipped:
            skipped_files.append(f"{relative(dataset_path, root)} {raw.skipped}")
        elif raw.rows:
            reports.append(analyse_dataset(dataset_path, root, raw))
        dataset_candidates = 1
    else:
        reports, dataset_candidates, dataset_notes, skipped_files = scan_datasets(
            files, root
        )

    probed: ScorerCandidate | None = None
    refusal: str | None = None
    if args.scorer:
        file_part, _, function_part = args.scorer.rpartition(":")
        if not file_part or not function_part:
            raise ValueError("--scorer must be given as FILE.py:FUNCTION")
        chosen_file = relative(Path(file_part), root)
        selected = next(
            (
                candidate
                for candidate in inventory.scorers
                if candidate.file == chosen_file
                and candidate.function == function_part
            ),
            None,
        )
        if selected is None:
            kind, signals = classify_module_function(root / chosen_file, function_part)
            selected = ScorerCandidate(
                function=function_part,
                file=chosen_file,
                line=0,
                kind=kind,
                signals=signals,
                parameters=[],
            )
        # An explicit selection is not permission to run arbitrary code: a
        # judge calls a provider and an executing scorer runs code, and this
        # audit does neither, whichever way the scorer was chosen.
        if selected.kind == "deterministic":
            probed = selected
        else:
            refusal = (
                f"`{selected.function}` at {selected.file} was selected with "
                f"--scorer and refused: it is classified {selected.kind}"
                + (f" ({'; '.join(selected.signals)})" if selected.signals else "")
                + ", and this audit runs no scorer that calls a provider or "
                "executes code — `traigent-eval-audit` assesses those"
            )
    else:
        deterministic = [c for c in inventory.scorers if c.kind == "deterministic"]
        if len(deterministic) == 1:
            probed = deterministic[0]

    interpreter = project_interpreter(root)
    probe: dict | None = None
    isolation: list[str] = []
    if probed is not None:
        payload = build_probe_payload(reports, root)
        # The probe must still be able to READ the project and the scorer's own
        # directory inside the sandbox, or the sandbox looks like a broken scorer.
        readable = [root, (root / probed.file).resolve().parent]
        isolation = isolation_command(
            backend, isolation_args, isolation_terminator, readable
        )
        probe = run_scorer_probe(
            interpreter, probed, root, payload, args.repeats, isolation
        )

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
        "dataset": dataset_area(
            reports, dataset_candidates, dataset_notes, skipped_files
        ),
        "scorer": scorer_area(inventory, probe, probed, refusal),
        "setup": setup_area(sdk, keys, ignored, model_ids),
    }

    return {
        "schema": SCHEMA,
        "network_guard": guard_level,
        "network_guard_note": guard_note(guard_level),
        "audit_process_guard": guard,
        "isolation_command": isolation,
        "root": str(root.resolve()),
        "files": {
            "python_parsed": inventory.files_scanned,
            "python_total": inventory.files_total,
            "python_unparsed": inventory.files_unparsed[:20],
            "dataset_candidates": dataset_candidates,
            "dataset_files_not_analysed": skipped_files,
            "notes": inventory.notes + dataset_notes,
            "walkthrough": {
                "dir": WALKTHROUGH_DIR,
                "count": len(walkthrough_files),
                # The first run's own tuning/holdout working copies, when present:
                # named so the card can say where the graduate's reserved slice is.
                "holdout_files": sorted(
                    relative(path, root)
                    for path in walkthrough_files
                    if path.suffix.lower() in {".jsonl", ".json", ".csv"}
                    and file_names_holdout(relative(path, root))
                ),
            },
        },
        "areas": areas,
        "entry_points": [
            {
                "function": entry.function,
                "file": entry.file,
                "line": entry.line,
                "config_space_note": entry.config_space_note,
                "knobs": [
                    {
                        "name": knob.name,
                        "values": knob.values,
                        "values_readable": knob.values_readable,
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
            "near_duplicate_row_ceiling": NEAR_DUPLICATE_LIMIT,
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
        "skipped_scorer_candidates": [
            {
                "function": item.function,
                "file": item.file,
                "line": item.line,
                "reason": item.reason,
            }
            for item in inventory.skipped_scorers
        ],
        "scorer_selection_refused": refusal,
        "scorer_probe": probe,
        "next_step": next_step(inventory, reports, probe, probed),
        "setup": {
            "sdk": sdk,
            "keys": keys,
            "env_file_git_status": ignored,
            "model_ids_declared": model_ids,
        },
        "open_questions": open_questions(areas, reports),
        "not_established": not_established(guard_level),
    }


def render_card(report: dict) -> str:
    lines: list[str] = []
    root_name = Path(report["root"]).name or report["root"]
    lines.append(f"# Traigent setup audit — {root_name}")
    lines.append("")
    lines.append(
        f"Local audit. `network_guard: {report['network_guard']}` — "
        f"{report['network_guard_note']}."
    )
    lines.append("")
    lines.append(
        f"Scanned {report['files']['python_parsed']} Python file(s) and "
        f"{report['files']['dataset_candidates']} JSONL/JSON/CSV file(s) under "
        f"`{report['root']}`."
    )
    walkthrough = report["files"].get("walkthrough") or {}
    if walkthrough.get("count"):
        lines.append("")
        lines.append(
            f"{walkthrough['dir']}/: {walkthrough['count']} walkthrough file(s) from "
            "traigent-first-run — not counted as project material."
        )
        if walkthrough.get("holdout_files"):
            names = ", ".join(walkthrough["holdout_files"])
            lines.append(
                f"  The first run's reserved slice is {names} (a working copy): "
                "`traigent-boost-agent` continues from it; the project's own "
                "dataset above is judged on its own rows."
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

    lines.append("## Next step")
    lines.append("")
    lines.append(report["next_step"]["line"])
    lines.append("")
    lines.append(STOP_LINE)
    lines.append("")
    lines.append("## What code alone could not tell you")
    lines.append("")
    for question in report["open_questions"]:
        lines.append(f"- {question}")
    lines.append("")
    lines.append(
        "Each of those needs a Traigent service call, which sends data off this "
        "machine and can cost money. None of them runs here: run "
        "`tier2_checks.py --from-audit report.json` to see the approval cards, "
        "one per check, each naming what runs and what leaves the machine."
    )
    lines.append("")
    lines.append("## What this audit does not establish")
    lines.append("")
    for item in report["not_established"]:
        lines.append(f"- {item}")
    lines.append("")
    # Every line here carries text read out of the audited project — file names,
    # model ids, findings quoting source. `printable_text` is applied to the
    # WHOLE card rather than at each interpolation so a new evidence line cannot
    # be added later without it.
    return "\n".join(printable_text(line) for line in lines)


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
