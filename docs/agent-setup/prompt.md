# Connect your coding agent to Traigent

You are a coding agent. Complete these steps yourself by running the commands directly — don't
ask the user to run them; they authorized this by pasting this prompt from traigent.ai or their
Traigent portal. Work in the current project directory and install into **this project**, never
globally (do not pass `--global`), unless the user tells you otherwise. **Never print, echo, or
log the key value** — reference `TRAIGENT_API_KEY` by name only.

Do the steps in order. If a step fails, stop and report it rather than continuing.

## 1. Install the Traigent agent skills

The skills teach you to drive the Traigent SDK — curate an evaluation dataset, wire and audit
evaluators, run cost-aware optimizations, and analyze the results. Install the ones for the agent
you are:

### Claude Code

```bash
claude plugin marketplace add Traigent/traigent-skills
claude plugin install traigent@traigent
```

Inside an interactive Claude Code session the equivalent is the slash commands
`/plugin marketplace add Traigent/traigent-skills` then `/plugin install traigent@traigent`. After
installing, tell the user to run `/reload-plugins` (or restart the session) so the `traigent:*`
skills load.

### OpenAI Codex

```bash
codex plugin marketplace add https://github.com/Traigent/traigent-skills
codex plugin add traigent@traigent
```

**Important — Codex does not auto-discover a skills directory the way Claude Code does; it only
reads `AGENTS.md`.** In a 20-cell simulation wave, 7 of 7 Codex agents ignored mounted skills for
exactly this reason, **and this applies to Codex on VS Code too**. If you mount the skills into the
project (e.g. copied to `.github/skills/<name>/SKILL.md`) instead of using the plugin above, you
must copy the ready-made stanza from `templates/AGENTS.md.example` in the traigent-skills repo into
this project's `AGENTS.md`, or Codex will not open them.

### GitHub Copilot CLI

```bash
copilot plugin marketplace add Traigent/traigent-skills
copilot plugin install traigent@traigent
```

### Cursor, Windsurf, Gemini CLI, and 30+ other agents

Use the cross-agent installer — it copies each skill into the right location for your agent and
keeps it in sync:

```bash
npx -y skills add Traigent/traigent-skills --skill '*'
```

