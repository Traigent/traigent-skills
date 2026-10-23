"""Issue #443: the skill must not flatly claim the SDK ignores the project ``.env``.

traigent 0.28.0+ loads the caller's project ``.env`` when a function is decorated;
0.24.0-0.27.0 do not. The claim must be version-scoped and document the opt-out.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2] / "skills" / "traigent-setup-quickstart"
SKILL = ROOT / "SKILL.md"
ENV_REF = ROOT / "references" / "environment-variables.md"


def test_no_flat_claim_that_project_env_is_ignored() -> None:
    for page in (SKILL, ENV_REF):
        text = page.read_text(encoding="utf-8")
        assert "does **not** read your project's `.env`" not in text
        assert "does not load your project's `.env`" not in text
        assert "0.28.0" in text, page.name
        assert "TRAIGENT_SKIP_DOTENV" in text, page.name
        assert "when you decorate" not in text
        assert "on decoration" not in text
        assert "import" in text.split("TRAIGENT_SKIP_DOTENV")[0][-400:], page.name


def test_mock_not_offline_mentions_env_keys() -> None:
    line = next(
        row for row in SKILL.read_text(encoding="utf-8").splitlines() if row.startswith("- **Mock ≠ offline.**")
    )
    assert ".env" in line
    assert "TRAIGENT_OFFLINE_MODE=true" in line


def test_sdk_loader_and_opt_out_exist() -> None:
    traigent = pytest.importorskip("traigent")
    env_config = pytest.importorskip("traigent.utils.env_config")
    source = Path(env_config.__file__).read_text(encoding="utf-8")
    if Version(traigent.__version__) >= Version("0.28.0"):
        assert hasattr(env_config, "_find_bounded_project_dotenv")
        assert "TRAIGENT_SKIP_DOTENV" in source
    else:
        # The documented boundary: below 0.28.0 the project .env is not loaded.
        assert not hasattr(env_config, "_find_bounded_project_dotenv")
