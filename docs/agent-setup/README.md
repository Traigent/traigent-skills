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
