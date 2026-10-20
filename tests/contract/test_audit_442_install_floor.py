"""Issue #442: a customer-facing install floor must not be below the repo's floor.

The quickstart and README told readers to ``pip install "traigent>=0.19"`` while
eight skills declared ``traigent>=0.24.0`` for themselves. On a machine that
already had 0.19.x, pip printed "Requirement already satisfied" and the
quickstart's own check printed ``traigent 0.19.3 OK`` -- it only rejected the
``0.0.1`` PyPI placeholder. The reader then followed guidance the skills say is
wrong below the floor (cost/latency units, ``traigent plan``, the ``auto``
algorithm).

These checks are text-only, so they run in every bucket.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]

# `pip install "traigent>=X"` / `traigent[extras]>=X`, in any quoting style.
# The extras group may contain `_`, digits and `-` (`traigent[extra_name]`), and the
# operator may be spaced or an exact pin. A narrower class silently missed
# `traigent[extra_name]>=0.19` in a file this guard already scanned.
FLOOR_RE = re.compile(
    r"traigent(?:\[[A-Za-z0-9_,\-]+\])?\s*(?:>=|==)\s*(?P<version>\d+(?:\.\d+)*)"
)

QUICKSTART = ROOT / "skills" / "traigent-setup-quickstart" / "SKILL.md"
LITERAL_SCRIPT = (
    ROOT / "skills" / "traigent-setup-quickstart" / "references" / "literal-quickstart.sh"
)


def _sync_map() -> dict:
    return yaml.safe_load((ROOT / "sync_map.yml").read_text(encoding="utf-8"))


def _default_floor() -> Version:
    return Version(str(_sync_map()["default_min_sdk_version"]))


def _customer_facing_files() -> list[Path]:
    # docs/agent-setup/prompt.md is the onboarding prompt the portal vendors and a
    # customer pastes into their coding agent -- the most customer-facing install
    # instruction in the repo, and the one the first sweep missed because the scan
    # stopped at README.md + skills/.
    paths = [ROOT / "README.md", ROOT / "docs" / "agent-setup" / "prompt.md"]
    for pattern in ("skills/**/*.md", "skills/**/*.sh"):
        paths.extend(
            p
            for p in sorted(ROOT.glob(pattern))
            # A skill's own pytest suite is not customer-facing install guidance.
            if "/tests/" not in p.as_posix()
        )
    return paths


def _applicable_floor(path: Path, sync_map: dict) -> tuple[Version, str]:
    """The floor that governs this page: the skill's own, else the repo default.

    A skill that declares a *lower* ``min_sdk_version`` than the repo default
    (``traigent-analyze-guidance`` at 0.21.3) is correct to state its own floor
    -- #442 is about an install command sinking below the floor that applies,
    not about the per-skill declarations.
    """
    default = _default_floor()
    parts = path.relative_to(ROOT).parts
    if len(parts) >= 2 and parts[0] == "skills":
        entry = (sync_map.get("skills") or {}).get(parts[1]) or {}
        declared = entry.get("min_sdk_version")
        if declared:
            return Version(str(declared)), f"{parts[1]}.min_sdk_version"
    return default, "default_min_sdk_version"


def test_no_customer_install_floor_is_below_the_repo_floor() -> None:
    sync_map = _sync_map()
    violations: list[str] = []
    for path in _customer_facing_files():
        floor, source = _applicable_floor(path, sync_map)
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in FLOOR_RE.finditer(line):
                if Version(match.group("version")) < floor:
                    violations.append(
                        f"{path.relative_to(ROOT)}:{lineno}: install floor "
                        f"{match.group(0)!r} is below {source} {floor}"
                    )
    assert not violations, "\n".join(violations)


def test_the_onboarding_prompt_is_scanned() -> None:
    """The guard must cover the file the first sweep missed, or it cannot catch it."""
    prompt = ROOT / "docs" / "agent-setup" / "prompt.md"
    assert prompt.is_file(), prompt
    assert prompt in _customer_facing_files()


def test_the_floor_regex_has_teeth() -> None:
    assert FLOOR_RE.search('pip install "traigent>=0.19"')
    assert FLOOR_RE.search("pip install 'traigent[mcp,analytics]>=0.21.3'")
    # The three forms the first, narrower regex missed.
    assert FLOOR_RE.search("pip install 'traigent[extra_name]>=0.19'")
    assert FLOOR_RE.search("traigent >= 0.19")
    assert FLOOR_RE.search("traigent==0.19")
    assert FLOOR_RE.search('pip install "traigent>=0.24.0"').group("version") == "0.24.0"
    assert not FLOOR_RE.search("pip install traigent")


def test_quickstart_install_check_enforces_the_floor() -> None:
    """The check must reject an in-range-looking but too-old release, not only 0.0.1."""
    floor = _default_floor()
    for path in (QUICKSTART, LITERAL_SCRIPT):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        assert 'v == "0.0.1"' in text, f"{rel}: lost the PyPI placeholder check"
        assert "from packaging.version import Version" in text, (
            f"{rel}: the install check must compare versions, not only match the "
            "placeholder string"
        )
        # Order matters: the 0.0.1 placeholder declares no dependencies, so a
        # `packaging` import above the placeholder branch raises
        # ModuleNotFoundError in a fresh venv and hides the crafted message.
        assert text.index('v == "0.0.1"') < text.index(
            "from packaging.version import Version"
        ), (
            f"{rel}: import packaging AFTER the placeholder check, or the "
            "placeholder diagnostic is masked in the venv it exists for"
        )
        assert f'FLOOR = "{floor}"' in text, (
            f"{rel}: the install check's FLOOR must be the repo's "
            f"default_min_sdk_version ({floor})"
        )
        assert "if Version(v) < Version(FLOOR):" in text, (
            f"{rel}: the install check must fail below FLOOR"
        )
