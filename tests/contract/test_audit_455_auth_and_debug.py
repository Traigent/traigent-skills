"""Issue #455: the auth command and the debug variable must be named correctly.

``setup-quickstart`` said ``traigent auth login`` "opens a browser for OAuth
device authorization". On 0.30.0 ``auth login`` prompts for an email and
password; the browser device-code flow is a separate command,
``auth device-login``, which no skill mentioned. ``boost-agent`` offered
``TRAIGENT_DEBUG=1`` "for debug logging", which ``traigent-debugging`` already
contradicts correctly: it only shows raw ``ConfigurationError`` tracebacks.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from .test_audit_349_fenced_blocks import skip_unless_current_released_sdk

ROOT = Path(__file__).resolve().parents[2]
QUICKSTART = ROOT / "skills" / "traigent-setup-quickstart" / "SKILL.md"
BOOST = ROOT / "skills" / "traigent-boost-agent" / "SKILL.md"
ENV_VARS = (
    ROOT / "skills" / "traigent-setup-quickstart" / "references" / "environment-variables.md"
)

# "auth login ... browser" on one line, in either order.
LOGIN_BROWSER_RE = re.compile(
    r"auth login[^.\n]*\bbrowser\b|\bbrowser\b[^.\n]*auth login", re.I
)
# TRAIGENT_DEBUG presented as switching on logging.
DEBUG_AS_LOGGING_RE = re.compile(
    r"TRAIGENT_DEBUG\s*=\s*1[^.\n]{0,60}\bdebug log", re.I
)


def _scanned_files() -> list[Path]:
    paths = [
        p
        for p in sorted(ROOT.glob("skills/**/*.md"))
        if "/tests/" not in p.as_posix()
    ]
    # The onboarding prompt a customer pastes into their agent is scanned too.
    paths.append(ROOT / "docs" / "agent-setup" / "prompt.md")
    return [p for p in paths if p.is_file()]


def test_no_skill_says_auth_login_opens_a_browser() -> None:
    violations = [
        f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:140]}"
        for path in _scanned_files()
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if LOGIN_BROWSER_RE.search(line)
        # The correction itself contrasts the two commands on one line.
        and "device-login" not in line
    ]
    assert not violations, "\n".join(violations)


def test_the_device_flow_is_named() -> None:
    text = QUICKSTART.read_text(encoding="utf-8")
    assert "traigent auth device-login" in text, (
        "the browser device-code flow has a command name; the skill must give it"
    )
    assert "email and password" in text, (
        "say what `traigent auth login` actually prompts for, so a reader who runs "
        "it is not surprised"
    )


def test_no_skill_presents_traigent_debug_as_debug_logging() -> None:
    violations = [
        f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:140]}"
        for path in _scanned_files()
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if DEBUG_AS_LOGGING_RE.search(line)
    ]
    assert not violations, "\n".join(violations)


def test_the_debug_matcher_has_teeth() -> None:
    assert DEBUG_AS_LOGGING_RE.search("set `export TRAIGENT_DEBUG=1` for debug logging")
    assert not DEBUG_AS_LOGGING_RE.search(
        "`TRAIGENT_DEBUG=1` only shows raw ConfigurationError tracebacks"
    )
    assert LOGIN_BROWSER_RE.search("Run `traigent auth login` — it opens a browser")
    assert not LOGIN_BROWSER_RE.search("Run `traigent auth device-login` in your terminal")


def test_debug_logging_is_pointed_at_configure() -> None:
    for path in (BOOST, ENV_VARS):
        text = path.read_text(encoding="utf-8")
        assert 'configure(logging_level="DEBUG")' in text, (
            f"{path.relative_to(ROOT)}: name the call that actually turns on Traigent "
            "debug logs in a decorator-only script"
        )


def test_the_sdk_still_uses_traigent_debug_only_for_tracebacks(
    sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(sync_map, sdk_version_label, "the debug-variable claim")
    traigent = pytest.importorskip("traigent")
    root = Path(traigent.__file__).resolve().parent
    exceptions = (root / "utils" / "exceptions.py").read_text(encoding="utf-8")
    assert 'os.getenv("TRAIGENT_DEBUG")' in exceptions, (
        "TRAIGENT_DEBUG no longer gates the ConfigurationError traceback — re-check "
        "what the skills say it does"
    )
    logging_mod = (root / "utils" / "logging.py").read_text(encoding="utf-8")
    assert 'os.environ.get("TRAIGENT_LOG_LEVEL")' in logging_mod, (
        "TRAIGENT_LOG_LEVEL is no longer read by the logging setup the skills describe"
    )


def test_auth_cli_still_has_both_commands(
    sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(sync_map, sdk_version_label, "the auth commands")
    traigent = pytest.importorskip("traigent")
    source = (
        Path(traigent.__file__).resolve().parent / "cli" / "auth_commands.py"
    ).read_text(encoding="utf-8")
    assert "def device_login(" in source, "`traigent auth device-login` is gone"
    assert "Prompt for email and password" in source, (
        "`traigent auth login` no longer prompts for email/password — restate the "
        "quickstart's contrast between the two commands"
    )
