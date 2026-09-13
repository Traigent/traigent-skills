#!/usr/bin/env python3
"""Run one of the user's deterministic scorers in a separate process.

The parent (``audit_project.py``) never loads user code itself. How strongly
this process is contained is the parent's decision: it launches this script
inside a network namespace when one is available, and this script additionally
replaces Python's socket entry points with a refusal before the user's module
is loaded.

Nothing here relays text produced by user code. A failure is reported as the
exception TYPE plus a ``file:line`` inside the user's project — never the
exception message, never the child's stderr — because a scorer that raises
"bad key sk-..." would otherwise put that value in the audit report.

Reads one JSON request on standard input and writes one JSON result line on
standard output. Standard library only, Python 3.11+.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

GUARD_MESSAGE = "traigent-setup-audit: network disabled in the free audit"
# The parent reads ONLY a line carrying this prefix, and only if there is
# exactly one. Anything else the scorer prints is ignored, which is what stops a
# scorer's own JSON output from being read as the probe's result.
RESULT_MARKER = "<<<TRAIGENT_SETUP_AUDIT_RESULT>>>"


class NetworkDisabled(RuntimeError):
    """Raised in place of opening a socket."""


class _RefusingSocket:
    """Stands in for ``socket.socket``.

    A CLASS, not a function: ``ssl`` declares ``class SSLSocket(socket)``, so a
    function here made ``import ssl`` raise a TypeError, which the parent then
    reported as scorer instability.
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


def is_guard_refusal(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, NetworkDisabled):
            return True
        if isinstance(current, RuntimeError) and str(current) == GUARD_MESSAGE:
            return True
        current = current.__cause__ or current.__context__
    return False


def fault(exc: BaseException, root: str) -> dict:
    """Exception TYPE and the last frame inside the user's project.

    Deliberately message-free: ``str(exc)`` is attacker- and accident-controlled
    text that has already been observed carrying an API key.
    """
    site = None
    traceback = exc.__traceback__
    root_prefix = os.path.abspath(root) + os.sep
    while traceback is not None:
        filename = os.path.abspath(traceback.tb_frame.f_code.co_filename)
        if filename.startswith(root_prefix):
            site = f"{os.path.relpath(filename, root)}:{traceback.tb_lineno}"
        traceback = traceback.tb_next
    return {"error_type": type(exc).__name__, "error_site": site}


def load_callable(module_path: str, function_name: str):
    """Load the user's module in a fresh namespace and return the named callable.

    ``runpy.run_path`` is deliberate: it keeps the module out of ``sys.modules``
    and does not run it as ``__main__``, so a script guard in the user's file
    stays unexecuted.
    """
    import runpy

    parent = os.path.dirname(os.path.abspath(module_path))
    if parent not in sys.path:
        sys.path.insert(0, parent)
    namespace = runpy.run_path(module_path)
    target = namespace.get(function_name)
    if target is None or not callable(target):
        raise LookupError("the named function is not a callable in that module")
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
    raise TypeError("the scorer returned a value that is not a number")


def probe(request: dict) -> dict:
    guard = verify_network_guard()
    root = request.get("root") or os.path.dirname(request["module"])
    try:
        target = load_callable(request["module"], request["function"])
    except BaseException as exc:  # noqa: BLE001 - user code decides what it raises
        if is_guard_refusal(exc):
            return {
                "ran": False,
                "network_blocked": True,
                "network_guard": guard,
                "stage": "load",
            }
        return {
            "ran": False,
            "network_guard": guard,
            "stage": "load",
            **fault(exc, root),
        }

    repeats = max(1, int(request.get("repeats", 5)))
    cases = (
        ("good", request["good"], request["good"], repeats),
        ("partial", request["partial"], request["good"], 1),
        ("bad", request["bad"], request["good"], 1),
    )
    scores: dict[str, list[float]] = {}
    errors: list[dict] = []
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
                        "stage": "call",
                    }
                errors.append({"case": name, **fault(exc, root)})
                break
        scores[name] = collected
    return {
        "ran": True,
        "network_guard": guard,
        "scores": scores,
        "errors": errors,
    }


def _emit(result: dict) -> None:
    """One framed line, flushed, so the parent can find it among user output."""
    sys.stdout.write(RESULT_MARKER + json.dumps(result, sort_keys=True) + "\n")
    sys.stdout.flush()


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
    except ValueError:
        _emit({"ran": False, "stage": "unreadable-request"})
        return 0
    _emit(probe(request))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
