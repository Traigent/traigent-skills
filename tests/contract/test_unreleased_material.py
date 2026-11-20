"""Guards for ``docs/unreleased/``: SDK features merged to develop but not yet released.

``docs/unreleased/README.md`` explains the convention. Two things are enforced:

* While a file is parked in ``docs/unreleased/``, no skill may teach what it describes.
  A skill that did would send a user on the shipping SDK to a command that does not exist,
  and the contract buckets would fail on it.
* The moment a *released* SDK bucket contains the feature, the parked file is overdue:
  the test goes red and names the activation steps, so the move is not forgotten.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UNRELEASED = ROOT / "docs" / "unreleased"
REGRESSION_DOC = UNRELEASED / "regression-set-and-repeat-outcomes.md"

# What the parked file teaches. Each is a literal that only the unreleased SDK knows.
REGRESSION_TOKENS = (
    "traigent regression",
    "example_consistency",
    "Repeat outcomes",
)


def _skill_markdown() -> list[Path]:
    return sorted((ROOT / "skills").glob("**/*.md"))


def test_the_index_lists_every_parked_file() -> None:
    index = (UNRELEASED / "README.md").read_text(encoding="utf-8")
    for path in sorted(UNRELEASED.glob("*.md")):
        if path.name == "README.md":
            continue
        assert f"`{path.name}`" in index, (
            f"docs/unreleased/{path.name} is not listed in docs/unreleased/README.md"
        )


def test_parked_files_keep_the_release_placeholder() -> None:
    text = REGRESSION_DOC.read_text(encoding="utf-8")
    assert "<RELEASE>" in text, (
        "the parked file must name its release as <RELEASE> until the SDK that "
        "carries it is on PyPI; do not guess the version"
    )


def test_no_skill_teaches_parked_material() -> None:
    if not REGRESSION_DOC.exists():
        pytest.skip("the regression-set material has been activated")
    hits = []
    for path in _skill_markdown():
        text = path.read_text(encoding="utf-8")
        for token in REGRESSION_TOKENS:
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}: {token!r}")
    assert not hits, (
        "these skills teach SDK features that are still unreleased (the text is parked in "
        "docs/unreleased/regression-set-and-repeat-outcomes.md); move it only at release "
        "time, following docs/unreleased/README.md:\n" + "\n".join(hits)
    )


def test_released_sdk_does_not_yet_have_the_regression_commands(
    sdk_version_label: str,
) -> None:
    """Tripwire: fires in the first released bucket that ships the regression set."""
    if not REGRESSION_DOC.exists():
        pytest.skip("the regression-set material has been activated")
    if sdk_version_label in {"develop", "unknown"}:
        pytest.skip(
            "develop carries the feature by design; only released buckets are checked"
        )
    if importlib.util.find_spec("traigent") is None:
        pytest.skip("no SDK installed")
    has_commands = (
        importlib.util.find_spec("traigent.cli.regression_commands") is not None
    )
    assert not has_commands, (
        f"SDK {sdk_version_label} now ships `traigent regression`. Activate "
        "docs/unreleased/regression-set-and-repeat-outcomes.md: follow the steps in "
        "docs/unreleased/README.md (replace <RELEASE>, move each section, set "
        "min_sdk_version, update provenance, delete the parked file)."
    )
