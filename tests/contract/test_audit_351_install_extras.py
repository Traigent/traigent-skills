"""Taught ``traigent[...]`` extras must exist in the installed wheel (traigent-skills#351).

pip only *warns* on an unknown extra (``traigent 0.27.0 does not provide the extra
'dspy'``) and exits 0, so a skill that teaches a missing extra hands the reader an
environment without the package they asked for. The bundle rows of the extras table
must also list exactly the sub-extras the wheel's ``Requires-Dist`` declares.
"""

from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path

EXTRA_USE_RE = re.compile(r"\btraigent\[([A-Za-z0-9_,\s-]+)\]")
PLACEHOLDER_EXTRAS = {"extra_name"}  # the generic `traigent[extra_name]` syntax line
BUNDLES = ("recommended", "all", "enterprise")
TABLE = "skills/traigent-setup-quickstart/references/installation-extras.md"


def _declared_extras() -> set[str]:
    return set(importlib.metadata.metadata("traigent").get_all("Provides-Extra") or [])


def _bundle_members(extra: str) -> set[str]:
    members: set[str] = set()
    for req in importlib.metadata.metadata("traigent").get_all("Requires-Dist") or []:
        if not re.search(rf"extra\s*==\s*[\"']{re.escape(extra)}[\"']", req):
            continue
        nested = re.match(r"\s*traigent\[([^\]]+)\]", req)
        if nested:
            members.update(part.strip() for part in nested.group(1).split(","))
    return members


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _extra_requirements(extra: str) -> set[str]:
    """Normalized package names an extra installs, plus its nested sub-extras."""
    names = set(_bundle_members(extra))
    for req in importlib.metadata.metadata("traigent").get_all("Requires-Dist") or []:
        if not re.search(rf"extra\s*==\s*[\"']{re.escape(extra)}[\"']", req):
            continue
        package = re.match(r"\s*([A-Za-z0-9_.-]+)", req)
        if package and _norm(package.group(1)) != "traigent":
            names.add(package.group(1))
    return {_norm(name) for name in names}


def _row_packages(cell: str) -> list[str]:
    """Package names in a Key Packages cell; descriptive phrases are skipped."""
    cell = re.sub(
        r"\([^)]*\)", "", cell
    )  # "LangChain (+ community/...)" -> "LangChain"
    tokens = (part.strip() for part in re.split(r"[,+]", cell))
    return [token for token in tokens if token and not re.search(r"[\s(]", token)]


def _scan_row_packages(text: str, wheel: dict[str, set[str]]) -> list[str]:
    violations = []
    for extra, cell in re.findall(r"^\|\s*`([\w-]+)`\s*\|[^|]*\|([^|]*)\|", text, re.M):
        if extra not in wheel:
            continue  # unknown extras are reported by the Provides-Extra test
        extra_names = wheel[extra]
        for package in _row_packages(cell):
            if _norm(package) not in extra_names:
                violations.append(
                    f"`{extra}` row names `{package}`, which `traigent[{extra}]` does not "
                    f"install (wheel: {sorted(extra_names)})"
                )
    return violations


def _scan_unknown_extras(rel: str, text: str, declared: set[str]) -> list[str]:
    violations = []
    for match in EXTRA_USE_RE.finditer(text):
        for extra in (part.strip() for part in match.group(1).split(",")):
            if extra and extra not in declared and extra not in PLACEHOLDER_EXTRAS:
                line = text.count("\n", 0, match.start()) + 1
                violations.append(
                    f"{rel}:{line}: `traigent[{extra}]` is not an extra of the installed "
                    "wheel (pip warns and installs nothing for it)"
                )
    return violations


def _table_row(text: str, extra: str) -> set[str]:
    row = re.search(rf"^\|\s*`{re.escape(extra)}`\s*\|[^|]*\|([^|]*)\|", text, re.M)
    assert row, f"no `{extra}` row in {TABLE}"
    return {part.strip() for part in row.group(1).split(",") if part.strip()}


def test_taught_extras_are_declared_by_the_wheel(repo_root: Path) -> None:
    declared = _declared_extras()
    assert declared, "installed traigent declares no extras; wrong distribution?"
    violations: list[str] = []
    for path in sorted((repo_root / "skills").rglob("*.md")):
        rel = path.relative_to(repo_root).as_posix()
        violations.extend(
            _scan_unknown_extras(rel, path.read_text(encoding="utf-8"), declared)
        )
    assert not violations, "\n".join(violations)


def test_bundle_rows_match_wheel_requires_dist(repo_root: Path) -> None:
    text = (repo_root / TABLE).read_text(encoding="utf-8")
    mismatches = []
    for bundle in BUNDLES:
        wheel = _bundle_members(bundle)
        assert wheel, f"wheel declares no sub-extras for `{bundle}`"
        taught = _table_row(text, bundle)
        if taught != wheel:
            mismatches.append(
                f"`{bundle}` row lists {sorted(taught)}; the wheel installs {sorted(wheel)}"
            )
    assert not mismatches, "\n".join(mismatches)


def test_every_row_names_only_packages_its_extra_installs(repo_root: Path) -> None:
    text = (repo_root / TABLE).read_text(encoding="utf-8")
    wheel = {extra: _extra_requirements(extra) for extra in _declared_extras()}
    violations = _scan_row_packages(text, wheel)
    assert not violations, "\n".join(violations)


def test_row_package_lint_has_teeth() -> None:
    wheel = {"test": {"pytest", "rapidfuzz"}, "ml": {"bayesian", "numpy"}}
    row = (
        "| `test` | d | pytest, ragas, pytest suite |\n"
        "| `ml` | d | bayesian + numpy (+ extras) |\n"
    )
    found = _scan_row_packages(row, wheel)
    assert len(found) == 1 and "`ragas`" in found[0], found
    assert _norm("Python_Multipart") == "python-multipart"


def test_extras_lints_have_teeth() -> None:
    declared = {"integrations", "all"}
    bad = 'pip install "traigent[dspy]>=0.19"\npip install "traigent[integrations,nope]"\n'
    found = _scan_unknown_extras("bad.md", bad, declared)
    assert len(found) == 2 and "dspy" in found[0] and "nope" in found[1]
    assert not _scan_unknown_extras(
        "ok.md", 'pip install "traigent[extra_name]" "traigent[all]"', declared
    )
    row = "| `all` | desc | analytics, bayesian |\n"
    assert _table_row(row, "all") == {"analytics", "bayesian"}