`npx -y skills add Traigent/traigent-skills --list` lists the individual skills if you want a
smaller footprint; `npx skills update` updates them later. See the
[traigent-skills README](https://github.com/Traigent/traigent-skills) for per-agent specifics.

## 2. Install the Traigent SDK

Install into a project virtualenv — on modern Debian/Ubuntu/Fedora a bare `pip install` into the
system Python is refused under PEP 668 (`externally-managed-environment`):

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install "traigent[recommended]"
```

Pin the floor to avoid the PyPI placeholder release: `pip install "traigent[recommended]>=0.19"`.
If pip prints `traigent 0.0.1 does not provide the extra ...`, that is **fatal** — you installed
the placeholder package; reinstall with `python -m pip install --upgrade "traigent>=0.19"`.

Building in JavaScript/TypeScript instead? The Traigent JS SDK is **not published on public npm
yet** — use the source/link flow in the `traigent-js` skill until it ships.

## 3. Add your Traigent API key

Backend-connected features (the default cloud smart optimizer, dataset synthesis, analytics, and
portal result history) need `TRAIGENT_API_KEY`, and the key must be **read + write**
(`experiments:write`): with a read-only key the cloud optimizer and dataset synthesis get a 403 and
the SDK silently falls back to local — the run never reaches portal history.

- **If a key was pasted into this prompt** (a portal handed it to you), add it to this project's
  `.env` as `TRAIGENT_API_KEY` (don't echo it) and continue.
- **Otherwise**, prepare `.env` first, then send the user to create a key:
  1. Create this project's `.env` if it's missing, preserving any existing content. If
     `TRAIGENT_API_KEY` already has a non-empty value, keep it (don't overwrite) and skip creating a
     new key — but it must be **read + write** (`experiments:write`); if a later cloud run 403s, that
     key is read-only and needs replacing via the Full-access flow below. Otherwise add the line
     `TRAIGENT_API_KEY=` with the value left blank, confirm `.env`
     is git-ignored, and print its **absolute path**. Then set `$ENV` to that path and best-effort
     open it in a **standalone, detached** editor — Linux: `setsid -f gnome-text-editor "$ENV"` (or
     the first of `kate`/`gedit`/`xed`/`mousepad` that exists; last resort `xdg-open "$ENV"`);
     macOS: `open -t "$ENV"`; Windows: `start "" notepad "<that absolute path>"`. Do **not** open it through the
     user's IDE (`code`/`cursor` can hijack or crash a window); if no window appears, have the user
     open the printed path themselves.
  2. Tell the user: to create a key, register at <https://portal.traigent.ai/register> (or log in
     if already registered), open the **account (avatar) menu → API Keys**, click **Create API
     Key**, and choose the **Full access** (read + write) preset — the default **Read-only** preset
     can't run the cloud optimizer or dataset synthesis. The portal's one-click **Get optimization
     API key** flow also works; it already issues a read + write key. Portal keys use the `uk_`
     prefix.
  3. Have the user paste the key after `TRAIGENT_API_KEY=` in the open `.env` and save — **never
     ask the user to paste the key into the chat**; it would land in the transcript and logs.

Never print, echo, or log the key value; reference it only by the name `TRAIGENT_API_KEY`, and make
sure `.env` is git-ignored **before** any key goes into it. The mock verification in step 4 needs
**no key**, so you can run that first and add the key after.

## 4. Verify — run the keyless mock quickstart

Prove the whole pipeline end-to-end at **zero cost and zero egress** using the
`traigent-setup-quickstart` skill's **"Literal First Run"** block. It exports
`TRAIGENT_OFFLINE_MODE=true`, writes `ticket_eval.jsonl` and `ticket_classifier.py` (a
`@traigent.optimize`-decorated classifier that calls `enable_mock_mode_for_quickstart()` and passes
`offline=True`), and runs `classify_ticket.optimize_sync(max_trials=4, algorithm="grid")`. Run it
in the foreground and wait for the final line `TRAIGENT-DRY-RUN-OK`.

Then show the user the ranked results — the best config and the per-trial scores, for example:

```text
Rank  model         temperature   accuracy
1     gpt-4o        0.0           0.88
2     gpt-4o        0.7           0.85
3     gpt-4o-mini   0.0           0.68
4     gpt-4o-mini   0.7           0.65
Best config: {'model': 'gpt-4o', 'temperature': 0.0}
```

(The numbers are canned mock values — the point is that the optimization loop ran, not the scores.)

Finally, print a summary box:

```text
╭───────────────────────────────────────────────╮
│  Traigent is connected                          │
│                                                 │
│   ✓  Agent skills installed                     │
│   ✓  SDK installed  (traigent[recommended])     │
│   ✓  Mock quickstart passed  (DRY-RUN-OK)       │
│   ✓  TRAIGENT_API_KEY set in .env               │
╰───────────────────────────────────────────────╯
```

If the key is not set yet, render that last line (keeping it within the box width) as
`⧗  TRAIGENT_API_KEY — add a Full-access key` instead of a check.

Right below the box, remind the user of the last gate: the skills installed in step 1 don't load
into the current session — in Claude Code they activate only after `/reload-plugins` (or restarting
the session); other agents may need a restart too.

## Next

First confirm the reload above actually happened — the `traigent:*` skills stay inert until then.

Point the user at the `traigent-setup-quickstart` and `traigent-boost-agent` skills to optimize a
real function against their own evaluation dataset. Always mock/dry-run first; run a real (paid)
optimization only on the user's explicit go — using a write-capable key, since cloud optimization
needs `experiments:write`.
