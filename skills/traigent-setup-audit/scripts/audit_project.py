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
import importlib.metadata as md
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

SCHEMA ="traigent-setup-audit/v1"
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
# (traigent/evaluators/base.py: `input` then `input_data` for the input,
# `_EXPECTED_OUTPUT_FIELDS` for the gold keys). The SDK loads only
# SDK_INPUT_KEYS; the wider INPUT_KEYS list decides which files are candidate
# datasets, and a row keyed by anything outside SDK_INPUT_KEYS is a finding,
# because `eval_dataset` refuses that file.
SDK_INPUT_KEYS = ("input", "input_data")
INPUT_KEYS = (*SDK_INPUT_KEYS, "question", "prompt", "query", "messages")
EXPECTED_KEYS = ("output", "expected", "expected_output", "answer", "target", "label")
# Why a row has no usable gold value, in display order. The first gold key
# present decides; a later key never stands in for an unusable one.
GOLD_KIND_LABEL = {
    "absent": "with no gold key",
    "null": "null",
    "nan": "NaN",
    "infinite": "infinite",
    "empty": "empty string",
}
DATASET_SUFFIXES = (".jsonl", ".json", ".csv")
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
SCORER_NAME_RE = re.compile(r"(?i)(?:^(score|evaluate|grade|metric)|_(score|scorer)$)")
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
# The only environment variables a child that runs project code receives. An
# allowlist, not a credential denylist: credentials follow no naming rule
# (PGPASSWORD, DATABASE_URL, SSH_AUTH_SOCK, a proxy URL with a password in it),
# and neither the probe nor the sandbox prefix reads any other variable.
CHILD_ENV_NAMES = (
    "PATH",
    "HOME",
    "LANG",
    "LANGUAGE",
    "TZ",
    "TMPDIR",
    "TMP",
    "TEMP",
    # The POSIX and glibc locale categories, named one by one so the child's
    # environment is built by looking up each name, never by walking the
    # whole environment.
    "LC_ALL",
    "LC_ADDRESS",
    "LC_COLLATE",
    "LC_CTYPE",
    "LC_IDENTIFICATION",
    "LC_MEASUREMENT",
    "LC_MESSAGES",
    "LC_MONETARY",
    "LC_NAME",
    "LC_NUMERIC",
    "LC_PAPER",
    "LC_TELEPHONE",
    "LC_TIME",
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
# Distinct gold values of the probed kind read when choosing the known-bad
# answer. Bounded so a large dataset is not compared value by value.
PROBE_CANDIDATES = 32
# The JSON report keeps everything; the printed card stops here so one tree with
# dozens of eval files or scorers stays readable.
MAX_DATASETS_IN_CARD = 10
MAX_SCORERS_IN_CARD = 8


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

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NetworkDisabled(GUARD_MESSAGE)


def _replace_entry_points(
    module: object, names: tuple[str, ...], refuse: Callable[..., NoReturn]
) -> None:
    """Replace each of ``names`` the module has: ``socket`` with the refusing
    class, every other name with ``refuse``. A name the module lacks stays
    absent."""
    for name in names:
        if hasattr(module, name):
            setattr(module, name, _RefusingSocket if name == "socket" else refuse)


def install_network_guard() -> None:
    """Replace the socket entry points, in both ``socket`` and ``_socket``."""
    import socket

    def _refuse(*args: object, **kwargs: object) -> NoReturn:
        raise NetworkDisabled(GUARD_MESSAGE)

    _replace_entry_points(
        socket,
        (
            "socket",
            "socketpair",
            "fromfd",
            "create_connection",
            "getaddrinfo",
            "gethostbyname",
        ),
        _refuse,
    )

    try:
        import _socket
    except ImportError:  # pragma: no cover - _socket is always present on CPython
        return
    _replace_entry_points(
        _socket,
        (
            "socket",
            "socketpair",
            "dup",
            "getaddrinfo",
            "gethostbyname",
            "create_connection",
        ),
        _refuse,
    )


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
    # realpath, not Path.resolve(): on Python <= 3.12 resolve() raises
    # RuntimeError on a symlink loop, which then crashed the whole audit.
    try:
        real = Path(os.path.realpath(path))
        return real.relative_to(os.path.realpath(root)).as_posix()
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
            _add_import_aliases(node, modules)
        elif isinstance(node, ast.ImportFrom):
            _add_import_from_aliases(node, modules, optimize_names)
    return modules, optimize_names


def _is_traigent_module(name: str) -> bool:
    return name == "traigent" or name.startswith("traigent.")


def _add_import_aliases(node: ast.Import, modules: set[str]) -> None:
    """``import traigent[.x] [as y]`` binds a module alias."""
    for alias in node.names:
        if _is_traigent_module(alias.name):
            modules.add(alias.asname or alias.name.split(".", 1)[0])


def _add_import_from_aliases(
    node: ast.ImportFrom, modules: set[str], optimize_names: set[str]
) -> None:
    """``from traigent[.x] import optimize`` binds the decorator itself; any
    other imported name is recorded as a module alias."""
    if not _is_traigent_module(node.module or ""):
        return
    for alias in node.names:
        if alias.name == "optimize":
            optimize_names.add(alias.asname or alias.name)
        else:
            modules.add(alias.asname or alias.name)


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
        return _resolve_config_space_call(node, constants)
    return None, None


def _callee_name(func: ast.expr) -> str | None:
    """``f`` for ``f(...)`` and ``attr`` for ``obj.attr(...)``; else ``None``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _resolve_config_space_call(
    node: ast.Call, constants: dict[str, ast.Dict]
) -> tuple[ast.Dict | None, list[tuple[str, ast.expr]] | None]:
    """A ``ConfigurationSpace(...)`` / ``ConfigSpace(...)`` wrapper is unwrapped;
    ``dict(a=[...])`` gives its keyword pairs; any other call is unreadable."""
    callee = _callee_name(node.func)
    if callee in CONFIG_SPACE_WRAPPERS and node.args:
        return resolve_config_space(node.args[0], constants)
    if callee == "dict" and node.keywords:
        pairs = [(kw.arg, kw.value) for kw in node.keywords if kw.arg]
        return None, pairs
    return None, None


def _reportable_knob_values(values: list[object]) -> bool:
    """Use the report's JSON codec before accepting literal knob values."""
    try:
        json.dumps(values, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError, OverflowError):
        return False
    return True


def _gold_kind(value: object) -> str | None:
    """Why a gold value cannot be scored against, or ``None`` when it can.

    ``0``, ``False`` and ``[]`` are real labels; ``null``, a non-finite number
    and an empty or blank string are not."""
    if value is None:
        return "null"
    if isinstance(value, float) and math.isnan(value):
        return "nan"
    if isinstance(value, float) and math.isinf(value):
        return "infinite"
    if isinstance(value, str) and not value.strip():
        return "empty"
    return None


def knob_values(node: ast.expr) -> tuple[list[object], bool]:
    """``(values, readable)``. Understands a literal list plus the
    ``Choices(...)`` / ``Choices.model(...)`` factories. Values holding a
    value the report cannot encode count as unreadable."""
    literal = _literal(node)
    if isinstance(literal, (list, tuple, set)) and _reportable_knob_values(list(literal)):
        return list(literal), True
    if isinstance(node, ast.Call):
        values = _choices_values(node)
        if values is not None:
            return values, True
    return [], False


def _factory_name(callee: ast.expr) -> str | None:
    """``Choices`` for ``Choices(...)`` and for ``Choices.model(...)``."""
    if isinstance(callee, ast.Name):
        return callee.id
    if isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name):
        return callee.value.id
    return None


def _choices_values(node: ast.Call) -> list[object] | None:
    """The literal arguments of a choices factory call, or ``None`` when the
    call is not one or any argument is not a reportable literal."""
    if _factory_name(node.func) not in CHOICES_FACTORIES:
        return None
    values = [_literal(arg) for arg in node.args]
    if (
        values
        and all(value is not None for value in values)
        and _reportable_knob_values(values)
    ):
        return values
    return None


def function_read_surface(node: ast.AST) -> tuple[set[str], set[str], bool]:
    """Names the function could read a knob through.

    Returns ``(parameter names, string literals, reads a config mapping)``.

    Only the parameter list and the function BODY are inspected. Walking the
    whole node would include the decorator that declares the configuration
    space, and every declared knob name would then look like a literal the body
    reads — the exact defect this check exists to catch.
    """
    literals: set[str] = set()
    dynamic = False
    mapping_names = set(CONFIG_MAPPING_NAMES)
    parameters, body = _signature_surface(node, mapping_names)

    for child in (sub for stmt in body for sub in ast.walk(stmt)):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            literals.add(child.value)
        if _reads_config_mapping(child, mapping_names):
            dynamic = True
    return parameters, literals, dynamic


def _signature_surface(
    node: ast.AST, mapping_names: set[str]
) -> tuple[set[str], list[ast.stmt]]:
    """``(parameter names, body statements)`` of a function; empty for any
    other node. A ``**kwargs`` name is added to ``mapping_names``."""
    parameters: set[str] = set()
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return parameters, []
    args = node.args
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        parameters.add(arg.arg)
    if args.vararg:
        parameters.add(args.vararg.arg)
    if args.kwarg:
        parameters.add(args.kwarg.arg)
        mapping_names.add(args.kwarg.arg)
    return parameters, list(node.body)


def _reads_config_mapping(child: ast.AST, mapping_names: set[str]) -> bool:
    """Whether one node reads knobs in a way the parser cannot follow.

    Any use of a config mapping at all: `kwargs["k"]`, `kwargs.get("k")`,
    `kwargs.items()`, `f(**kwargs)`. Requiring a Subscript missed the
    commonest form and reported a read knob as never read. A call to a
    config reader (`get_config()`, `traigent.get_current_config()`) counts too.
    """

    def _is_mapping(value: ast.AST) -> bool:
        return isinstance(value, ast.Name) and value.id in mapping_names

    if isinstance(child, (ast.Subscript, ast.Attribute)) and _is_mapping(child.value):
        return True
    if not isinstance(child, ast.Call):
        return False
    if any(
        keyword.arg is None and _is_mapping(keyword.value) for keyword in child.keywords
    ):
        return True
    callee = child.func
    if isinstance(callee, ast.Attribute) and callee.attr in CONFIG_READ_FUNCS:
        return True
    return isinstance(callee, ast.Name) and callee.id in CONFIG_READ_FUNCS


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
        surface = function_read_surface(node)
        if isinstance(decorator, ast.Call):
            _add_declared_knobs(entry, decorator, constants, node, surface)
        entry.knobs.sort(key=lambda knob: knob.name)
        entry_points.append(entry)
    entry_points.sort(key=lambda item: (item.file, item.line))
    return entry_points


def _add_declared_knobs(
    entry: EntryPoint,
    decorator: ast.Call,
    constants: dict[str, ast.Dict],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    surface: tuple[set[str], set[str], bool],
) -> None:
    """Add a knob for every key of each configuration space keyword of the
    decorator; a space the audit cannot read sets the entry's note instead."""
    for keyword in decorator.keywords:
        if keyword.arg not in {"configuration_space", "config_space"}:
            continue
        pairs, key_nodes, note = _config_space_pairs(
            keyword, constants, entry.file, node
        )
        if note is not None:
            entry.config_space_note = note
            continue
        for key, value_node in pairs:
            entry.knobs.append(
                _declared_knob(key, value_node, key_nodes, surface, entry.file, node)
            )


