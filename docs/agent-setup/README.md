# Agent-setup prompt

[`prompt.md`](prompt.md) is the **canonical, versioned, agent-agnostic setup prompt** for
onboarding a coding agent to Traigent. It is authored here (in the skills repo, next to the skills
it references) and served publicly at **<https://traigent.ai/agent-setup/prompt.md>**.

## Who copies it

Two "Connect your agent" buttons put this exact prompt on the user's clipboard, ready to paste into
Claude Code, Codex, Cursor, Copilot, or any other coding agent:

- **traigent.ai** (marketing site, `traigent-web`) — serves this file verbatim at
  `/agent-setup/prompt.md` and copies the **keyless** variant (the agent creates a key from the
  portal itself). Keep the served copy in sync with this source file.
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

Edit `prompt.md` here; the two consumers above are downstream copies. When you change a command,
verify it against the repo [`README.md`](../../README.md) (skill install commands) and the
`traigent-setup-quickstart` SKILL.md (the mock quickstart), and update the vendored portal copy so
the two do not drift. Automating that sync (e.g. the portal fetching this file at build time) is a
follow-up.

## Bump protocol (pinned checksum guard)

`prompt.md`'s canonical body is pinned by a checksum in [`provenance.json`](provenance.json)
(`doc_hash`, the first 16 hex characters of the file's SHA-256 — the same convention as a skill's
`provenance.json`, see `tests/contract/test_provenance.py`). `tests/contract/test_agent_setup_prompt_sync.py`
fails whenever `prompt.md` changes without that checksum being bumped. That's deliberate: manual
sync-notes between the three copies of this prompt are not durable (the drift that motivated this
guard — issue #234), so every edit here is forced through this checklist:

1. Make the content change in `prompt.md`.
2. Recompute the pinned checksum and record why:
   ```bash
   python3 tools/contract/update_agent_setup_prompt_hash.py --note "<what changed and why>"
   ```
   (`--check` reports staleness without writing, e.g. for CI.)
3. Re-sync the two downstream copies to match, in the same wave (separate PRs, same content
   adapted to each format):
   - `TraigentFrontend`: `src/components/onboarding/agentSetupPrompt.ts`
   - `traigent-web`: `public/agent-setup/prompt.md`
4. Run `pytest tests/contract/test_agent_setup_prompt_sync.py` to confirm the checksum is green.

This repo's guard only pins *this* copy. Each consumer repo needs its own local test asserting its
vendored/served copy matches this pinned checksum (cross-repo CI fetches to compare all three live
are brittle) — that guard does not exist yet in either `TraigentFrontend` or `traigent-web` as of
this protocol landing; adding it is tracked outside `traigent-skills`.
