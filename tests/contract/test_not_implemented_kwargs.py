"""Guards against a taught kwarg whose NAME is a real parameter (passes the
plain signature check in ``test_python_contracts.py``) but whose VALUE the
SDK's own docstring documents as raising ``NotImplementedError``.

Case in point: traigent-ci-safety-gate taught ``safety_constraints=[...]`` on
``@traigent.optimize`` as runnable. The kwarg name is real, but the SDK
docstring says "Not yet implemented - raises ``NotImplementedError``" and the
decorator raises it at decoration time for any non-empty value.
"""

from __future__ import annotations

import inspect
import re

import pytest

from .facts import ContractFact
from .verifier import resolve_dotted

_PARAM_START_RE = re.compile(r"^(\w+):\s")


def _kwarg_documented_as_not_implemented(doc: str, kwarg: str) -> bool:
    """True if a Google-style docstring documents ``kwarg`` in a paragraph
    that mentions ``NotImplementedError``."""
    lines = doc.splitlines()
    starts = [
        (i, len(line) - len(line.lstrip()))
        for i, line in enumerate(lines)
        if re.match(rf"^\s*{re.escape(kwarg)}:\s", line)
    ]
    if not starts:
        return False
    start_i, indent = starts[0]
    end_i = len(lines)
    for j in range(start_i + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            end_i = j
            break
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= indent and _PARAM_START_RE.match(line.strip()):
            end_i = j
            break
    return "NotImplementedError" in "\n".join(lines[start_i:end_i])


def test_taught_kwargs_are_not_documented_as_not_implemented(
    python_fact: ContractFact,
) -> None:
    if python_fact.kind != "call_kwargs":
        pytest.skip("only call_kwargs facts carry keyword names to check")
    try:
        target = resolve_dotted(python_fact.target or "")
    except (ModuleNotFoundError, AttributeError):
        pytest.skip(f"{python_fact.target} not resolvable against this SDK bucket")

    doc = inspect.getdoc(target) or ""
    if not doc:
        pytest.skip(f"{python_fact.target} has no docstring to check")

    dead = [
        kwarg
        for kwarg in python_fact.kwargs
        if _kwarg_documented_as_not_implemented(doc, kwarg)
    ]
    assert not dead, (
        f"DEAD TEACHING  {python_fact.identifier()}\n"
        f"  teaches : {python_fact.display()}\n"
        f"  problem : SDK docstring documents {', '.join(dead)} as "
        "not-yet-implemented / raising NotImplementedError.\n"
        "  fix     : stop teaching this kwarg as runnable; describe it as "
        "roadmap-only and point at a working alternative."
    )
