"""Contract tests for docs/version-matrix.md (Traigent/traigent-skills#221).

The version matrix is the single authoritative table for SDK behavior-delta
facts. Inline stamps in skills/ keep a minimal canonical phrase and point at a
matrix row with ``see version-matrix: <fact_id>``. These tests keep both sides
honest:

- the matrix parses and every row is complete;
- every ``changed_in_version`` is a released SDK tag and does not exceed
  ``sync_map.yml.current_released_sdk_version``;
- every pointer in skills/ (and README.md) resolves to a matrix row
  (no dangling pointers) and every row has at least one pointer site
  (no dead rows);
- the version boundary named by a row's ``canonical_phrasing`` appears in the
  immediate context of each pointer site (phrasing-divergence check).

All checks are offline and deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from packaging.version import Version


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


MATRIX_RELPATH = "docs/version-matrix.md"

EXPECTED_COLUMNS = (
    "fact_id",
    "symbol/surface",
    "delta",
    "changed_in_version",
    "issue_ref",
    "canonical_phrasing",
)

# Released SDK tags (public Traigent/Traigent repo, `git tag`, v-prefix
# stripped). Static on purpose: PR CI must not resolve tags live. Extend this
# list when bumping sync_map.yml.current_released_sdk_version.
RELEASED_SDK_TAGS = (
    "0.13.0",
    "0.14.0",
    "0.14.2",
    "0.14.3",
    "0.15.0",
    "0.16.0",
    "0.17.0",
    "0.19.0",
    "0.19.1",
    "0.19.2",
    "0.19.3",
    "0.20.0",
    "0.20.1",
    "0.21.0",
    "0.21.1",
    "0.21.2",
    "0.21.3",
    "0.22.0",
    "0.23.0",
)

FACT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
POINTER_RE = re.compile(r"see version-matrix: `?([A-Za-z0-9_-]+)`?")
# Version boundary tokens inside canonical phrasing: "0.22.0" or "0.13.x".
BOUNDARY_TOKEN_RE = re.compile(r"\b0\.\d+\.(?:\d+|x)\b")
# Lines around a pointer that must contain the boundary token (markdown prose
# wraps, so the canonical phrase may span neighbouring lines).
POINTER_CONTEXT_LINES = 2


@dataclass(frozen=True)
class MatrixRow:
    fact_id: str
    symbol: str
    delta: str
    changed_in_version: str
    issue_ref: str
    canonical_phrasing: str
    line: int


def _split_table_row(line: str) -> list[str]:
    # Split on pipes that are not escaped (`\|` appears inside cells).
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [cell.replace("\\|", "|").strip() for cell in cells]


def _parse_matrix(root: Path) -> list[MatrixRow]:
    path = root / MATRIX_RELPATH
    assert path.is_file(), f"{MATRIX_RELPATH} is missing"
    lines = path.read_text(encoding="utf-8").splitlines()

    header_index = None
    for index, line in enumerate(lines):
        if line.strip().startswith("|") and "fact_id" in line:
            header_index = index
            break
    assert header_index is not None, f"{MATRIX_RELPATH}: no table header with fact_id"

    header = tuple(_split_table_row(lines[header_index]))
    normalized = tuple(cell.strip("`") for cell in header)
    assert normalized == EXPECTED_COLUMNS, (
        f"{MATRIX_RELPATH}: header columns {normalized!r} != {EXPECTED_COLUMNS!r}"
    )

    rows: list[MatrixRow] = []
    for offset, line in enumerate(lines[header_index + 2 :], start=header_index + 3):
        if not line.strip().startswith("|"):
            break
        cells = _split_table_row(line)
        assert len(cells) == len(EXPECTED_COLUMNS), (
            f"{MATRIX_RELPATH}:{offset}: expected {len(EXPECTED_COLUMNS)} cells, "
            f"found {len(cells)}"
        )
        rows.append(
            MatrixRow(
                fact_id=cells[0].strip("`"),
                symbol=cells[1],
                delta=cells[2],
                changed_in_version=cells[3].strip("`"),
                issue_ref=cells[4],
                canonical_phrasing=cells[5],
                line=offset,
            )
        )
    return rows


def _pointer_scan_files(root: Path) -> list[Path]:
    files = sorted((root / "skills").glob("**/*.md"))
    readme = root / "README.md"
    if readme.is_file():
        files.append(readme)
    return files


def _pointer_sites(root: Path) -> list[tuple[Path, int, str]]:
    """Return (path, 1-based line number, fact_id) for every pointer."""
    sites: list[tuple[Path, int, str]] = []
    for path in _pointer_scan_files(root):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in POINTER_RE.finditer(line):
                sites.append((path, line_number, match.group(1)))
    return sites


def test_matrix_parses_with_complete_unique_rows() -> None:
    rows = _parse_matrix(repo_root())
    assert rows, f"{MATRIX_RELPATH}: table has no rows"

    seen: set[str] = set()
    for row in rows:
        assert FACT_ID_RE.fullmatch(row.fact_id), (
            f"{MATRIX_RELPATH}:{row.line}: fact_id {row.fact_id!r} is not kebab-case"
        )
        assert row.fact_id not in seen, (
            f"{MATRIX_RELPATH}:{row.line}: duplicate fact_id {row.fact_id!r}"
        )
        seen.add(row.fact_id)
        for field in ("symbol", "delta", "changed_in_version", "issue_ref",
                      "canonical_phrasing"):
            assert getattr(row, field), (
                f"{MATRIX_RELPATH}:{row.line}: empty {field} for {row.fact_id!r}"
            )


def test_changed_in_version_is_released_and_within_current(sync_map: dict) -> None:
    current = Version(str(sync_map["current_released_sdk_version"]))
    for row in _parse_matrix(repo_root()):
        assert row.changed_in_version in RELEASED_SDK_TAGS, (
            f"{MATRIX_RELPATH}:{row.line}: {row.fact_id!r} changed_in_version "
            f"{row.changed_in_version!r} is not a released SDK tag"
        )
        assert Version(row.changed_in_version) <= current, (
            f"{MATRIX_RELPATH}:{row.line}: {row.fact_id!r} changed_in_version "
            f"{row.changed_in_version} exceeds current_released_sdk_version {current}"
        )


def test_no_dangling_pointers() -> None:
    root = repo_root()
    known = {row.fact_id for row in _parse_matrix(root)}
    dangling = [
        f"{path.relative_to(root)}:{line}: unknown fact {fact_id!r}"
        for path, line, fact_id in _pointer_sites(root)
        if fact_id not in known
    ]
    assert not dangling, (
        "pointers to nonexistent version-matrix rows:\n" + "\n".join(dangling)
    )


def test_version_matrix_mentions_are_wellformed_pointers() -> None:
    """A wrapped or misspelled pointer would silently escape the other checks.

    Every line mentioning "version-matrix" in skills/ or README.md must contain
    a complete single-line ``see version-matrix: <fact_id>`` pointer.
    """
    root = repo_root()
    malformed: list[str] = []
    for path in _pointer_scan_files(root):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "version-matrix" in line and not POINTER_RE.search(line):
                malformed.append(
                    f"{path.relative_to(root)}:{line_number}: mentions "
                    "version-matrix without a complete single-line "
                    "`see version-matrix: <fact_id>` pointer"
                )
    assert not malformed, "\n".join(malformed)


def test_no_dead_matrix_rows() -> None:
    root = repo_root()
    pointed = {fact_id for _, _, fact_id in _pointer_sites(root)}
    dead = [
        f"{MATRIX_RELPATH}:{row.line}: {row.fact_id!r} has no "
        "`see version-matrix:` pointer site in skills/ or README.md"
        for row in _parse_matrix(root)
        if row.fact_id not in pointed
    ]
    assert not dead, "dead version-matrix rows:\n" + "\n".join(dead)


def test_pointer_sites_carry_the_canonical_version_boundary() -> None:
    """Phrasing-divergence check (pragmatic variant).

    Full literal phrase matching would be brittle across table cells, code
    comments, and wrapped prose, so this asserts the load-bearing invariant:
    every version-boundary token in a row's canonical_phrasing (e.g. "0.22.0")
    must appear within POINTER_CONTEXT_LINES lines of each pointer to that row.
    A site whose stated boundary drifts from the row's boundary fails here.
    """
    root = repo_root()
    boundaries = {
        row.fact_id: BOUNDARY_TOKEN_RE.findall(row.canonical_phrasing)
        for row in _parse_matrix(root)
    }
    for fact_id, tokens in boundaries.items():
        assert tokens, (
            f"{MATRIX_RELPATH}: {fact_id!r} canonical_phrasing names no "
            "version boundary token"
        )

    violations: list[str] = []
    for path, line_number, fact_id in _pointer_sites(root):
        tokens = boundaries.get(fact_id)
        if tokens is None:
            continue  # dangling pointers are reported by their own test
        lines = path.read_text(encoding="utf-8").splitlines()
        start = max(0, line_number - 1 - POINTER_CONTEXT_LINES)
        end = min(len(lines), line_number + POINTER_CONTEXT_LINES)
        window = "\n".join(lines[start:end])
        for token in tokens:
            if token not in window:
                violations.append(
                    f"{path.relative_to(root)}:{line_number}: pointer to "
                    f"{fact_id!r} lacks canonical boundary {token!r} within "
                    f"±{POINTER_CONTEXT_LINES} lines"
                )
    assert not violations, "\n".join(violations)