def _config_space_pairs(
    keyword: ast.keyword,
    constants: dict[str, ast.Dict],
    rel_path: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[list[tuple[str, ast.expr]], dict[object, ast.expr], str | None]:
    """``(key/value pairs, key nodes by key, note)`` for one configuration
    space keyword. The note is set, with no pairs, when the space cannot be
    read statically."""
    space, pairs = resolve_config_space(keyword.value, constants)
    if space is not None:
        literal_pairs = [
            (_literal(k), v) for k, v in zip(space.keys, space.values) if k is not None
        ]
        pairs = [(k, v) for k, v in literal_pairs if isinstance(k, str)]
        key_nodes = {_literal(k): k for k in space.keys if k is not None}
        return pairs, key_nodes, None
    if pairs is None:
        note = (
            f"configuration_space is passed as `{_expr_text(keyword.value)}` "
            f"at {rel_path}:{getattr(keyword.value, 'lineno', node.lineno)}; "
            "the audit reads only a dict literal, a module-level constant, "
            "a ConfigurationSpace(...) wrapper or dict(...), so its knobs "
            "were not inventoried"
        )
        return [], {}, note
    return pairs, {}, None


def _declared_knob(
    key: str,
    value_node: ast.expr,
    key_nodes: dict[object, ast.expr],
    surface: tuple[set[str], set[str], bool],
    rel_path: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Knob:
    """One declared knob: its readable values and whether the body reads it."""
    values, readable = knob_values(value_node)
    key_node = key_nodes.get(key)
    parameters, literals, dynamic = surface
    return Knob(
        name=key,
        values=values,
        values_readable=readable,
        status=knob_status(key, parameters, literals, dynamic),
        file=rel_path,
        line=getattr(key_node or value_node, "lineno", node.lineno),
    )


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
            _call_signals(child, executing, escapes)
        # Touching the module table at all: popping a module and importing it
        # again rebuilds the real entry points, which is a reload spelled
        # differently.
        if _is_sys_modules(child):
            escapes.append("sys.modules")

    if judge:
        signals.append("imports " + ", ".join(judge))
    if executing:
        signals.append("uses " + ", ".join(sorted(set(executing))))
    if escapes:
        signals.append(
            "steps outside the socket layer via " + ", ".join(sorted(set(escapes)))
        )
    return _scorer_kind(judge, executing, escapes), signals


def _call_signals(child: ast.Call, executing: list[str], escapes: list[str]) -> None:
    """Record what one call does outside plain Python: an executing builtin or
    ``os`` function, a reload/import/subprocess escape, a runtime-named lookup."""
    callee = None
    if isinstance(child.func, ast.Name):
        callee = child.func.id
        if callee in EXECUTING_BUILTINS:
            executing.append(f"builtin {callee}")
        if callee in ESCAPE_CALL_ATTRS:
            escapes.append(callee)
    elif isinstance(child.func, ast.Attribute):
        callee = _attribute_call_signals(child.func, executing, escapes)
    if callee is not None:
        dynamic = _dynamic_naming_signal(child, callee)
        if dynamic:
            escapes.append(dynamic)


def _attribute_call_signals(
    func: ast.Attribute, executing: list[str], escapes: list[str]
) -> str:
    """Record the signals of an ``owner.attr(...)`` call; return ``attr``."""
    callee = func.attr
    owner = func.value
    is_os = isinstance(owner, ast.Name) and owner.id == "os"
    if is_os and callee in EXECUTING_OS_ATTRS:
        executing.append(f"os.{callee}")
    if callee in ESCAPE_CALL_ATTRS:
        owner_name = owner.id if isinstance(owner, ast.Name) else "?"
        escapes.append(f"{owner_name}.{callee}")
    return callee


def _is_sys_modules(child: ast.AST) -> bool:
    return (
        isinstance(child, ast.Attribute)
        and child.attr == "modules"
        and isinstance(child.value, ast.Name)
        and child.value.id == "sys"
    )


def _scorer_kind(judge: list[str], executing: list[str], escapes: list[str]) -> str:
    """``hybrid``, ``llm-judge``, ``executing`` or ``deterministic``."""
    if judge and (executing or escapes):
        return "hybrid"
    if judge:
        return "llm-judge"
    if executing or escapes:
        return "executing"
    return "deterministic"


def classify_module_function(path: Path, function: str) -> tuple[str, list[str], int]:
    """Classify a scorer chosen with ``--scorer`` that the inventory did not
    reach. Never assume deterministic: an unreadable module is `executing`.
    The line is 0 when the function is not found by name."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return "executing", ["the module could not be parsed, so it is not run"], 0
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function
        ):
            return (*classify_scorer(tree, node), node.lineno)
    return (
        "executing",
        ["the function was not found in the module, so it is not run"],
        0,
    )


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
        tree = _parse_python(path)
        if tree is None:
            inventory.files_unparsed.append(rel)
            continue
        inventory.files_scanned += 1
        inventory.entry_points.extend(collect_entry_points(tree, rel))

        modules = module_imports(tree)
        providers = sorted(modules & PROVIDER_MODULES)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _inventory_function(inventory, tree, node, rel, providers)
    if inventory.files_unparsed:
        inventory.notes.append(
            f"{len(inventory.files_unparsed)} Python file(s) could not be parsed "
            "and were not inventoried"
        )
    inventory.scorers.sort(key=lambda item: (item.file, item.line))
    inventory.skipped_scorers.sort(key=lambda item: (item.file, item.line))
    inventory.llm_call_sites.sort(key=lambda item: (item["file"], item["line"]))
    return inventory


def _parse_python(path: Path) -> ast.Module | None:
    """The module's syntax tree, or ``None`` when it cannot be read or parsed."""
    try:
        source = path.read_text(encoding="utf-8-sig", errors="replace")
        return ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return None


def _inventory_function(
    inventory: PythonInventory,
    tree: ast.AST,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel: str,
    providers: list[str],
) -> None:
    """File one function as a scorer, a skipped scorer candidate and/or an LLM
    call site."""
    parameters = [arg.arg for arg in node.args.args]
    is_candidate, skip_reason = scorer_candidate_verdict(node.name, parameters, rel)
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
    # Set when the file parsed but holds no object rows: a config file in
    # discovery, never a damaged dataset (that is `skipped`).
    not_rows: str | None = None
    # The key of a top-level list of input-keyed objects inside a JSON object:
    # a wrapped dataset, which discovery still names rather than drops.
    nested_rows: str | None = None
    # Non-standard constants (`NaN`, `Infinity`, `-Infinity`) by name.
    constants: dict[str, int] = field(default_factory=dict)


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
    # Informational lines (how the holdout slice was declared). Printed as
    # evidence, never counted as a problem: a finding is something to fix.
    notes: list[str] = field(default_factory=list)
    # Rows with neither `input` nor `input_data`: the SDK refuses the whole
    # file on the first one. One field drives both the finding and the next step.
    rows_without_sdk_input: int = 0
    # Full per-kind counts of rows with no usable gold value (GOLD_KIND_LABEL
    # keys); `missing_expected` keeps only the first 20 positions.
    missing_gold_counts: dict[str, int] = field(default_factory=dict)
    # Every overlapping row, before the 20-row cap on `holdout_overlap`.
    holdout_overlap_total: int = 0
    overlap_rows: set[int] = field(default_factory=set, repr=False)


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

    # Python's json accepts NaN/Infinity, which strict readers refuse: counted
    # here so the file's own non-standard constants become a finding.
    constants: Counter[str] = Counter()

    def _constant(name: str) -> float:
        constants[name] += 1
        return float(name)

    try:
        if suffix == ".jsonl":
            if _read_jsonl(path, result, _constant):
                return result
        elif suffix == ".json":
            _read_json(path, result, _constant)
        elif suffix == ".csv":
            _read_csv(path, result)
    except (OSError, ValueError, csv.Error) as exc:
        result.skipped = f"could not be parsed ({type(exc).__name__})"
        return result
    result.constants = dict(constants)
    if not result.rows and not result.not_rows:
        result.not_rows = "holds no rows"
    return result


def _read_jsonl(
    path: Path, result: RawDataset, parse_constant: Callable[[str], float]
) -> bool:
    """Read JSONL rows into ``result``. ``True`` when every line failed: the
    file is then recorded as damaged and ``result`` is final as it stands."""
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        total_lines, bad_lines, truncated = _scan_jsonl(handle, result, parse_constant)
    if not result.rows and bad_lines:
        # Every line failed: a damaged file, not an absent one.
        result.skipped = (
            f"could not be parsed (none of its {total_lines} line(s) is a "
            f"JSON object; {bad_lines} were not valid JSON)"
        )
        return True
    if bad_lines:
        result.notes.append(f"{bad_lines} line(s) were not valid JSON and were skipped")
    if truncated:
        result.notes.append(
            f"read the first {MAX_ROWS} of {total_lines} line(s); the rest "
            "were not analysed"
        )
    return False


def _scan_jsonl(
    handle: Iterable[str], result: RawDataset, parse_constant: Callable[[str], float]
) -> tuple[int, int, bool]:
    """Append each JSON-object line to ``result.rows`` up to ``MAX_ROWS``:
    ``(non-blank lines, lines that are not JSON, truncated)``."""
    bad_lines = 0
    total_lines = 0
    truncated = False
    for line in handle:
        line = line.strip()
        if not line:
            continue
        total_lines += 1
        if len(result.rows) >= MAX_ROWS:
            truncated = True
            continue
        try:
            item = json.loads(line, parse_constant=parse_constant)
        except ValueError:
            bad_lines += 1
            continue
        if isinstance(item, dict):
            result.rows.append(item)
    return total_lines, bad_lines, truncated


def _read_json(
    path: Path, result: RawDataset, parse_constant: Callable[[str], float]
) -> None:
    """Read a top-level JSON array of row objects into ``result``; an object
    or scalar is recorded as ``not_rows``."""
    payload = json.loads(
        path.read_text(encoding="utf-8-sig", errors="replace"),
        parse_constant=parse_constant,
    )
    if not isinstance(payload, list):
        result.nested_rows = _nested_row_key(payload)
        result.not_rows = (
            f"is a JSON object with a nested row list (`{result.nested_rows}`), "
            "which this audit does not read; name a top-level array"
            if result.nested_rows
            else "is not a JSON array of objects"
        )
        return
    if len(payload) > MAX_ROWS:
        result.notes.append(
            f"read the first {MAX_ROWS} of {len(payload)} row(s); the "
            "rest were not analysed"
        )
    result.rows = [item for item in payload[:MAX_ROWS] if isinstance(item, dict)]


def _read_csv(path: Path, result: RawDataset) -> None:
    """Read CSV rows, keyed by the header, into ``result`` up to ``MAX_ROWS``."""
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, item in enumerate(reader):
            if index >= MAX_ROWS:
                result.notes.append(
                    f"read the first {MAX_ROWS} row(s); the rest were not analysed"
                )
                break
            result.rows.append(dict(item))


def _nested_row_key(payload: object) -> str | None:
    """The first top-level key of a JSON object whose value is a non-empty list
    starting with an input-keyed object (``{"data": [{"input": ...}]}``)."""
    if not isinstance(payload, dict):
        return None
    for key, value in payload.items():
        if (
            isinstance(value, list)
            and value
            and isinstance(value[0], dict)
            and any(name in value[0] for name in INPUT_KEYS)
        ):
            return str(key)
    return None


def _tokenize(text: str) -> frozenset[str]:
    return frozenset(text.split())


def near_duplicate_pairs(rows: list[DatasetRow]) -> list[list[int]]:
    """Row-index pairs whose normalized inputs are close but not identical."""
    token_sets = {row.index: _tokenize(row.normalized_input) for row in rows}
    text_by_index = {row.index: row.normalized_input for row in rows}
    pairs: list[list[int]] = []
    for left, right in sorted(_candidate_pairs(token_sets, len(rows))):
        if text_by_index[left] == text_by_index[right]:
            continue
        if _jaccard(token_sets[left], token_sets[right]) >= NEAR_DUPLICATE_JACCARD:
            pairs.append([left, right])
    return pairs


def _candidate_pairs(
    token_sets: dict[int, frozenset[str]], row_count: int
) -> set[tuple[int, int]]:
    """Row-index pairs ``(low, high)`` sharing at least one token that is not
    common to more than ``max(50, 20%)`` of the rows."""
    index: dict[str, list[int]] = defaultdict(list)
    for row_index, tokens in token_sets.items():
        for token in tokens:
            index[token].append(row_index)
    common_cutoff = max(50, int(0.2 * row_count))
    candidates: set[tuple[int, int]] = set()
    for members in index.values():
        if len(members) > common_cutoff:
            continue
        for position, left in enumerate(members):
            for right in members[position + 1 :]:
                candidates.add((left, right) if left < right else (right, left))
    return candidates


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    """Token overlap of two inputs; ``-1.0`` when both are empty, so they are
    never a pair."""
    union = left | right
    if not union:
        return -1.0
    return len(left & right) / len(union)


def _row_gold(
    row: dict,
    position: int,
    expected_key_counts: Counter[str],
    missing_expected: list[int],
    gold_kinds: Counter[str],
) -> tuple[str | None, object]:
    """``(gold key, gold value)`` for one row, tallying a missing or unusable one.

    The first gold key present decides: an unusable value there is not rescued
    by a later key."""
    expected_key = next((key for key in EXPECTED_KEYS if key in row), None)
    if expected_key is None:
        missing_expected.append(position)
        gold_kinds["absent"] += 1
        return None, None
    kind = _gold_kind(row[expected_key])
    if kind is not None:
        missing_expected.append(position)
        gold_kinds[kind] += 1
        return None, None
    expected_key_counts[expected_key] += 1
    return expected_key, row[expected_key]


def _parse_dataset_rows(
    rows: list[dict],
) -> tuple[list[DatasetRow], Counter[str], Counter[str], list[int], Counter[str]]:
    """``(parsed rows, input key counts, gold key counts, rows with no usable
    gold, gold kinds)``. A row with no input-like key is not parsed."""
    parsed: list[DatasetRow] = []
    input_key_counts: Counter[str] = Counter()
    expected_key_counts: Counter[str] = Counter()
    missing_expected: list[int] = []
    gold_kinds: Counter[str] = Counter()
    for position, row in enumerate(rows):
        input_key = next((key for key in INPUT_KEYS if key in row), None)
        if input_key is None:
            continue
        input_key_counts[input_key] += 1
        expected_key, expected = _row_gold(
            row, position, expected_key_counts, missing_expected, gold_kinds
        )
        parsed.append(
            DatasetRow(
                index=position,
                input_key=input_key,
                normalized_input=normalize_text(row[input_key]),
                expected_key=expected_key,
                expected=expected,
                split=_row_split(row),
            )
        )
    return parsed, input_key_counts, expected_key_counts, missing_expected, gold_kinds


def _input_indexes(
    parsed: list[DatasetRow],
) -> tuple[
    dict[str, list[int]],
    dict[str, list[int]],
    dict[str, list[int]],
    dict[str, list[int]],
]:
    """Row indexes by normalized input: all rows, holdout-tagged rows, every
    other row, and untagged rows."""
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
    return by_input, holdout_by_input, non_holdout_by_input, untagged_by_input


def _exact_duplicate_groups(by_input: dict[str, list[int]]) -> list[list[int]]:
    """Groups of row indexes sharing a normalized input, by first index."""
    return sorted(
        (indices for indices in by_input.values() if len(indices) > 1),
        key=lambda group: group[0],
    )


def _split_counts(parsed: list[DatasetRow]) -> tuple[Counter[str], int]:
    """``(rows per split marker, rows in a holdout slice)``."""
    split_counts = Counter(row.split for row in parsed if row.split)
    holdout_rows = sum(
        value for key, value in split_counts.items() if key in HOLDOUT_VALUES
    )
    return split_counts, holdout_rows


def _is_holdout_row(row: DatasetRow, named_holdout: bool) -> bool:
    """A holdout-tagged row, or an untagged row in a holdout-named file."""
    return row.split in HOLDOUT_VALUES or (row.split is None and named_holdout)


def _holdout_overlap_rows(parsed: list[DatasetRow], named_holdout: bool) -> list[int]:
    """Indexes of rows whose normalized input is in both the holdout slice and
    another slice of the same file."""
    holdout_inputs = {
        row.normalized_input for row in parsed if _is_holdout_row(row, named_holdout)
    }
    other_inputs = {
        row.normalized_input
        for row in parsed
        if row.split not in HOLDOUT_VALUES
        and (row.split is not None or not named_holdout)
    }
    overlap_texts = holdout_inputs & other_inputs
    return sorted(
        row.index for row in parsed if row.normalized_input in overlap_texts
    )


def _label_counts(parsed: list[DatasetRow]) -> dict[str, int]:
    """Counts per scalar gold value, kept only for 20+ scalar rows over at most
    10 distinct values."""
    scalar_expected = [
        row.expected
        for row in parsed
        if isinstance(row.expected, (str, int, float, bool))
    ]
    if len(scalar_expected) < 20:
        return {}
    counted = Counter(str(value) for value in scalar_expected)
    if len(counted) > 10:
        return {}
    return dict(sorted(counted.items()))


def _size_findings(count: int) -> list[str]:
    if count < MIN_SMOKE:
        return [f"{count} rows is under the {MIN_SMOKE}-row smoke minimum"]
    if count < MIN_TUNING:
        return [
            f"{count} rows is under the {MIN_TUNING}-row first-tuning-slice minimum"
        ]
    return []


def _input_key_findings(
    row_total: int, input_key_counts: Counter[str]
) -> tuple[int, list[str]]:
    """``(rows with no input/input_data key, findings)``."""
    other_keys = {
        key: value
        for key, value in sorted(input_key_counts.items())
        if key not in SDK_INPUT_KEYS
    }
    keyless = row_total - sum(input_key_counts.values())
    rows_without_sdk_input = sum(other_keys.values()) + keyless
    if not rows_without_sdk_input:
        return rows_without_sdk_input, []
    detail = [f"{value} keyed `{key}`" for key, value in other_keys.items()]
    if keyless:
        detail.append(f"{keyless} with no input-like key at all")
    return rows_without_sdk_input, [
        f"{rows_without_sdk_input} row(s) have no `input`/`input_data` key "
        f"({', '.join(detail)}); `eval_dataset` reads only `input` or "
        "`input_data` and refuses the whole file on the first such row — "
        "rename or add the key"
    ]


def _gold_findings(gold_kinds: Counter[str]) -> list[str]:
    findings: list[str] = []
    if gold_kinds["absent"]:
        findings.append(
            f"{gold_kinds['absent']} row(s) carry no gold key "
            f"({'/'.join(EXPECTED_KEYS)})"
        )
    unusable = {
        kind: gold_kinds[kind]
        for kind in GOLD_KIND_LABEL
        if kind != "absent" and gold_kinds[kind]
    }
    if unusable:
        detail = ", ".join(
            f"{count} {GOLD_KIND_LABEL[kind]}" for kind, count in unusable.items()
        )
        findings.append(
            f"{sum(unusable.values())} row(s) carry a gold key with no usable "
            f"value ({detail})"
        )
    return findings


def _constant_findings(constants: dict[str, int]) -> list[str]:
    if not constants:
        return []
    named = ", ".join(f"{name} ×{count}" for name, count in sorted(constants.items()))
    return [
        f"{sum(constants.values())} non-standard JSON constant(s) in the "
        f"file ({named}); strict JSON readers refuse them"
    ]


def _near_duplicate_findings(
    parsed: list[DatasetRow],
) -> tuple[list[list[int]], list[str]]:
    """``(near-duplicate pairs, findings)``; skipped, and said so, over the
    row ceiling."""
    if len(parsed) > NEAR_DUPLICATE_LIMIT:
        return [], [
            f"near-duplicate detection skipped: {len(parsed)} rows over the "
            f"{NEAR_DUPLICATE_LIMIT}-row ceiling, so near-duplicates were not "
            "looked for"
        ]
    near_pairs = near_duplicate_pairs(parsed)
    if near_pairs:
        return near_pairs, [f"{len(near_pairs)} near-duplicate input pair(s)"]
    return near_pairs, []


def _holdout_findings(split_counts: Counter[str], holdout_rows: int) -> list[str]:
    if not split_counts:
        return [NO_HOLDOUT_FINDING]
    if holdout_rows == 0:
        return [
            "split markers present but none name a holdout slice "
            f"({'/'.join(sorted(HOLDOUT_VALUES))})"
        ]
    if holdout_rows < MIN_HOLDOUT:
        return [
            f"holdout slice has {holdout_rows} rows, under the {MIN_HOLDOUT}-row minimum"
        ]
    return []


def _label_findings(label_counts: dict[str, int]) -> list[str]:
    if not label_counts:
        return []
    largest = max(label_counts.values())
    if largest >= 0.8 * sum(label_counts.values()):
        return [
            f"one label covers {largest} of {sum(label_counts.values())} labelled rows"
        ]
    return []


def analyse_dataset(
    path: Path, root: Path, raw: RawDataset
) -> DatasetReport:
    rows = raw.rows
    parsed, input_key_counts, expected_key_counts, missing_expected, gold_kinds = (
        _parse_dataset_rows(rows)
    )
    by_input, holdout_by_input, non_holdout_by_input, untagged_by_input = (
        _input_indexes(parsed)
    )
    exact_groups = _exact_duplicate_groups(by_input)
    split_counts, holdout_rows = _split_counts(parsed)
    holdout_overlap = _holdout_overlap_rows(
        parsed, file_names_holdout(relative(path, root))
    )
    label_counts = _label_counts(parsed)

    findings: list[str] = list(raw.notes)
    count = len(parsed)
    findings.extend(_size_findings(count))
    rows_without_sdk_input, key_findings = _input_key_findings(
        len(rows), input_key_counts
    )
    findings.extend(key_findings)
    findings.extend(_gold_findings(gold_kinds))
    findings.extend(_constant_findings(raw.constants))
    if exact_groups:
        findings.append(
            f"{len(exact_groups)} group(s) of rows share a normalized input"
        )
    near_pairs, near_findings = _near_duplicate_findings(parsed)
    findings.extend(near_findings)
    findings.extend(_holdout_findings(split_counts, holdout_rows))
    if holdout_overlap:
        findings.append(
            f"{len(holdout_overlap)} row(s) appear in both the holdout slice and another slice"
        )
    findings.extend(_label_findings(label_counts))

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
        rows_without_sdk_input=rows_without_sdk_input,
        missing_gold_counts={
            kind: gold_kinds[kind] for kind in GOLD_KIND_LABEL if gold_kinds[kind]
        },
        holdout_overlap_total=len(holdout_overlap),
        overlap_rows=set(holdout_overlap),
        input_index=dict(by_input),
        holdout_input_index=dict(holdout_by_input),
        non_holdout_input_index=dict(non_holdout_by_input),
        untagged_input_index=dict(untagged_by_input),
    )


def _drop_superseded_holdout_findings(report: DatasetReport) -> None:
    """Drop the per-file holdout findings a tagged holdout-named file replaces:
    the holdout-size finding always (it is re-stated below), and "none name a
    holdout slice" once the file holds holdout rows."""
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


def _declare_tagged_holdout(report: DatasetReport, holdout_inputs: set[str]) -> None:
    """A holdout-named file whose rows carry split tags.

    Tagged rows keep their declared roles. A holdout-named file that contains
    tuning rows is contradictory; do not silently relabel those rows just to
    make the sibling layout pass. Untagged rows still inherit the holdout role
    from the file."""
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
        report.notes.append(
            f"{untagged_rows} untagged row(s) inherit the holdout role "
            "from the file name"
        )
    _drop_superseded_holdout_findings(report)
    if 0 < report.holdout_rows < MIN_HOLDOUT:
        report.findings.append(
            f"holdout slice has {report.holdout_rows} rows, under the "
            f"{MIN_HOLDOUT}-row minimum"
        )
    report.holdout_by_name = (
        report.holdout_rows == report.rows and non_holdout_rows == 0
    )


def _declare_untagged_holdout(
    report: DatasetReport, holdout_inputs: set[str]
) -> None:
    """A holdout-named file with no per-row split marker: every row is holdout."""
    holdout_inputs.update(report.input_index)
    report.holdout_rows = report.rows
    report.holdout_by_name = True
    report.notes.append(
        f"holdout slice declared by file name: {report.rows} row(s), "
        "no per-row split marker"
    )
    if report.rows < MIN_HOLDOUT:
        report.findings.append(
            f"holdout slice has {report.rows} rows, under the "
            f"{MIN_HOLDOUT}-row minimum"
        )


def _declare_holdout_file(report: DatasetReport, holdout_inputs: set[str]) -> int:
    """Read one holdout-named file as a holdout slice, adding its holdout
    inputs to ``holdout_inputs``; returns its holdout row count."""
    if report.split_counts:
        _declare_tagged_holdout(report, holdout_inputs)
    else:
        _declare_untagged_holdout(report, holdout_inputs)
    if report.holdout_by_name:
        # A dedicated holdout file is judged against the holdout
        # minimum, not the tuning minimum meant for searchable rows.
        report.findings = [
            finding
            for finding in report.findings
            if finding != NO_HOLDOUT_FINDING
            and "first-tuning-slice minimum" not in finding
        ]
    return report.holdout_rows


def _link_tuning_file(
    report: DatasetReport, holdout_inputs: set[str], total: int, names: str
) -> None:
    """Give a tuning file its sibling holdout slice and check the pair for
    shared inputs."""
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
        report.notes.append(
            f"holdout slice declared by sibling file {names} ({total} row(s))"
        )
    overlap = sorted(
        index
        for text, indexes in report.non_holdout_input_index.items()
        if text in holdout_inputs
        for index in indexes
    )
    report.overlap_rows |= set(overlap)
    report.holdout_overlap_total = len(report.overlap_rows)
    report.holdout_overlap = sorted(report.overlap_rows)[:20]
    if overlap:
        report.findings.append(
            f"{len(overlap)} row(s) appear in both this file and the "
            f"sibling holdout file"
        )


def _sibling_groups(
    reports: list[DatasetReport],
) -> list[tuple[list[DatasetReport], list[DatasetReport]]]:
    """``(holdout-named files, other files)`` for each directory holding both."""
    by_dir: dict[str, list[DatasetReport]] = defaultdict(list)
    for report in reports:
        by_dir[str(Path(report.file).parent)].append(report)
    groups = []
    for group in by_dir.values():
        holdouts = [r for r in group if file_names_holdout(r.file)]
        tuning = [r for r in group if r not in holdouts]
        if holdouts and tuning:
            groups.append((holdouts, tuning))
    return groups


def apply_sibling_holdouts(reports: list[DatasetReport]) -> None:
    """Read the two-file holdout layout: a holdout-named file beside a tuning
    file in one directory declares the holdout slice for both, and the overlap
    check runs across the pair. Explicit row tags win; untagged rows inherit
    their file's role."""
    for holdouts, tuning in _sibling_groups(reports):
        holdout_inputs: set[str] = set()
        total = 0
        for report in holdouts:
            total += _declare_holdout_file(report, holdout_inputs)
        names = ", ".join(r.file for r in holdouts)
        for report in tuning:
            _link_tuning_file(report, holdout_inputs, total, names)


def _read_dataset(
    path: Path, root: Path, *, named: bool
) -> tuple[DatasetReport | None, str | None]:
    """``(report, skip line)`` for one candidate file, shared by discovery and
    ``--dataset`` so both read a file the same way.

    A file that cannot be parsed is always a skip line: the audit cannot tell
    it from a damaged dataset. A file that parses but holds no rows is a skip
    line when the user named it; in discovery it is dropped like a JSONL whose
    rows carry no input-like key (a `package.json`), unless its name declares
    a holdout slice or it wraps a row list in an object — those are evaluation
    assets this audit did not read, so they stay named.
    """
    raw = load_rows(path)
    rel = relative(path, root)
    if raw.skipped:
        return None, f"{rel} {raw.skipped}"
    if raw.not_rows:
        if named or raw.nested_rows or file_names_holdout(rel):
            return None, f"{rel} {raw.not_rows}"
        return None, None
    if not named and _mostly_without_input(raw.rows):
        return None, None
    return analyse_dataset(path, root, raw), None


def _mostly_without_input(rows: list[dict]) -> bool:
    """No row, or fewer than half of them, carries an input-like key."""
    with_input = sum(1 for row in rows if any(key in row for key in INPUT_KEYS))
    return with_input == 0 or with_input < 0.5 * len(rows)


def scan_datasets(
    files: list[Path], root: Path
) -> tuple[list[DatasetReport], int, list[str], list[str]]:
    candidates = [path for path in files if path.suffix.lower() in DATASET_SUFFIXES]
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
        report, skip = _read_dataset(path, root, named=False)
        if report is not None:
            reports.append(report)
        if skip is not None:
            skipped.append(skip)
    reports.sort(key=lambda report: report.file)
    apply_sibling_holdouts(reports)
    return reports, len(candidates), notes, sorted(skipped)


def explicit_datasets(
    path: Path, root: Path
) -> tuple[list[DatasetReport], int, list[str], list[str]]:
    """``(reports, candidates, notes, skipped)`` for ``--dataset FILE``.

    The named file is read whatever its rows look like, and any holdout-named
    sibling in its directory is read as its declared holdout slice, exactly as
    discovery reads the two-file layout. Naming the holdout file itself pulls
    in no tuning sibling: only holdout-named siblings are looked for.
    """
    reports: list[DatasetReport] = []
    skipped: list[str] = []
    _keep_read(_read_dataset(path, root, named=True), reports, skipped)
    siblings = _holdout_siblings(path, root)
    considered = siblings[: MAX_DATA_FILES - 1]
    notes: list[str] = []
    if len(siblings) > len(considered):
        notes.append(
            f"looked at the first {1 + len(considered)} of {1 + len(siblings)} "
            "JSONL/JSON/CSV file(s), including the named dataset and holdout siblings; "
            "the rest were not analysed"
        )
    for sibling in considered:
        _keep_read(_read_dataset(sibling, root, named=False), reports, skipped)
    reports.sort(key=lambda report: report.file)
    apply_sibling_holdouts(reports)
    return reports, 1 + len(siblings), notes, sorted(skipped)


def _keep_read(
    read: tuple[DatasetReport | None, str | None],
    reports: list[DatasetReport],
    skipped: list[str],
) -> None:
    """File one ``_read_dataset`` result under the reports or the skip lines."""
    report, skip = read
    if report is not None:
        reports.append(report)
    if skip is not None:
        skipped.append(skip)


def _holdout_siblings(path: Path, root: Path) -> list[Path]:
    """Holdout-named dataset files beside ``path``, sorted, ``path`` itself
    (by resolved path) excluded; none when the directory cannot be listed."""
    if not path.parent.is_dir():
        return []
    try:
        entries = list(path.parent.iterdir())
    except OSError:
        entries = []
    named_real = os.path.realpath(path)
    return sorted(
        entry
        for entry in entries
        if entry.is_file()
        and entry.suffix.lower() in DATASET_SUFFIXES
        and os.path.realpath(entry) != named_real
        and file_names_holdout(relative(entry, root))
    )


# --------------------------------------------------------------------------
# scorer probe
# --------------------------------------------------------------------------


def _probe_kind(value: object) -> str | None:
    """The JSON kind a gold value is probed as, or ``None`` when it cannot be.

    Gold is whatever the task's answer is: text, a structured object, a list, a
    number or a boolean. Each kind is probed with values of that same kind, so a
    scorer written for the task's answers is called the way a run would call it.
    """
    if _gold_kind(value) is not None:
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, dict):
        return "object" if value else None
    if isinstance(value, list):
        return "array" if value else None
    return None


