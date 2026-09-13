#!/usr/bin/env python3
"""Run one of the user's deterministic scorers in a separate process, with the
network guard installed before the user's module is loaded.

Reads one JSON request on standard input and writes one JSON result line on
standard output. The parent (``audit_project.py``) never loads user code itself.

Request:
    {"module": "/abs/path/scorer.py", "function": "score",
     "good": "...", "partial": "...", "bad": "...", "repeats": 5}

Result:
    {"ran": true, "network_guard": "active",
     "scores": {"good": [...], "partial": [...], "bad": [...]}, "errors": [...]}
    {"ran": false, "network_blocked": true, "reason": "..."}

Standard library only, Python 3.11+.
"""

from __future__ import annotations

import argparse
import json
import sys

GUARD_MESSAGE = "traigent-setup-audit: network disabled in the free audit"


def install_network_guard() -> None:
    """Replace the socket entry points with a refusal. Runs before any user code."""
    import socket

    def _refuse(*args, **kwargs):
        raise RuntimeError(GUARD_MESSAGE)

    socket.socket = _refuse
    socket.create_connection = _refuse
    socket.getaddrinfo = _refuse
    socket.gethostbyname = _refuse


def verify_network_guard() -> str:
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


def is_guard_refusal(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, RuntimeError) and str(current) == GUARD_MESSAGE:
            return True
        current = current.__cause__ or current.__context__
    return False


def load_callable(module_path: str, function_name: str):
    """Load the user's module in a fresh namespace and return the named callable.

    ``runpy.run_path`` is deliberate: it keeps the module out of ``sys.modules``
    and does not run it as ``__main__``, so a script guard in the user's file
    stays unexecuted.
    """
    import os
    import runpy

    parent = os.path.dirname(os.path.abspath(module_path))
    if parent not in sys.path:
        sys.path.insert(0, parent)
    namespace = runpy.run_path(module_path)
    target = namespace.get(function_name)
    if target is None or not callable(target):
        raise LookupError(
            f"{function_name!r} is not a callable in {module_path}"
        )
    return target


def call_scorer(target, output_value: str, expected_value: str) -> float:
    result = target(output_value, expected_value)
    if isinstance(result, bool):
        return 1.0 if result else 0.0
    if isinstance(result, (int, float)):
        return float(result)
    if isinstance(result, dict):
        for key in ("score", "value", "result"):
            if isinstance(result.get(key), (int, float)):
                return float(result[key])
    raise TypeError(f"scorer returned {type(result).__name__}, not a number")


def probe(request: dict) -> dict:
    guard = verify_network_guard()
    try:
        target = load_callable(request["module"], request["function"])
    except BaseException as exc:  # noqa: BLE001 - user code decides what it raises
        if is_guard_refusal(exc):
            return {
                "ran": False,
                "network_blocked": True,
                "network_guard": guard,
                "reason": "loading the scorer module tried to open a network connection",
            }
        return {
            "ran": False,
            "network_guard": guard,
            "reason": f"could not load the scorer: {type(exc).__name__}: {exc}",
        }

    repeats = max(1, int(request.get("repeats", 5)))
    cases = (
        ("good", request["good"], request["good"], repeats),
        ("partial", request["partial"], request["good"], 1),
        ("bad", request["bad"], request["good"], 1),
    )
    scores: dict[str, list[float]] = {}
    errors: list[str] = []
    for name, output_value, expected_value, times in cases:
        collected: list[float] = []
        for _ in range(times):
            try:
                collected.append(call_scorer(target, output_value, expected_value))
            except BaseException as exc:  # noqa: BLE001
                if is_guard_refusal(exc):
                    return {
                        "ran": False,
                        "network_blocked": True,
                        "network_guard": guard,
                        "reason": (
                            "the scorer tried to open a network connection while "
                            "scoring"
                        ),
                    }
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                break
        scores[name] = collected
    return {
        "ran": True,
        "network_guard": guard,
        "scores": scores,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    install_network_guard()
    parser = argparse.ArgumentParser(
        prog="scorer_probe.py",
        description="Run one deterministic scorer with the network guard installed.",
    )
    parser.add_argument(
        "--request-stdin",
        action="store_true",
        help="read the JSON probe request from standard input",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if not args.request_stdin:
        parser.print_usage(sys.stderr)
        return 2
    try:
        request = json.loads(sys.stdin.read())
    except ValueError as exc:
        print(json.dumps({"ran": False, "reason": f"unreadable request: {exc}"}))
        return 0
    print(json.dumps(probe(request), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
