"""Framework auto-override teaching must match the released SDK (traigent-skills#350).

1. The SDK only overrides when ``auto_override_frameworks=True`` *and*
   ``framework_targets`` are set together, so every call that passes
   ``framework_targets=`` must also pass ``auto_override_frameworks=True``.
2. On ``traigent<=0.27.0`` the override is a silent no-op inside trials, so every
   page that shows an auto-override example carries the released-SDK caveat (or,
   once a fixed release ships, a ``Requires traigent>=X`` gate).
3. Every class listed under "Supported Auto-Discovery Targets" has a parameter
   mapping in the installed SDK.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .test_audit_349_fenced_blocks import (
    python_blocks,
    scoped_markdown,
    skip_unless_current_released_sdk,
)

VERSION_GATE_RE = re.compile(
    r"Released SDK caveat:\*\* on `traigent<=0\.27\.0` auto-override is a silent no-op"
    r"|Requires `traigent>=\d+\.\d+\.\d+`"
)
TARGETS_SECTION_RE = re.compile(
    r"^### Supported Auto-Discovery Targets\n(.*?)(?=^#)", re.S | re.M
)


def _scan_targets_without_flag(rel: str, text: str) -> list[str]:
    violations: list[str] = []
    for first_line, block in python_blocks(text):
        try:
            tree = ast.parse(block)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            if "framework_targets" not in kwargs:
                continue
            flag = kwargs.get("auto_override_frameworks")
            if isinstance(flag, ast.Constant) and flag.value is True:
                continue
            violations.append(
                f"{rel}:{first_line + node.lineno - 1}: framework_targets= without "
                "auto_override_frameworks=True in the same call (the SDK skips the override)"
            )
    return violations


def _scan_missing_version_gate(rel: str, text: str) -> list[str]:
    shows_example = any(
        "auto_override_frameworks=True" in block for _, block in python_blocks(text)
    )
    if shows_example and not VERSION_GATE_RE.search(text):
        return [
            f"{rel}: auto-override example without the traigent<=0.27.0 caveat "
            "or a `Requires traigent>=X` gate"
        ]
    return []


def _listed_targets(text: str) -> list[str]:
    section = TARGETS_SECTION_RE.search(text)
    assert section, "langchain.md lost its 'Supported Auto-Discovery Targets' section"
    return re.findall(r"`([\w.]+\.[A-Z]\w*)`", section.group(1))


def test_framework_targets_always_paired_with_auto_override(repo_root: Path) -> None:
    violations: list[str] = []
    for path in scoped_markdown(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        violations.extend(
            _scan_targets_without_flag(rel, path.read_text(encoding="utf-8"))
        )
    assert not violations, "\n".join(violations)


def test_auto_override_examples_carry_the_released_sdk_gate(repo_root: Path) -> None:
    violations: list[str] = []
    for path in scoped_markdown(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        violations.extend(
            _scan_missing_version_gate(rel, path.read_text(encoding="utf-8"))
        )
    assert not violations, "\n".join(violations)


def test_supported_targets_have_sdk_parameter_mappings(
    repo_root: Path, sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(
        sync_map, sdk_version_label, "the supported-targets list"
    )
    from traigent.integrations import framework_override

    mapped = set(framework_override._framework_override_manager._parameter_mappings)
    path = repo_root / "skills/traigent-setup-integrations/references/langchain.md"
    listed = _listed_targets(path.read_text(encoding="utf-8"))
    assert listed, "no targets parsed from 'Supported Auto-Discovery Targets'"
    unmapped = sorted(set(listed) - mapped)
    assert not unmapped, (
        f"listed as supported but the installed SDK has no parameter mapping: {unmapped}"
    )


def test_auto_override_lints_have_teeth() -> None:
    bad = (
        "```python\n@traigent.optimize(\n    configuration_space={},\n"
        '    framework_targets=["langchain_openai.ChatOpenAI"],\n)\ndef f(x): ...\n```\n'
    )
    assert _scan_targets_without_flag("bad.md", bad)
    assert _scan_missing_version_gate(
        "bad.md", bad.replace("framework_targets", "auto_override_frameworks=True, t")
    )
    good = bad.replace(
        "    framework_targets",
        "    auto_override_frameworks=True,\n    framework_targets",
    )
    assert not _scan_targets_without_flag("good.md", good)
    gated = good + "\n> Requires `traigent>=0.28.0`.\n"
    assert not _scan_missing_version_gate("gated.md", gated)
    assert _listed_targets(
        "### Supported Auto-Discovery Targets\n\n- `a.B`\n- `c.d.E`, `f.G`\n\n## Next\n"
    ) == ["a.B", "c.d.E", "f.G"]