def build_probe_payload(
    datasets: list[DatasetReport], root: Path
) -> tuple[object, object | None, object, str]:
    """Return ``(good, partial, bad, source)`` probe values.

    ``good`` and ``bad`` are two distinct gold values of the same JSON kind from
    the dataset. ``partial`` sits between them when one can be built from the
    two values alone (see ``partial_value``) and is ``None`` otherwise, so the
    partial case is skipped rather than invented. With no such pair the values
    are placeholder text and ``source`` is ``"synthetic"``: the report then
    abstains from saying the scorer separates good from bad answers for the task.

    The kind is the first one with two distinct values. ``good`` is its first
    value; ``bad`` is, among its first ``PROBE_CANDIDATES`` distinct values, the
    one that differs most from ``good`` (see ``answer_difference``).
    """
    for report in sorted(datasets, key=lambda item: -item.rows):
        raw = load_rows(root / report.file)
        if not raw.rows:
            continue
        candidates = _probe_candidates(raw.rows)
        if candidates is not None:
            good, *others = candidates
            # The first candidate that differs most from ``good``: two gold
            # values can be distinct and still the same answer to the task
            # (a case or spacing variant, numbers within a tolerance, objects
            # that differ only in a field the scorer ignores). Taking the next
            # distinct value as the known-bad answer would then read a correct
            # scorer as one that cannot tell good from bad.
            bad = max(others, key=lambda other: answer_difference(good, other))
            return good, partial_value(good, bad), bad, "dataset"
    return (
        "traigent setup audit probe value",
        "traigent setup audit probe",
        "an unrelated answer",
        "synthetic",
    )


