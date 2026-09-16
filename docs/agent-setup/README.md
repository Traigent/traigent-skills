# Agent-setup prompt

[`prompt.md`](prompt.md) is the **canonical, versioned, agent-agnostic setup prompt** for
onboarding a coding agent to Traigent. It is authored here (in the skills repo, next to the skills
it references) and served publicly at **<https://traigent.ai/agent-setup/prompt.md>**.

## Who copies it

Two "Connect your agent" buttons put this exact prompt on the user's clipboard, ready to paste into
Claude Code, Codex, Cursor, Copilot, or any other coding agent:

- **traigent.ai** (marketing site, `traigent-web`) — as of commit `e52a89e7` (2026-08-20) no longer
  serves this file: `/agent-setup/prompt.md` there now serves a different, intentionally short
  "Guided First Run" prompt. This bullet is kept for history; see the Bump protocol section below
  before assuming this copy still needs to track `prompt.md`.
- **The Traigent portal** (`TraigentFrontend`) — vendors the same canonical text in
  `src/components/onboarding/agentSetupPrompt.ts` and injects the **freshly issued API key** into
  the "Add your Traigent API key" section before copying.

## How it works when pasted

The prompt opens with a consent-scoped autonomous directive (the user authorized the agent by
pasting it), then walks the agent through: installing the Traigent skills for its own agent family,
installing the SDK, wiring `TRAIGENT_API_KEY` into `.env` (never printing the value), and verifying
end-to-end with the keyless mock quickstart from the
[`traigent-setup-quickstart`](../../skills/traigent-setup-quickstart/) skill — finishing with a
ranked results table and a success box.

## Editing

Edit `prompt.md` here; the Traigent portal's vendored copy above is a downstream copy (the
traigent-web copy is not, see above). When you change a command, verify it against the repo
[`README.md`](../../README.md) (skill install commands) and the `traigent-setup-quickstart`
SKILL.md (the mock quickstart), and update the vendored portal copy so the two do not drift.
Automating that sync (e.g. the portal fetching this file at build time) is a follow-up.

## Bump protocol (pinned checksum guard)

`prompt.md`'s canonical body is pinned by a checksum in [`provenance.json`](provenance.json) —
schema `agent-setup-prompt-provenance/v1`, with `doc_hash` (the first 16 hex characters of the
file's SHA-256 — the same convention as a skill's `provenance.json`, see
`tests/contract/test_provenance.py`) and an `entries` list recording, for each bump, `edit_id`,
`doc_before_hash`/`doc_after_hash`, and a `note` explaining why. `tests/contract/test_agent_setup_prompt_sync.py`
fails whenever `prompt.md` changes without `doc_hash` being bumped to match. That's deliberate:
manual sync-notes are not durable (the drift that motivated this guard — issue #234, and this list
itself has drifted once already, see below), so every edit here is forced through this checklist —
**this is the one place the downstream-copy list is kept**; other files in this guard (the test,
the helper script) point back here instead of repeating it:

1. Make the content change in `prompt.md`.
2. Recompute the pinned checksum and record why:
   ```bash
   python3 tools/contract/update_agent_setup_prompt_hash.py --note "<what changed and why>"
   ```
   (`--check` reports staleness without writing, e.g. for CI.)
3. Run `pytest tests/contract/test_agent_setup_prompt_sync.py` to confirm the checksum is green.
4. Re-sync known downstream copies, in a separate PR in each repo with the same content adapted to
   its format:
   - **`TraigentFrontend`** `src/components/onboarding/agentSetupPrompt.ts` — hand-synced to this
     file as of the genesis entry in `provenance.json`. This repo cannot verify that copy directly
     (an exact byte match isn't achievable there either: the portal's copy is split across several
     template pieces with a freshly issued API key injected into one, not one flat file). The
     realistic guard on that side is a local test pinning a checksum of *its own* constant plus the
     `doc_hash` it was last synced against, so a source-side bump here becomes visibly stale there
     too — that guard doesn't exist yet; adding it is follow-up work with no tracking issue filed
     yet.
   - **`traigent-web`** `public/agent-setup/prompt.md` — **not currently a copy of this file.** As
     of commit `e52a89e7` (2026-08-20), `traigent.ai` serves a different, intentionally short
     "Guided First Run" prompt instead (confirm with
     `curl https://traigent.ai/agent-setup/prompt.md` before assuming otherwise). Do not push a
     re-sync there on the strength of this document alone — the two prompts may have deliberately
     diverged; check with that repo's history first.

This repo's guard only pins *this* copy, and only forces the checklist above to run — it cannot
verify that either downstream copy was actually updated, or that the list above is still accurate
(it has gone stale before).
