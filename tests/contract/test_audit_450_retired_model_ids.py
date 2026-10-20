"""Issues #450 / #451: no skill may teach a model ID past its shutdown date.

Five skills taught ``claude-3-haiku-20240307`` and ``claude-3-5-sonnet-20241022``
as working, pin-this examples months after Anthropic retired them, and twice as
the ID to pin. ``traigent models --check`` passes a retired-but-well-formed ID,
so the example IDs themselves have to be current.

The table below carries each ID's **published shutdown date**, so the check turns
red on that date rather than months after it: an ID whose date has arrived may
not appear in a skill line unless that line marks it retired. IDs with a future
date are checked by ``test_future_shutdowns_have_a_usable_replacement`` and become
blocking on their own date without another edit here.

Dates read from the vendors' deprecation pages on 2026-10-19 (see #450, #451).
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# model id -> (shutdown date, the replacement this repo moved to)
SHUTDOWNS: dict[str, tuple[str, str]] = {
    # Anthropic, platform.claude.com/docs/en/about-claude/model-deprecations
    "claude-3-5-sonnet-20241022": ("2025-10-28", "claude-sonnet-5-5"),
    "claude-3-haiku-20240307": ("2026-04-20", "claude-haiku-5-5"),
    # OpenAI, developers.openai.com/api/docs/deprecations
    "gpt-4-turbo": ("2026-10-23", "gpt-5.6-sol"),
    "gpt-4o": ("2027-01-14", "gpt-5.6-sol"),
    "gpt-4o-mini": ("2027-01-14", "gpt-6-luna"),
    "gpt-4.1-mini": ("2027-01-14", "gpt-5.6-terra"),
}

# A line that already says the model is retired/dead is documentation of the
# retirement, not an example to copy.
RETIREMENT_MARKERS = ("retired", "shut down", "shutdown", "delisted", "deprecat")

# No carve-outs. The Bedrock example row names claude-3-sonnet-20240229, which is
# not in SHUTDOWNS, so it needs no exemption -- an inert allowlist entry only
# implies a protection that is not there.
ALLOWED_SUBSTRINGS: tuple[str, ...] = ()


def _scanned_files() -> list[Path]:
    paths = [ROOT / "README.md", ROOT / "docs" / "agent-setup" / "prompt.md"]
    for pattern in ("skills/**/*.md", "skills/**/*.sh"):
        paths.extend(
            p
            for p in sorted(ROOT.glob(pattern))
            if "/tests/" not in p.as_posix()
        )
    return paths


def _id_re(model_id: str) -> re.Pattern[str]:
    """Match the ID but not a longer ID that merely starts with it.

    ``gpt-4o`` must not match inside ``gpt-4o-mini``; ``\\b`` alone would,
    because ``-`` is a word boundary.
    """
    return re.compile(rf"(?<![\w.-]){re.escape(model_id)}(?![\w.-])")


def _hits(model_id: str) -> list[str]:
    pattern = _id_re(model_id)
    hits: list[str] = []
    for path in _scanned_files():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not pattern.search(line):
                continue
            if any(allowed in line for allowed in ALLOWED_SUBSTRINGS):
                continue
            if any(marker in line.lower() for marker in RETIREMENT_MARKERS):
                continue
            hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:120]}")
    return hits


def test_no_skill_teaches_a_model_past_its_shutdown_date() -> None:
    today = dt.date.today()
    violations: list[str] = []
    for model_id, (shutdown, replacement) in sorted(SHUTDOWNS.items()):
        if dt.date.fromisoformat(shutdown) > today:
            continue
        for hit in _hits(model_id):
            violations.append(
                f"{hit}\n    -> {model_id} shut down {shutdown}; use {replacement}"
            )
    assert not violations, "\n".join(violations)


def test_future_shutdowns_have_a_usable_replacement() -> None:
    """An ID still being taught must have somewhere to go before its date.

    Asserting the date is in the future would be a tautology -- the dict
    comprehension already filters on exactly that. The real question is whether
    an ID we are still shipping has a replacement that is not itself retiring.
    """
    today = dt.date.today()
    pending = {
        model_id: (replacement, len(_hits(model_id)))
        for model_id, (shutdown, replacement) in SHUTDOWNS.items()
        if dt.date.fromisoformat(shutdown) > today
    }
    assert pending, "every shutdown date has passed; the table needs new rows"
    for model_id, (replacement, occurrences) in sorted(pending.items()):
        assert replacement, model_id
        assert replacement not in SHUTDOWNS, (
            f"{model_id}: replacement {replacement!r} is itself on the shutdown list"
        )
        if occurrences:
            # Still taught somewhere, so the replacement has to be a plausible
            # model id we could swap in on the day -- not an empty string or a
            # note to self. (`assert replacement` above only rejects "".)
            # NOT _id_re(replacement).fullmatch(replacement): that regex is
            # built from re.escape(replacement), so it matches itself for every
            # string -- "note to self" included. Assert a real id shape.
            assert re.fullmatch(r"[a-z0-9][\w.\-/]*", replacement), (
                f"{model_id}: replacement {replacement!r} is not a model-id shape"
            )


def test_the_id_matcher_has_teeth() -> None:
    assert _id_re("gpt-4o").search('["gpt-4o", "x"]')
    assert not _id_re("gpt-4o").search('["gpt-4o-mini"]')
    assert not _id_re("claude-3-haiku-20240307").search(
        "bedrock/anthropic.claude-3-sonnet-20240229-v1:0"
    )
    assert _id_re("claude-3-haiku-20240307").search("`claude-3-haiku-20240307`")