def _probe_gold(row: dict) -> tuple[str, object] | None:
    """``(probe kind, gold value)`` of a row's first gold key, or ``None``
    when the row has no gold key or its value cannot be probed."""
    key = next((name for name in EXPECTED_KEYS if name in row), None)
    if key is None:
        return None
    value = row[key]
    kind = _probe_kind(value)
    if kind is None:
        return None
    return kind, value


def _probe_candidates(rows: list[dict]) -> list[object] | None:
    """The distinct gold values of the first kind to show two of them, at most
    ``PROBE_CANDIDATES``, in row order; ``None`` when no kind has two."""
    values: dict[str, list[object]] = {}
    chosen: str | None = None
    for row in rows:
        gold = _probe_gold(row)
        if gold is None:
            continue
        kind, value = gold
        if chosen is not None and kind != chosen:
            continue
        distinct = _add_distinct(values.setdefault(kind, []), value)
        if chosen is None and distinct >= 2:
            chosen = kind
        if chosen is not None and distinct >= PROBE_CANDIDATES:
            break
    return values[chosen] if chosen is not None else None


def _add_distinct(seen: list[object], value: object) -> int:
    """Append ``value`` unless an equal one is there; return the new count."""
    if value not in seen:
        seen.append(value)
    return len(seen)


def _same_answer(left: object, right: object) -> bool:
    """Equal, reading text without case or spacing differences."""
    if isinstance(left, str) and isinstance(right, str):
        return " ".join(left.casefold().split()) == " ".join(right.casefold().split())
    return left == right


def answer_difference(good: object, other: object) -> float:
    """How far ``other`` is from ``good``, compared within one JSON kind.

    Text counts as different only when it differs beyond case and spacing; a
    number by its distance; an object by how many of its fields differ; a list
    by how many positions differ, plus the difference in length. It ranks
    candidates for the known-bad probe and is not a score for the task.
    """
    if isinstance(good, bool) or isinstance(other, bool):
        return float(good != other)
    if isinstance(good, (int, float)) and isinstance(other, (int, float)):
        return _number_difference(good, other)
    if isinstance(good, dict) and isinstance(other, dict):
        return _object_difference(good, other)
    if isinstance(good, list) and isinstance(other, list):
        return _list_difference(good, other)
    return float(not _same_answer(good, other))


def _list_difference(good: list, other: list) -> float:
    """How many positions differ, plus the difference in length."""
    differing = sum(1 for a, b in zip(good, other) if not _same_answer(a, b))
    return float(differing + abs(len(good) - len(other)))


def _number_difference(good: int | float, other: int | float) -> float:
    """The distance between two numbers. JSON integers have no size limit; a
    distance no float can hold ranks last rather than stopping the audit."""
    try:
        distance = float(abs(good - other))
    except OverflowError:
        return 0.0
    return distance if math.isfinite(distance) else 0.0


def _object_difference(good: dict, other: dict) -> float:
    """How many fields are missing from one object or differ between them."""
    return float(
        sum(
            1
            for key in good.keys() | other.keys()
            if key not in good
            or key not in other
            or not _same_answer(good[key], other[key])
        )
    )


def partial_value(good: object, bad: object) -> object | None:
    """A value between ``good`` and ``bad``, or ``None`` when there is none.

    Text loses its last token. A list keeps its length and takes the bad
    answer's last item in place of its own; an object takes the bad answer's
    value for one key it shares with it. Both keep the rest of the good answer
    and the answer's shape, so a scorer that compares item by item or field by
    field is called on input it was written for. A number or a boolean has no
    in-between value that holds for every scorer, so none is built.
    """
    if isinstance(good, str):
        return perturb(good)
    if isinstance(good, list) and isinstance(bad, list):
        return _partial_list(good, bad)
    if isinstance(good, dict) and isinstance(bad, dict):
        return _partial_object(good, bad)
    return None


def _partial_list(good: list, bad: list) -> list | None:
    """``good`` with its last item replaced by ``bad``'s last item, unless that
    equals either answer or there is no item to take."""
    if len(good) < 2 or not bad:
        return None
    candidate = [*good[:-1], bad[-1]]
    return candidate if candidate not in (good, bad) else None


def _partial_object(good: dict, bad: dict) -> dict | None:
    """``good`` with the first shared key that differs taking ``bad``'s value,
    unless every such object equals ``bad``."""
    for key, value in good.items():
        if key in bad and bad[key] != value:
            candidate = {**good, key: bad[key]}
            if candidate != bad:
                return candidate
    return None


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
        try:
            number = float(item)
        except OverflowError:
            return None
        if not math.isfinite(number):
            return None
        out.append(number)
    return out


