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

Don't end this session yet — steps 2–4 still run in it. Once setup is finished, tell the user to
start a new Codex session (the reminder at the end of step 4): the `traigent:*` skills load when a
session starts (verified on Codex CLI 0.160.0), so don't count on them before then.

If you mount the skills into the project instead of installing the plugin (e.g. copied to
`.github/skills/<name>/SKILL.md`), copy the ready-made stanza from `templates/AGENTS.md.example` in
the traigent-skills repo into this project's `AGENTS.md`. Codex may not open mounted skill files on
its own — in a 20-cell simulation wave, 7 of 7 Codex agents ignored mounted skills.

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

- **If a key was pasted into this prompt** (a portal handed it to you), write it to this project's
  `.env` only after each check below has positively passed — they are based on the `.env` checks
  in the `traigent-setup-quickstart` skill's "Using a .env File" section, made fail-closed here.
  Any other result — another exit code, unexpected output, or a check you can't run — is a stop.
  A stop here does not end setup: don't add the key, tell the user which check failed so they can
  add it themselves, continue with step 4 (the keyless mock run), and render the summary box's
  `⧗  TRAIGENT_API_KEY` line.
  1. `.env` is a regular file, not a symbolic link: first, if `test -L .env` exits 0, `.env` is a
     symbolic link — even a broken one, or one pointing at a tracked config file — so stop without
     creating anything. Otherwise create it if it's missing, preserving any existing content, then
     check `test -f .env && ! test -L .env` exits 0.
  2. On macOS/Linux, and only after step 1 passed, set mode 0600 (`chmod 600 .env`).
  3. The repository status is known: run `LC_ALL=C git rev-parse --is-inside-work-tree`. If it
     prints `true`, run steps 4 and 5. Skip steps 4 and 5 only if it fails with exactly
     `fatal: not a git repository (or any of the parent directories): .git` — there is nothing to
     track or ignore. Any other result (e.g. a "dubious ownership", "parent up to mount point",
     permission or config error) is a stop.
  4. `.env` is untracked: `git ls-files --error-unmatch -- .env` exits 1. Git prints an
     `error: pathspec` line and a hint — that is the expected, passing answer; judge by the exit
     code, not the message. Exit 0 means `.env` is tracked: stop.
  5. `.env` is git-ignored: `git check-ignore -q -- .env` exits 0. If it exits 1, add `/.env` once
     to the `.gitignore` in the same directory as `.env` and re-run; it must then exit 0.
  6. Then add the key as `TRAIGENT_API_KEY` without printing it, and continue.
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

The skills from step 1 may not be loaded in this session yet, so read the block from disk; reading a
file does not need the skill loaded in this session. Search your agent's config directory (e.g.
`~/.claude`, `~/.codex`, `~/.copilot`) or this project's skills folder for a path ending in
`traigent-setup-quickstart/SKILL.md`. Prefer the installed plugin or skill directory over a
marketplace checkout; if several copies exist, use the one step 1 just installed, or the newest
installed version if you can't tell which that is. Use SKILL.md's
"Literal First Run" block or the identical `references/literal-quickstart.sh` beside it. If you
can't find either, stop and report.

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

Right below the box, remind the user of the last gate for the skills installed in step 1: in Claude
Code they activate only after `/reload-plugins` (or restarting the session); in Codex, start a new
session, since the skills load when a session starts; other agents may need a restart too.

## Next

First confirm the reload (or new session) above actually happened — until then, don't count on the
`traigent:*` skills.

Point the user at the `traigent-setup-quickstart` and `traigent-boost-agent` skills to optimize a
real function against their own evaluation dataset. Always mock/dry-run first; run a real (paid)
optimization only on the user's explicit go — using a write-capable key, since cloud optimization
needs `experiments:write`.