def _clean_error(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("error_type")
    site = value.get("error_site")
    case = value.get("case")
    cleaned: dict = {}
    # A type name the report cannot carry is dropped, not the record: the
    # failure still happened, and is then shown as "an error".
    cleaned["error_type"] = (
        kind if isinstance(kind, str) and ERROR_TYPE_RE.match(kind) else None
    )
    if site is None:
        cleaned["error_site"] = None
    elif isinstance(site, str) and ERROR_SITE_RE.match(site):
        cleaned["error_site"] = site
    else:
        cleaned["error_site"] = None
    if isinstance(case, str) and case in SCORE_CASES:
        cleaned["case"] = case
    if value.get("non_finite") is True:
        cleaned["non_finite"] = True
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
        return _tampered_result(), 0

    clean: dict = {}
    known = _copy_known_flags(payload, clean)

    if "scores" in payload:
        scores = _clean_scores(payload["scores"])
        # Scores the parent cannot hold as finite numbers are not the child's
        # honest output: the child withholds a non-finite value itself.
        if scores is None:
            return _tampered_result(), len(payload)
        clean["scores"] = scores
        known += 1

    errors = _clean_errors(payload.get("errors"))
    if errors is not None:
        clean["errors"] = errors
        known += 1

    top_fault = _clean_error(payload)
    if top_fault is not None and "error_type" in payload:
        clean["error_type"] = top_fault["error_type"]
        clean["error_site"] = top_fault["error_site"]
        known += 1

    if "ran" not in clean:
        return _tampered_result(), len(payload)
    return clean, max(0, len(payload) - known)


def _tampered_result() -> dict:
    """A fresh not-run result: callers add keys to the one they get."""
    return {"ran": False, "stage": "tampered-result"}


# The probe result's flags, in report order, each with the shape it must have.
KNOWN_FLAGS: tuple[tuple[str, Callable[[object], bool]], ...] = (
    ("ran", lambda value: isinstance(value, bool)),
    ("network_blocked", lambda value: isinstance(value, bool)),
    ("network_guard", lambda value: isinstance(value, str) and value in GUARD_STATES),
    ("stage", lambda value: isinstance(value, str) and value in PROBE_STAGES),
)


def _copy_known_flags(payload: dict, clean: dict) -> int:
    """Copy each known flag of the right shape into ``clean``; return how many."""
    known = 0
    for name, valid in KNOWN_FLAGS:
        if valid(payload.get(name)):
            clean[name] = payload[name]
            known += 1
    return known


def _clean_scores(scores: object) -> dict[str, list[float]] | None:
    """The scores as finite floats per known case, or ``None`` when any part
    of them is not."""
    converted = None
    if isinstance(scores, dict) and set(scores) <= SCORE_CASES:
        converted = {name: _numbers(value) for name, value in scores.items()}
    if converted is None or any(value is None for value in converted.values()):
        return None
    return converted


def _clean_errors(errors: object) -> list[dict] | None:
    """The cleaned error records, or ``None`` when the list is too long or any
    record is not an object."""
    if not (isinstance(errors, list) and len(errors) <= 100):
        return None
    cleaned = [_clean_error(item) for item in errors]
    if all(item is not None for item in cleaned):
        return cleaned
    return None


def validate_probe_evidence(
    payload: object, repeats: int | None = None, *, partial_probed: bool = True
) -> tuple[dict, int]:
    """Validate measurements before either tier can use them as evidence.

    The requested count is parent-owned. Older stored reports lack it, so their
    types and completeness are checked without inventing a historical count.
    Whether a partial case was sent is parent-owned too: a gold kind with no
    in-between value sends none, and then no partial score may come back.
    Error-bearing results retain their existing repair-versus-not-run reading.
    """
    if not isinstance(payload, dict) or type(payload.get("ran")) is not bool:
        raise ValueError("probe ran must be a boolean")
    if repeats is not None and (type(repeats) is not int or repeats < 1):
        raise ValueError("requested repeats must be a positive integer")
    clean, dropped = validate_probe_payload(payload)
    if payload["ran"]:
        _check_measurements(clean, repeats, partial_probed)
    return clean, dropped


def _check_measurements(clean: dict, repeats: int | None, partial_probed: bool) -> None:
    """Raise ``ValueError`` unless a run's scores cover every case and, when no
    call failed, hold the requested number of each."""
    scores = clean.get("scores")
    errors = clean.get("errors")
    if not isinstance(scores, dict) or set(scores) != SCORE_CASES or errors is None:
        raise ValueError("probe measurements are malformed")
    if errors:
        return
    good_count = len(scores["good"])
    if (good_count != repeats if repeats is not None else good_count < 1):
        raise ValueError("probe good count differs from requested repeats")
    expected_partial = 1 if partial_probed else 0
    if len(scores["partial"]) != expected_partial or len(scores["bad"]) != 1:
        raise ValueError("probe comparison cases are incomplete")


def _unique_members(pairs: list[tuple[str, object]]) -> dict:
    """Do not allow a later JSON member to erase earlier evidence."""
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate member in the probe result")
        result[name] = value
    return result


def _refuse_constant(name: str) -> float:
    raise ValueError(f"non-finite constant {name} in the probe result")


def _strict_float(text: str) -> float:
    """``1e999`` is valid JSON that decodes to inf: refused like ``Infinity``."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("non-finite number in the probe result")
    return value


def _strict_int(text: str) -> int:
    """An int too large for a float is refused while decoding, before a
    duplicated key could discard it."""
    value = int(text)
    try:
        float(value)
    except OverflowError:
        raise ValueError("unconvertible number in the probe result") from None
    return value


def _framed_lines(stdout: str) -> list[str]:
    return [
        line[len(RESULT_MARKER) :]
        for line in stdout.splitlines()
        if line.startswith(RESULT_MARKER)
    ]


def probe_environment() -> dict[str, str]:
    """The allowlisted environment for a child that may run project code.

    Only PATH, HOME, locale, timezone and temp-dir variables pass; every other
    variable, credentials included, is withheld. A scorer that needs another
    variable fails the probe and is reported by exception type and location.
    """
    values = {name: os.getenv(name) for name in CHILD_ENV_NAMES}
    return {name: value for name, value in values.items() if value is not None}


def run_scorer_probe(
    interpreter: str,
    scorer: ScorerCandidate,
    root: Path,
    payload: tuple[object, object | None, object, str],
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
            env=probe_environment(),
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
    parsed = None
    try:
        parsed = json.loads(
            framed[0],
            parse_constant=_refuse_constant,
            parse_float=_strict_float,
            parse_int=_strict_int,
            object_pairs_hook=_unique_members,
        )
        result, dropped = validate_probe_evidence(
            parsed, repeats, partial_probed=partial is not None
        )
    except ValueError:
        return {
            "ran": False,
            "stage": "tampered-result",
            "stderr_bytes": stderr_bytes,
            "framed_result_lines": 1,
            "payload_source": source,
            "dropped_keys": validate_probe_payload(parsed)[1] if isinstance(parsed, dict) else 0,
        }
    result["requested_repeats"] = repeats
    result["payload_source"] = source
    result["partial_probed"] = partial is not None
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


def _error_summary(errors: list[dict]) -> str:
    """What the failed probe calls did, by exception TYPE and location only."""
    raised = [error for error in errors if not error.get("non_finite")]
    non_finite = len(errors) - len(raised)
    parts = []
    if raised:
        faults = ", ".join(sorted({_fault_phrase(error) for error in raised}))
        parts.append(f"{len(raised)} probe call(s) raised {faults}")
    if non_finite:
        parts.append(
            f"{non_finite} probe call(s) returned a value that is not a finite number"
        )
    return "; ".join(parts)


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
    good, partial, bad, errors = _score_lists(result)
    unusable = _unusable_scores(result, good, partial, bad, errors)
    if unusable is not None:
        return unusable
    return _ran_metrics(good, partial, bad, errors)


def _score_lists(
    result: dict,
) -> tuple[list[float], list[float], list[float], list[dict]]:
    """``(good, partial, bad, errors)`` of a probe that ran, each a new list."""
    scores = result.get("scores") or {}
    good = list(scores.get("good") or [])
    partial = list(scores.get("partial") or [])
    bad = list(scores.get("bad") or [])
    errors = list(result.get("errors") or [])
    return good, partial, bad, errors


def _scores_complete(
    result: dict, good: list[float], partial: list[float], bad: list[float]
) -> bool:
    """Every case the probe sent has its score and no result key was dropped.

    The child records an error for every case it could not score, so missing
    scores with no error to account for them are not its honest output. A key
    the parent dropped may have been that error (an older parent dropped error
    records it could not name), so the evidence is incomplete then too.
    A gold kind with no in-between value sends no partial case (the parent
    records that as ``partial_probed: false``); every other probe sends one.
    """
    expected_partial = 0 if result.get("partial_probed") is False else 1
    return (
        bool(good)
        and len(partial) == expected_partial
        and len(bad) == 1
        and not result.get("dropped_keys")
    )


def _unusable_scores(
    result: dict,
    good: list[float],
    partial: list[float],
    bad: list[float],
    errors: list[dict],
) -> dict | None:
    """The ``failed`` reading of a probe that ran without usable scores, or
    ``None`` when its scores can be read."""
    if not errors and not _scores_complete(result, good, partial, bad):
        return {
            "verdict": "failed",
            "stage": "tampered-result",
            "sentence": PROBE_FAILURE_SENTENCE["tampered-result"],
        }
    if _no_score_at_all(good, partial, bad, errors):
        fault = _fault_phrase(errors[0] if errors else {})
        return {
            "verdict": "failed",
            "stage": "no-scores",
            "sentence": PROBE_FAILURE_SENTENCE["no-scores"].format(fault=fault),
        }
    return None


def _no_score_at_all(
    good: list[float], partial: list[float], bad: list[float], errors: list[dict]
) -> bool:
    """No case scored, and no call returned a non-finite value either."""
    return not (good or partial or bad) and not any(
        error.get("non_finite") for error in errors
    )


def _ran_metrics(
    good: list[float], partial: list[float], bad: list[float], errors: list[dict]
) -> dict:
    """The ``ran`` reading: repeatability, ordering, finiteness, readiness."""
    ordered = bool(good and bad) and good[0] > bad[0]
    if partial:
        ordered = ordered and good[0] >= partial[0] >= bad[0]
    # A report written before the parent refused non-finite scores can still
    # hold them, and inf > 0 would otherwise read as ordered.
    finite = all(math.isfinite(score) for score in good + partial + bad)
    stable = len(set(good)) == 1
    return {
        "verdict": "ran",
        "good": good,
        "partial": partial,
        "bad": bad,
        "repeats": len(good),
        "distinct": len(set(good)),
        "stable": stable,
        "ordered": ordered,
        "errors": errors,
        "finite": finite,
        # The one readiness rule: the card, the next step and Tier 2 all read it.
        "ready": finite and stable and ordered and not errors,
    }


# A call that raised while others scored may have failed on the probe's own
# conditions, so those are named before the scorer, without claiming which one
# it was. Only the return types are a fixed fact of ``call_scorer``; how the
# probe process runs is documented in one place, the skill's Safety section.
PROBE_CONDITIONS_REMEDY = (
    "rule out the probe's own conditions first (it reads a return value only as "
    "an int, float, bool or a dict with a numeric score, value or result key, "
    "and runs the scorer in a separate restricted process described under "
    "Safety in the traigent-setup-audit skill), then fix the scorer"
)

# The probe could not draw two distinct gold values of one kind from a dataset,
# so it scored placeholder text. That still measures repeatability; it does not
# show that the scorer tells a good answer for THIS task from a bad one.
SYNTHETIC_PROBE_NOTE = (
    "no dataset gave two distinct usable gold values of the same kind, so the "
    "probe scored placeholder text: whether the scorer separates a good answer "
    "for this task from a bad one was not tested"
)
SYNTHETIC_MEANING = (
    "The scorer returns the same number for the same pair, but it was probed "
    "with placeholder text rather than this task's answers, so this audit makes "
    "no claim that it separates a good answer from a bad one."
)

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

    errors = metrics["errors"]
    synthetic = result.get("payload_source") == "synthetic"
    order = _order_note(metrics, synthetic)
    evidence = [
        _repeat_line(metrics),
        f"{_scored_cases(result, metrics)}{order}",
    ]
    if synthetic:
        evidence.append(SYNTHETIC_PROBE_NOTE)
    # A repeat count cut short by an error is not a repeatability reading.
    if not metrics["good"] or any(error.get("case") == "good" for error in errors):
        evidence.pop(0)
    if errors:
        evidence.append(_error_summary(errors))
    return ("ok" if metrics["ready"] else "attention"), evidence


def _order_note(metrics: dict, synthetic: bool) -> str:
    """Whether the probe values came out in the expected order; empty when a
    call failed or a score is not finite."""
    order = ""
    if not metrics["errors"] and metrics["finite"]:
        order = (
            " (ordered as expected)"
            if metrics["ordered"]
            else " (not ordered as expected)"
        )
    if synthetic and order:
        order += " on placeholder text, not on this task's answers"
    return order


def _scored_cases(result: dict, metrics: dict) -> str:
    """The probe cases and their first scores, without the partial case when
    none was sent."""
    if result.get("partial_probed") is False:
        cases = "gold self-match / contrast candidate probes scored "
        scored = f"{_show(metrics['good'])} / {_show(metrics['bad'])}"
    else:
        cases = "gold self-match / partial / contrast candidate probes scored "
        scored = (
            f"{_show(metrics['good'])} / {_show(metrics['partial'])} / "
            f"{_show(metrics['bad'])}"
        )
    return f"{cases}{scored}"


def _repeat_line(metrics: dict) -> str:
    return f"repeat-scoring the same pair {metrics['repeats']} times returned " + (
        "one identical score"
        if metrics["stable"]
        else f"{metrics['distinct']} different scores"
    )


def probe_symptom(metrics: dict) -> str:
    """Why a probe that ran is not reliable, in the probe's own numbers.

    Only meaningful for a ``probe_metrics`` result with verdict ``ran`` that is
    not ``ready``; shared by the next step and the Tier 2 cards. Failed calls
    are stated as observed, without a claim about what caused them.
    """
    errors = metrics["errors"]
    if errors:
        scored = metrics["good"] or metrics["partial"] or metrics["bad"]
        return (
            "scored some probe calls and " if scored else "produced no finite score: "
        ) + _error_summary(errors)
    if not metrics["finite"]:
        return "returned a score that is not a finite number"
    if not metrics["stable"]:
        return (
            f"returned {metrics['distinct']} different scores for the same "
            f"pair across {metrics['repeats']} repeats"
        )
    cases = f"gold self-match {_show(metrics['good'])}"
    if metrics["partial"]:
        cases += f", partial {_show(metrics['partial'])}"
    cases += f", contrast candidate {_show(metrics['bad'])}"
    return f"did not produce the expected probe ordering ({cases})"


def probe_remedy(metrics: dict) -> str:
    """What to do about the symptom ``probe_symptom`` names.

    A stable scorer can tie equivalent task answers. Structural differences
    alone do not establish that the contrast candidate is actually incorrect.
    """
    errors = metrics["errors"]
    if any(not error.get("non_finite") for error in errors):
        return PROBE_CONDITIONS_REMEDY
    if errors or not metrics["finite"]:
        return "make it return a finite number"
    if not metrics["stable"]:
        return "make it repeatable"
    return (
        "verify the contrast with a task-verified incorrect answer and any partial "
        "probe's expected position; if these task-verified probes still fail the "
        "expected ordering, fix what it measures"
    )


# The one consequence that judges the scorer itself: every call scored, finitely.
SCORER_MEASURED = "a configuration comparison would be measuring the scorer"


def probe_consequence(metrics: dict) -> str:
    """What the ``probe_symptom`` finding means for a configuration comparison."""
    if metrics["errors"] or not metrics["finite"]:
        return (
            "it is not established that a run would get a usable score for every row"
        )
    if metrics["stable"]:
        return (
            "the candidate may be equivalent for this task; task-quality "
            "separation is not established by this probe"
        )
    return SCORER_MEASURED


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


def _pyvenv_cfg(venv: Path) -> dict[str, str]:
    """`key = value` lines of a venv's pyvenv.cfg; empty when it cannot be read."""
    values: dict[str, str] = {}
    try:
        text = (venv / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip().lower()] = value.strip()
    return values


def venv_site_paths(venv: Path) -> tuple[list[str], bool]:
    """Every directory the venv's interpreter would import an installed package
    from, found by path: ``(paths, reads_base)``.

    With ``include-system-site-packages = true`` that interpreter also imports
    from the user site (searched first) and the base installation named by
    ``home``; those are read too, in the same order. Nothing is executed:
    ``home`` is written by the project, so its interpreter is not started either.
    """
    own = sorted(str(path) for path in venv.glob("lib/python3*/site-packages"))
    cfg = _pyvenv_cfg(venv)
    if cfg.get("include-system-site-packages", "false").lower() != "true":
        return own, False
    xy = _venv_major_minor(cfg)
    user_sites = _user_site_paths(xy)
    base = _base_site_paths(cfg.get("home"), xy)
    paths = [str(path) for path in user_sites] + own + [str(path) for path in base]
    return paths, True


def _venv_major_minor(cfg: dict[str, str]) -> str:
    """``X.Y`` of the venv's Python, from ``version`` or ``version_info``; empty
    when neither names one."""
    version = cfg.get("version") or cfg.get("version_info") or ""
    parts = version.split(".")
    return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else ""


def _user_site_paths(xy: str) -> list[Path]:
    """The user site directories for Python ``xy``; with no version, every
    ``python3*`` user site that exists."""
    user = Path.home()
    if xy:
        return [
            user / ".local" / "lib" / f"python{xy}" / "site-packages",
            user / "Library" / "Python" / xy / "lib" / "python" / "site-packages",
        ]
    return sorted((user / ".local" / "lib").glob("python3*/site-packages"))


def _base_site_paths(home: str | None, xy: str) -> list[Path]:
    """The base installation's package directories that exist, found under the
    parent of the venv's ``home``; none without a ``home``."""
    base: list[Path] = []
    if not home:
        return base
    prefix = Path(home).parent
    lib = f"python{xy}" if xy else "python3*"
    for pattern in (
        f"lib/{lib}/site-packages",
        f"lib/{lib}/dist-packages",
        "lib/python3/dist-packages",
        f"local/lib/{lib}/dist-packages",
    ):
        base.extend(sorted(prefix.glob(pattern)))
    return base


def read_sdk_version(interpreter: str) -> dict:
    """Read the installed SDK version from package metadata; start nothing.

    A project venv's interpreter is never executed here: starting it runs the
    venv's site hooks, which are project code, outside the probe sandbox. Its
    site-packages is read by path instead. (`python -I -S` is no way round
    that: without `site` the venv's site-packages is not on the path at all.)
    Only the scorer probe starts the project interpreter.
    """
    reads_base = False
    try:
        if interpreter == sys.executable:
            found = md.distributions(name="traigent")
        else:
            paths, reads_base = venv_site_paths(Path(interpreter).parent.parent)
            found = md.distributions(name="traigent", path=paths)
        dist = next(iter(found), None)
        version = dist.version if dist is not None else None
    except (OSError, ValueError) as exc:
        return {
            "interpreter": interpreter,
            "traigent_version": None,
            "error_type": type(exc).__name__,
        }
    return {
        "interpreter": interpreter,
        "traigent_version": version,
        "read_base_installation": reads_base,
    }


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
        names = _declared_key_names(path)
        if names:
            in_files[relative(path, root)] = names
    return {
        "env_files": [relative(path, root) for path in env_files],
        "names_set_in_environment": in_environment,
        "names_declared_in_env_files": in_files,
    }


def _declared_key_names(path: Path) -> list[str] | None:
    """The key names an env file assigns (``NAME=`` or ``export NAME=``), in
    ``KEY_ENV_NAMES`` order; ``None`` when the file cannot be read."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    return [
        name
        for name in KEY_ENV_NAMES
        if re.search(rf"(?m)^\s*(export\s+)?{re.escape(name)}\s*=", text)
    ]


def env_file_ignored(root: Path) -> str:
    if not (root / ".env").exists():
        return "no .env file"
    # A project's git config can name commands git runs on its behalf
    # (`core.fsmonitor`, hooks): switch those off, and give git the same
    # allowlisted environment as the probe, so no project-chosen code runs here.
    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-C",
        str(root),
        "check-ignore",
        "-q",
        ".env",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=15,
            check=False,
            env=probe_environment(),
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


def entry_point_records(entry_points: list[EntryPoint]) -> list[dict]:
    """The report's `entry_points` records."""
    return [
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
        for entry in entry_points
    ]


def _names(knobs: list[dict]) -> str:
    shown = [f"`{knob['name']}`" for knob in knobs[:3]]
    text = ", ".join(shown)
    if len(knobs) > 3:
        text += f", and {len(knobs) - 3} more"
    return text


def knob_wiring(entry_points: list[dict]) -> dict:
    """One reading of the declared knobs, shared by the Agent card, the next
    step and Tier 2. It reads the report's own `entry_points` records, so Tier 2
    applies the same rule to a stored report.

    The verdict is the first that matches, scanning the entries in order for
    each: ``none``, ``blank``, ``all-unread``, ``partly-unread``,
    ``not-inventoried``, ``possibly-read``, ``read``. Malformed input raises
    ``TypeError``, ``AttributeError``, ``KeyError`` or ``ValueError``.
    """
    all_knobs = [knob for entry in entry_points for knob in entry["knobs"]]
    if any(
        not isinstance(knob["status"], str)
        or knob["status"] not in (KNOB_READ, KNOB_UNREAD, KNOB_MAYBE)
        for knob in all_knobs
    ):
        raise ValueError("stored knob status is not a supported reading")
    knob_count = len(all_knobs)
    read_count = sum(1 for knob in all_knobs if knob["status"] == KNOB_READ)
    verdict, entry, knobs = _wiring_verdict(entry_points)
    return {
        "verdict": verdict,
        "entry": entry,
        "knobs": knobs,
        "knob_count": knob_count,
        "read_count": read_count,
        "summary": _wiring_summary(verdict, entry, knobs),
    }


def _knobs_with_status(entry: dict, status: str) -> list[dict]:
    return [knob for knob in entry["knobs"] if knob["status"] == status]


# The knob wiring ladder after `none`, in order: (verdict, which entry it
# matches, which of that entry's knobs it names). The first rung with a
# matching entry decides; with none, the verdict is `read`.
WIRING_LADDER: tuple[
    tuple[str, Callable[[dict], object], Callable[[dict], list[dict]]], ...
] = (
    (
        "blank",
        lambda e: not e["knobs"] and not e["config_space_note"],
        lambda e: [],
    ),
    (
        "all-unread",
        lambda e: e["knobs"] and all(knob["status"] == KNOB_UNREAD for knob in e["knobs"]),
        lambda e: list(e["knobs"]),
    ),
    (
        "partly-unread",
        lambda e: _knobs_with_status(e, KNOB_UNREAD),
        lambda e: _knobs_with_status(e, KNOB_UNREAD),
    ),
    (
        "not-inventoried",
        lambda e: e["config_space_note"],
        lambda e: list(e["knobs"]),
    ),
    (
        "possibly-read",
        lambda e: _knobs_with_status(e, KNOB_MAYBE),
        lambda e: _knobs_with_status(e, KNOB_MAYBE),
    ),
)


def _wiring_verdict(entry_points: list[dict]) -> tuple[str, dict | None, list[dict]]:
    """``(verdict, entry it names, knobs it names)`` by the wiring ladder."""
    if not entry_points:
        return "none", None, []
    for verdict, matches, named_knobs in WIRING_LADDER:
        found = next((entry for entry in entry_points if matches(entry)), None)
        if found is not None:
            return verdict, found, named_knobs(found)
    return "read", None, []


def _wiring_summary(verdict: str, entry: dict | None, knobs: list[dict]) -> str:
    """The one-line reading of a verdict that names an entry; empty otherwise."""
    if entry is None:
        return ""
    where = f"`{entry['function']}` at {entry['file']}:{entry['line']}"
    declared = len(entry["knobs"])
    if verdict == "blank":
        return f"{where} declares 0 knobs"
    if verdict == "all-unread":
        return f"{where} declares {declared} knob(s) and the body reads none of them"
    if verdict == "partly-unread":
        return (
            f"{where} declares {declared} knob(s) and the body never reads "
            f"{len(knobs)} of them ({_names(knobs)})"
        )
    if verdict == "not-inventoried":
        return f"the configuration space of {where} was not inventoried"
    if verdict == "possibly-read":
        return (
            f"{len(knobs)} knob(s) of {where} ({_names(knobs)}) are read "
            "through a mapping the parser cannot follow"
        )
    return ""


CONFIG_SPACE_SKILLS = ["traigent-optimize-config-space"]


def knob_step(wiring: dict) -> dict | None:
    """The next step a knob reading calls for, or ``None`` when it calls for
    none (``none``, ``read`` or an unknown verdict). ``b`` stops the run before
    anything else; ``h`` waits behind the scorer and dataset steps."""
    verdict = wiring.get("verdict")
    summary = wiring.get("summary", "")
    if verdict == "blank":
        branch = "b"
        line = (
            f"{summary}, so every trial would evaluate the same configuration — "
            "define a real configuration space with `traigent-optimize-config-space`."
        )
    elif verdict == "all-unread":
        branch = "b"
        line = (
            f"{summary}, so varying them cannot change the output — rework the "
            "configuration space with `traigent-optimize-config-space`."
        )
    elif verdict == "partly-unread":
        branch = "h"
        line = (
            f"{summary}, so every trial that varies them is spend with no effect — "
            "wire or remove them with `traigent-optimize-config-space`."
        )
    elif verdict == "not-inventoried":
        entry = wiring["entry"]
        branch = "h"
        line = (
            f"The configuration space of `{entry['function']}` at "
            f"{entry['file']}:{entry['line']} was not inventoried, so whether its "
            "knobs reach the function body is unconfirmed — confirm by hand, or "
            "declare the space as a dict literal so the next audit can read it, "
            "with `traigent-optimize-config-space`."
        )
    elif verdict == "possibly-read":
        branch = "h"
        line = (
            f"{summary}, so whether each one reaches the body is unconfirmed — "
            "confirm by hand that each one does, with "
            "`traigent-optimize-config-space`, before a run."
        )
    else:
        return None
    return {"branch": branch, "skills": list(CONFIG_SPACE_SKILLS), "line": line}


def inventory_gap(inventory: PythonInventory) -> str:
    """Why the Python inventory may be incomplete, or ``""``."""
    if inventory.files_unparsed:
        return (
            f"{len(inventory.files_unparsed)} Python file(s) could not be parsed "
            f"by this audit's Python {sys.version_info[0]}.{sys.version_info[1]} "
            f"(first: {inventory.files_unparsed[0]})"
        )
    if inventory.files_total > MAX_PYTHON_FILES:
        return (
            f"only the first {MAX_PYTHON_FILES} of {inventory.files_total} Python "
            "file(s) were inventoried"
        )
    return ""


def _capitalised(text: str) -> str:
    return text[:1].upper() + text[1:]


def agent_area(inventory: PythonInventory) -> dict:
    evidence: list[str] = []
    evidence.extend(inventory.notes)
    if not inventory.entry_points:
        evidence.extend(_no_entry_point_lines(inventory))
        meaning = (
            "Nothing is instrumented yet, so there is no search space to optimize; "
            "`traigent-setup-decorator` is where a first decorated function comes from."
        )
        return {"status": "not-found", "evidence": evidence, "meaning": meaning}
    knobs = [knob for entry in inventory.entry_points for knob in entry.knobs]
    evidence.extend(_entry_point_lines(inventory.entry_points))
    evidence.extend(_knob_lines(knobs))
    evidence.extend(_blank_entry_lines(inventory.entry_points))
    # One reading, shared with the next step and Tier 2: the card cannot
    # read `ok` over a knob or inventory fact the ladder would act on.
    verdict = knob_wiring(entry_point_records(inventory.entry_points))["verdict"]
    gap = inventory_gap(inventory)
    status = "ok" if verdict == "read" and not gap else "attention"
    maybe_count = sum(1 for knob in knobs if knob.status == KNOB_MAYBE)
    meaning = _agent_meaning(verdict, gap, maybe_count)
    return {"status": status, "evidence": evidence, "meaning": meaning}


def _no_entry_point_lines(inventory: PythonInventory) -> list[str]:
    """What was searched for when no decorated function was found."""
    lines = [
        f"searched for `@traigent.optimize` in {inventory.files_scanned} "
        "Python file(s), found none"
    ]
    if inventory.llm_call_sites:
        lines.extend(
            f"`{site['function']}` at {site['file']}:{site['line']} sits in a "
            f"module importing {', '.join(site['providers'])}"
            for site in inventory.llm_call_sites[:5]
        )
    else:
        lines.append(
            f"searched for provider imports ({', '.join(sorted(PROVIDER_MODULES)[:6])}, "
            f"and others) in {inventory.files_scanned} Python file(s), found none"
        )
    return lines


def _entry_point_lines(entry_points: list[EntryPoint]) -> list[str]:
    """One line per decorated function, each followed by its space note."""
    lines: list[str] = []
    for entry in entry_points:
        lines.append(
            f"`@traigent.optimize` on `{entry.function}` at "
            f"{entry.file}:{entry.line}, {len(entry.knobs)} declared knob(s)"
        )
        if entry.config_space_note:
            lines.append(entry.config_space_note)
    return lines


def _knob_lines(knobs: list[Knob]) -> list[str]:
    """The unread knobs, then the possibly-read ones, then those whose values
    could not be read."""
    lines = [
        f"knob `{knob.name}` is declared at {knob.file}:{knob.line} and the "
        "decorated function body never reads it"
        for knob in knobs
        if knob.status == KNOB_UNREAD
    ]
    lines += [
        f"knob `{knob.name}` at {knob.file}:{knob.line} is read through a "
        "mapping the parser cannot follow, so whether it reaches the body "
        "is unconfirmed"
        for knob in knobs
        if knob.status == KNOB_MAYBE
    ]
    lines += [
        f"knob `{knob.name}` at {knob.file}:{knob.line} has values the audit "
        "could not read, so they are not listed"
        for knob in knobs
        if not knob.values_readable
    ]
    return lines


def _blank_entry_lines(entry_points: list[EntryPoint]) -> list[str]:
    """One line per decorated function that declares no configuration space."""
    return [
        f"`{entry.function}` at {entry.file}:{entry.line} declares no "
        "configuration space, so there is nothing to search"
        for entry in entry_points
        if not entry.knobs and not entry.config_space_note
    ]


def _agent_meaning(verdict: str, gap: str, maybe_count: int) -> str:
    """What the knob wiring verdict, or an inventory gap, means for a search."""
    if verdict in ("all-unread", "partly-unread"):
        return (
            "A knob the function never reads cannot change the output, so every "
            "trial that varies it is spend with no effect."
        )
    if verdict == "blank":
        return (
            "A decorated function with no configuration space gives the "
            "optimizer one point to evaluate, so there is nothing to compare."
        )
    if verdict == "not-inventoried":
        return (
            "The configuration space was not readable statically, so this audit "
            "cannot say whether its knobs reach the function body — check those "
            "by hand."
        )
    if verdict == "possibly-read":
        return (
            f"{maybe_count} knob(s) are read through a mapping the parser cannot "
            "follow — confirm by hand that each one reaches the body."
        )
    if gap:
        return (
            f"{_capitalised(gap)}, so the entry points and knobs listed here may "
            "be incomplete — this audit cannot vouch for code it did not read."
        )
    return (
        "Every declared knob is read directly by the function body, so a "
        "search over them can change the output."
    )


def dataset_findings(
    reports: list[DatasetReport], notes: list[str], skipped_files: list[str]
) -> list[str]:
    """Every dataset fact that keeps the Dataset area from `ok`, in the order
    the card and the next step name them: report findings, then scan notes,
    then files that could not be read."""
    return [
        *(f"{report.file}: {finding}" for report in reports for finding in report.findings),
        *notes,
        *skipped_files,
    ]


def dataset_area(
    reports: list[DatasetReport],
    candidates: int,
    notes: list[str],
    skipped_files: list[str],
) -> dict:
    skip_lines = [f"{item} — not analysed" for item in skipped_files]
    if not reports:
        return _no_dataset_area(candidates, notes, skipped_files, skip_lines)
    evidence: list[str] = list(notes) + skip_lines
    shown = reports[:MAX_DATASETS_IN_CARD]
    for report in shown:
        evidence.extend(_dataset_report_lines(report))
    if len(reports) > len(shown):
        evidence.append(
            f"{len(reports) - len(shown)} further dataset file(s) are in the JSON "
            "report and not printed here"
        )
    status = "attention" if dataset_findings(reports, notes, skipped_files) else "ok"
    meaning = (
        "Row shortfalls, duplicates, a missing holdout slice and anything the audit "
        "could not read all widen the error bars on a measured score, so a small "
        "movement between configurations may be sampling, not improvement."
        if status == "attention"
        else "Row counts, gold coverage and a disjoint holdout slice are all within "
        "the documented minimums, so a measured movement has something to rest on."
    )
    return {"status": status, "evidence": evidence, "meaning": meaning}


def _no_dataset_area(
    candidates: int, notes: list[str], skipped_files: list[str], skip_lines: list[str]
) -> dict:
    """The Dataset area when no file was read as a dataset."""
    if skipped_files:
        return {
            "status": "attention",
            "evidence": [
                f"searched {candidates} JSONL/JSON/CSV file(s) for rows carrying an "
                f"input-like key; {len(skipped_files)} could not be read, so whether "
                "one of them is the dataset is unconfirmed",
                *notes,
                *skip_lines,
            ],
            "meaning": (
                "A dataset file this audit could not read cannot be judged, so "
                "nothing confirmed is there to score a configuration against yet; "
                "`traigent-dataset-curate` covers the file formats."
            ),
        }
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


def _dataset_report_lines(report: DatasetReport) -> list[str]:
    """The card lines for one dataset file: its shape, notes, findings and the
    first missing-gold, duplicate and near-duplicate rows."""
    splits = ", ".join(f"{k}={v}" for k, v in report.split_counts.items())
    lines = [
        f"{report.file}: {report.rows} row(s), "
        f"gold key(s) {', '.join(report.expected_key_counts) or 'none'}, "
        f"split marker(s) {splits or 'none'}"
    ]
    lines.extend(f"{report.file}: {note}" for note in report.notes)
    lines.extend(f"{report.file}: {finding}" for finding in report.findings)
    if report.missing_expected:
        lines.append(
            f"{report.file}: first row indexes with no usable gold value: "
            f"{report.missing_expected[:5]}"
        )
    if report.exact_duplicate_groups:
        lines.append(
            f"{report.file}: first duplicate row-index group: "
            f"{report.exact_duplicate_groups[0]}"
        )
    if report.near_duplicate_pairs:
        lines.append(
            f"{report.file}: first near-duplicate row-index pair: "
            f"{report.near_duplicate_pairs[0]}"
        )
    return lines


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


def _handles(items: Sequence[ScorerCandidate | SkippedScorer], limit: int = 3) -> str:
    shown = [f"{item.file}:{item.line}" for item in items[:limit]]
    if len(items) > limit:
        shown.append(f"and {len(items) - limit} more")
    return ", ".join(shown)


def not_run_lines(candidates: Iterable[ScorerCandidate]) -> list[str]:
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
    evidence = _scorer_listing(inventory)
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
    synthetic = probe.get("payload_source") == "synthetic"
    status = "ok" if probe_status == "ok" and not synthetic else "attention"
    meaning = _probe_meaning(probe_status, synthetic, probe)
    return {"status": status, "evidence": evidence, "meaning": meaning}


def _scorer_listing(inventory: PythonInventory) -> list[str]:
    """The scorers found (up to the card's limit), the skipped candidates, and
    one line per reason the non-deterministic ones were not run."""
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
    return evidence


def _probe_meaning(probe_status: str, synthetic: bool, probe: dict) -> str:
    """What a probe that was run means for a configuration comparison."""
    if probe_status == "blocked":
        return (
            "A scorer that reaches the network is not a local deterministic scorer; "
            "its score depends on a service this audit will not call."
        )
    if probe_status == "failed":
        return UNMEASURED_MEANING
    if probe_status == "ok" and synthetic:
        return SYNTHETIC_MEANING
    if probe_status == "ok":
        return (
            "The scorer returns the same number for the same pair and ranks the "
            "gold self-match above the contrast candidate. This shows repeatability "
            "and separation of the tested pair, not correctness for every task answer."
        )
    metrics = probe_metrics(probe)
    if metrics["errors"]:
        return (
            "Not every probe call produced a finite score, so whether a run would "
            "get a usable score for every row is not established."
        )
    if not metrics["stable"]:
        return (
            "A scorer that returns different numbers for the same pair makes a "
            "configuration comparison unreliable: the movement you measure may be "
            "the scorer moving."
        )
    return (
        "Repeated self-match scores are identical, but the probe values "
        "do not have the expected ordering. The contrast candidate may be "
        "equivalent for this task, so verify an actually incorrect answer "
        "before concluding that the scorer needs fixing."
    )


def setup_area(sdk: dict, keys: dict, ignored: str, model_ids: list[str]) -> dict:
    version = sdk.get("traigent_version")
    evidence = [_sdk_line(sdk), *_key_lines(keys), f".env git status: {ignored}"]
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


def _sdk_line(sdk: dict) -> str:
    """Where the SDK is installed, or why it reads as not installed."""
    version = sdk.get("traigent_version")
    if version:
        return f"traigent {version} is installed in {sdk['interpreter']}"
    return (
        f"traigent is not installed for {sdk['interpreter']}"
        + (f" ({sdk['error_type']})" if sdk.get("error_type") else "")
        + (
            " — read by path from its own site-packages, the user site and "
            "the base installation it includes"
            if sdk.get("read_base_installation")
            else ""
        )
    )


def _key_lines(keys: dict) -> list[str]:
    """The key names set in the environment, then those each env file declares."""
    if keys["names_set_in_environment"]:
        lines = [
            "set in this environment: "
            + ", ".join(keys["names_set_in_environment"])
            + " (name only; the audit reads no value)"
        ]
    else:
        lines = [
            f"searched the environment for {len(KEY_ENV_NAMES)} known key names, "
            "found none set"
        ]
    lines.extend(
        f"{env_file} declares {', '.join(names)} (name only)"
        for env_file, names in sorted(keys["names_declared_in_env_files"].items())
    )
    return lines


STOP_LINE = (
    "Stopping after this free audit is a valid choice; nothing here has left "
    "your machine."
)


def _no_entry_point_step(inventory: PythonInventory) -> dict:
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


def _scorer_step(
    inventory: PythonInventory, metrics: dict, probed: ScorerCandidate | None
) -> dict | None:
    """Branch ``c`` (no scorer), ``d`` (a probe that ran and is not ready) or
    ``e`` (no probe ran), or ``None`` when the scorer is ready."""
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

    if metrics["verdict"] == "ran" and not metrics["ready"]:
        symptom = probe_symptom(metrics)
        remedy = probe_remedy(metrics)
        return {
            "branch": "d",
            "skills": ["traigent-eval-build", "traigent-eval-audit"],
            "line": (
                f"`{probed.function}` at {probed.file}:{probed.line} {symptom}, so "
                f"{probe_consequence(metrics)} — {remedy} with `traigent-eval-build`, "
                "then assess it with `traigent-eval-audit`."
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
    return None


def _unread_dataset_step(
    reports: list[DatasetReport],
    skipped_files: list[str] | tuple[str, ...],
    dataset_notes: list[str] | tuple[str, ...],
    dataset_named: bool,
) -> dict | None:
    """A file that could not be read is named, never reported as absent.

    Beside analysed rows it outranks the rest only when the user named the
    dataset (then it is the named file's holdout sibling); in discovery it
    waits for the catch-all `_dataset_fact_step`."""
    unread = list(skipped_files) if (dataset_named or not reports) else []
    if not unread and (reports or not dataset_notes):
        return None
    if unread and not reports:
        line = (
            f"{unread[0]}, so no evaluation dataset could be analysed and there "
            "is nothing to score a configuration against yet — repair the file, "
            "or point --dataset at a readable one; `traigent-dataset-curate` "
            "covers the format."
        )
    elif unread:
        line = (
            f"{unread[0]}, so the slice it holds was not analysed and this "
            "dataset's readiness is unconfirmed — repair it with "
            "`traigent-dataset-curate`, then re-run this audit."
        )
    else:
        line = (
            f"{dataset_notes[0]}, and none of the files read is a dataset — "
            "point --dataset at your evaluation file, or build one with "
            "`traigent-dataset-curate`."
        )
    return {"branch": "f", "skills": ["traigent-dataset-curate"], "line": line}


def _no_dataset_step(reports: list[DatasetReport]) -> dict | None:
    if reports:
        return None
    return {
        "branch": "f",
        "skills": ["traigent-dataset-curate"],
        "line": (
            "No evaluation dataset was found, so there is nothing to score a "
            "configuration against — build a first tuning slice and a holdout "
            "slice with `traigent-dataset-curate`."
        ),
    }


def _unloadable_dataset_step(reports: list[DatasetReport]) -> dict | None:
    """A dataset the SDK cannot load stops the first run outright, so it
    outranks a row shortfall."""
    unloadable = [report for report in reports if report.rows_without_sdk_input]
    if not unloadable:
        return None
    worst = unloadable[0]
    return {
        "branch": "f",
        "skills": ["traigent-dataset-curate"],
        "line": (
            f"{worst.file} has {worst.rows_without_sdk_input} row(s) with no "
            "`input`/`input_data` key, so `eval_dataset` will refuse to load "
            "it — rename or add the key with `traigent-dataset-curate`."
        ),
    }


def _missing_gold_step(reports: list[DatasetReport]) -> dict | None:
    """A row with no usable gold can never score correct against gold, so
    every measured score is capped below what the agent really does."""
    gold = [report for report in reports if report.missing_gold_counts]
    if not gold:
        return None
    worst = max(gold, key=lambda report: sum(report.missing_gold_counts.values()))
    detail = ", ".join(
        f"{worst.missing_gold_counts[kind]} {label}"
        for kind, label in GOLD_KIND_LABEL.items()
        if worst.missing_gold_counts.get(kind)
    )
    return {
        "branch": "f",
        "skills": ["traigent-dataset-curate"],
        "line": (
            f"{worst.file} has {sum(worst.missing_gold_counts.values())} row(s) "
            f"with no usable gold value ({detail}), so a scorer that compares "
            "against gold cannot score those rows correct and every measured "
            "score is capped — fill or drop them with `traigent-dataset-curate`."
        ),
    }


def _overlap_count(report: DatasetReport) -> int:
    return report.holdout_overlap_total or len(report.holdout_overlap)


def _holdout_overlap_step(reports: list[DatasetReport]) -> dict | None:
    """A holdout that shares rows with the searched slice re-measures what the
    search already saw, so its score is not a held-out score."""
    overlapping = [report for report in reports if report.holdout_overlap]
    if not overlapping:
        return None
    worst = max(overlapping, key=_overlap_count)
    return {
        "branch": "f",
        "skills": ["traigent-dataset-curate"],
        "line": (
            f"{worst.file} has {_overlap_count(worst)} row(s) that appear in both "
            "the holdout slice and another slice, so a holdout score would partly "
            "re-measure rows the search already saw — make the slices disjoint "
            "with `traigent-dataset-curate`."
        ),
    }


def _is_short(report: DatasetReport) -> bool:
    """Under a row minimum. A file that is itself the holdout slice (declared
    by name) has no tuning rows to judge: only the holdout minimum applies."""
    return (
        not report.holdout_by_name and report.rows < MIN_TUNING
    ) or report.holdout_rows < MIN_HOLDOUT


def _short_dataset_line(worst: DatasetReport) -> str:
    if worst.holdout_by_name:
        return (
            f"{worst.file} is a {worst.rows}-row holdout slice declared by "
            f"file name, under the {MIN_HOLDOUT}-row holdout minimum, so a "
            "small score movement would not be resolvable — grow it with "
            "`traigent-dataset-curate`."
        )
    # Name only the minimum(s) actually missed.
    missed = []
    if worst.rows < MIN_TUNING:
        missed.append(f"the {MIN_TUNING}-row tuning minimum")
    if worst.holdout_rows < MIN_HOLDOUT:
        missed.append(f"the {MIN_HOLDOUT}-row holdout minimum")
    return (
        f"{worst.file} has {worst.rows} row(s) and a {worst.holdout_rows}-row "
        f"holdout slice, under {' and '.join(missed)}, so a small score "
        "movement would not be resolvable — grow and split it with "
        "`traigent-dataset-curate`."
    )


def _short_dataset_step(reports: list[DatasetReport]) -> dict | None:
    short = [report for report in reports if _is_short(report)]
    if not short:
        return None
    tuning_short = [r for r in short if not r.holdout_by_name]
    worst = min(tuning_short or short, key=lambda report: report.rows)
    return {
        "branch": "f",
        "skills": ["traigent-dataset-curate"],
        "line": _short_dataset_line(worst),
    }


def _dataset_step(
    reports: list[DatasetReport],
    skipped_files: list[str] | tuple[str, ...],
    dataset_notes: list[str] | tuple[str, ...],
    dataset_named: bool,
) -> dict | None:
    """The first dataset rung that applies, in priority order, or ``None``."""
    step = _unread_dataset_step(reports, skipped_files, dataset_notes, dataset_named)
    if step is not None:
        return step
    for rung in (
        _no_dataset_step,
        _unloadable_dataset_step,
        _missing_gold_step,
        _holdout_overlap_step,
        _short_dataset_step,
    ):
        step = rung(reports)
        if step is not None:
            return step
    return None


def _inventory_gap_step(inventory: PythonInventory) -> dict | None:
    gap = inventory_gap(inventory)
    if not gap:
        return None
    if inventory.files_unparsed:
        pronoun = "it" if len(inventory.files_unparsed) == 1 else "them"
        remedy = f"fix or exclude {pronoun} and re-run this audit."
    else:
        remedy = "narrow --root to the project's own code and re-run this audit."
    return {
        "branch": "i",
        "skills": [],
        "line": (
            f"{_capitalised(gap)}, so the entry points and scorers above may be "
            f"incomplete — {remedy}"
        ),
    }


def _dataset_fact_step(
    reports: list[DatasetReport],
    skipped_files: list[str] | tuple[str, ...],
    dataset_notes: list[str] | tuple[str, ...],
) -> dict | None:
    facts = dataset_findings(reports, list(dataset_notes), list(skipped_files))
    if not facts:
        return None
    if len(facts) == len(skipped_files):
        line = (
            f"{facts[0]}, so this audit cannot rule out an evaluation file it "
            "did not read — repair it, or name your dataset with --dataset so "
            "other files are not scanned, then re-run this audit."
        )
    else:
        line = (
            f"{facts[0]}, so this audit cannot call the dataset ready — resolve "
            "it with `traigent-dataset-curate`, then re-run this audit."
        )
    return {"branch": "f", "skills": ["traigent-dataset-curate"], "line": line}


def _placeholder_probe_step(
    probe: dict | None, probed: ScorerCandidate | None
) -> dict | None:
    """A probe on placeholder text measured repeatability only, so the Scorer
    area is not `ok` and `g` would claim more than was tested."""
    if probe is None or probe.get("payload_source") != "synthetic":
        return None
    return {
        "branch": "e",
        "skills": ["traigent-eval-audit"],
        "line": (
            f"`{probed.function}` at {probed.file}:{probed.line} is repeatable, "
            "but it was probed with placeholder text because no dataset gave "
            "two distinct usable gold values of the same kind, so whether it "
            "separates a good answer for this task from a bad one is unknown — "
            "assess it with `traigent-eval-audit`."
        ),
    }


def _all_clear_step() -> dict:
    return {
        "branch": "g",
        "skills": ["traigent-optimize-run"],
        "line": (
            "Entry point, knobs, dataset and scorer all check out, so the open "
            "question is whether tuning moves anything — run a mock dry-run first, "
            "then one small bounded run, with `traigent-optimize-run`."
        ),
    }


def _knob_step_on(knob: dict | None, branch: str) -> dict | None:
    return knob if knob is not None and knob["branch"] == branch else None


def next_step(
    inventory: PythonInventory,
    reports: list[DatasetReport],
    probe: dict | None,
    probed: ScorerCandidate | None,
    *,
    skipped_files: list[str] | tuple[str, ...] = (),
    dataset_notes: list[str] | tuple[str, ...] = (),
    dataset_named: bool = False,
) -> dict:
    """Exactly one next step, chosen by the most blocking finding.

    The Agent and Dataset rungs read the same `knob_wiring`, `inventory_gap`
    and `dataset_findings` the area cards read, so `g` is reached only when
    the Agent, Dataset and Scorer areas all read `ok`.
    """
    metrics = probe_metrics(probe)
    wiring = knob_wiring(entry_point_records(inventory.entry_points))
    knob = knob_step(wiring)

    if not inventory.entry_points:
        return _no_entry_point_step(inventory)

    # Each rung is tried in priority order; the first that applies is the step.
    # Knob wiring that is partly broken or unconfirmed (`h`) is concrete spend,
    # but below the dataset faults that make a run worthless outright.
    rungs = (
        lambda: _knob_step_on(knob, "b"),
        lambda: _scorer_step(inventory, metrics, probed),
        lambda: _dataset_step(reports, skipped_files, dataset_notes, dataset_named),
        lambda: _knob_step_on(knob, "h"),
        lambda: _inventory_gap_step(inventory),
        lambda: _dataset_fact_step(reports, skipped_files, dataset_notes),
        lambda: _placeholder_probe_step(probe, probed),
    )
    for rung in rungs:
        step = rung()
        if step is not None:
            return step
    return _all_clear_step()


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
        ("Repeat-scoring measures repeatability, not correctness. A scorer that "
        "returns the same wrong number every time passes this probe."),
        ("No lift is promised. This audit says nothing about whether optimization "
        "will improve your agent, and a flat or negative result is a real outcome."),
        ("Knob wiring is detected statically. A knob read through a mapping the "
        "parser cannot follow is reported as possibly read, and a configuration "
        "space the parser cannot read is reported as unread, never as absent."),
        ("Model ids are collected, not validated. Checking an id against a provider "
        "is a network call, which this tier does not make."),
        ("Only Python is inventoried in this version. A JavaScript or TypeScript "
        "project is not searched for entry points or scorers."),
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

    if args.dataset:
        reports, dataset_candidates, dataset_notes, skipped_files = explicit_datasets(
            Path(args.dataset), root
        )
    else:
        reports, dataset_candidates, dataset_notes, skipped_files = scan_datasets(
            files, root
        )

    selected, probed, refusal = _choose_scorer(args.scorer, inventory, root)

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

    model_ids = _declared_model_ids(inventory)

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
                "holdout_files": _walkthrough_holdout_files(walkthrough_files, root),
            },
        },
        "areas": areas,
        "entry_points": entry_point_records(inventory.entry_points),
        "llm_call_sites": inventory.llm_call_sites[:20],
        "dataset_minimums": {
            "smoke_check": MIN_SMOKE,
            "first_tuning_slice": MIN_TUNING,
            "holdout_slice": MIN_HOLDOUT,
            "high_variance_task": MIN_HIGH_VARIANCE,
            "near_duplicate_row_ceiling": NEAR_DUPLICATE_LIMIT,
            "source": "skills/traigent-dataset-curate/SKILL.md",
        },
        "datasets": [_dataset_record(report) for report in reports],
        "scorers": [
            _scorer_record(candidate, candidate is selected)
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
        "next_step": next_step(
            inventory,
            reports,
            probe,
            probed,
            skipped_files=skipped_files,
            dataset_notes=dataset_notes,
            dataset_named=bool(args.dataset),
        ),
        "setup": {
            "sdk": sdk,
            "keys": keys,
            "env_file_git_status": ignored,
            "model_ids_declared": model_ids,
        },
        "open_questions": open_questions(areas, reports),
        "not_established": not_established(guard_level),
    }


def _choose_scorer(
    selector: str | None, inventory: PythonInventory, root: Path
) -> tuple[ScorerCandidate | None, ScorerCandidate | None, str | None]:
    """``(selected, probed, refusal)``.

    Without ``--scorer`` the only deterministic scorer found, if exactly one,
    is probed. With it, the selected function is probed only when it is
    deterministic. An explicit selection is not permission to run arbitrary
    code: a judge calls a provider and an executing scorer runs code, and this
    audit does neither, whichever way the scorer was chosen.
    """
    if not selector:
        deterministic = [c for c in inventory.scorers if c.kind == "deterministic"]
        return None, (deterministic[0] if len(deterministic) == 1 else None), None
    selected = _select_scorer(selector, inventory, root)
    if selected.kind == "deterministic":
        return selected, selected, None
    refusal = (
        f"`{selected.function}` at {selected.file} was selected with "
        f"--scorer and refused: it is classified {selected.kind}"
        + (f" ({'; '.join(selected.signals)})" if selected.signals else "")
        + ", and this audit runs no scorer that calls a provider or "
        "executes code — `traigent-eval-audit` assesses those"
    )
    return selected, None, refusal


def _select_scorer(
    selector: str, inventory: PythonInventory, root: Path
) -> ScorerCandidate:
    """The scorer named by ``--scorer FILE.py:FUNCTION``: the inventory's own
    record when it has one, else a record classified from the module."""
    file_part, _, function_part = selector.rpartition(":")
    if not file_part or not function_part:
        raise ValueError("--scorer must be given as FILE.py:FUNCTION")
    # A relative selector is read against the working directory when that
    # lands inside --root, else against --root: joined to the root once.
    # Every read of the selected file uses this one resolved path.
    sel_abs = os.path.realpath(root / relative(Path(file_part), root))
    chosen_file = relative(Path(sel_abs), root)

    def is_selection(file: str, function: str) -> bool:
        # Same resolved path, not same spelling or inode. Known limit: on a
        # case-insensitive volume a differently-cased selection lists twice.
        return function == function_part and os.path.realpath(root / file) == sel_abs

    selected = next(
        (
            candidate
            for candidate in inventory.scorers
            if is_selection(candidate.file, candidate.function)
        ),
        None,
    )
    if selected is not None:
        return selected
    kind, signals, line = classify_module_function(Path(sel_abs), function_part)
    selected = ScorerCandidate(
        function=function_part,
        file=chosen_file,
        line=line,
        kind=kind,
        signals=signals,
        parameters=[],
    )
    # A selected function found by name IS a scorer, whatever its name
    # and whether it is probed or refused: listing it keeps the scorer
    # area, the next step and Tier 2 on one fact.
    if line:
        inventory.scorers.append(selected)
        inventory.skipped_scorers = [
            item
            for item in inventory.skipped_scorers
            if not is_selection(item.file, item.function)
        ]
    return selected


def _declared_model_ids(inventory: PythonInventory) -> list[str]:
    """Every value of a model-named knob, as text, sorted and deduplicated."""
    model_ids = [
        str(value)
        for entry in inventory.entry_points
        for knob in entry.knobs
        if knob.name in MODEL_KNOB_NAMES
        for value in knob.values
    ]
    return sorted(set(model_ids))


def _walkthrough_holdout_files(walkthrough_files: list[Path], root: Path) -> list[str]:
    """The first run's own tuning/holdout working copies, when present: named
    so the card can say where the graduate's reserved slice is."""
    return sorted(
        relative(path, root)
        for path in walkthrough_files
        if path.suffix.lower() in {".jsonl", ".json", ".csv"}
        and file_names_holdout(relative(path, root))
    )


def _dataset_record(report: DatasetReport) -> dict:
    """One dataset file as the report's `datasets` record."""
    return {
        "file": report.file,
        "rows": report.rows,
        "input_keys": report.input_key_counts,
        "gold_keys": report.expected_key_counts,
        "missing_gold_rows": report.missing_expected,
        "missing_gold_counts": report.missing_gold_counts,
        "duplicate_groups": report.exact_duplicate_groups,
        "near_duplicate_pairs": report.near_duplicate_pairs,
        "splits": report.split_counts,
        "holdout_rows": report.holdout_rows,
        "holdout_overlap_rows": report.holdout_overlap,
        "label_counts": report.label_counts,
        "findings": report.findings,
        "notes": report.notes,
        "rows_without_sdk_input_key": report.rows_without_sdk_input,
    }


def _scorer_record(candidate: ScorerCandidate, selected: bool) -> dict:
    """One scorer as the report's `scorers` record; ``selected`` only when it
    is the ``--scorer`` choice."""
    return {
        "function": candidate.function,
        "file": candidate.file,
        "line": candidate.line,
        "kind": candidate.kind,
        "signals": candidate.signals,
        **({"selected": True} if selected else {}),
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
        # Strict JSON, built before anything is written: a non-finite number
        # refuses the whole report rather than writing `Infinity`.
        text = (
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
            if args.json_out
            else None
        )
    except ValueError as exc:
        print(f"audit_project.py: {exc}", file=sys.stderr)
        return 2

    if text is not None:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    print(render_card(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
