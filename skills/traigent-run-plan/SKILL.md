---
name: traigent-run-plan
description: "Build a Traigent run-plan WITH the user before EVERY optimization run by asking them, option by option, which to choose — objectives & weights, models, structural knobs + values, algorithm, trial budget, cost cap, execution mode. Never set any option silently. Render the plan, mock dry-run, then run only on the user's explicit go. Use before designing/launching any run."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.0"
---

# Traigent run-plan — build it WITH the user, before every run

The experience the user should have: **you ask, they choose.** Before every run you
walk the user through the run-plan **option by option**, get an explicit choice (or
an explicit "use the default"), render the plan, mock-dry-run it for free, and only
spend on the user's **go**. Never pick a parameter silently.

## Protocol (every run)
0. **If prior runs exist**, first present the next-run recommendations
   (`traigent-next-run`) and use them to PROPOSE this plan's models/knobs/weights —
   the user still confirms each.
1. **Render** a fresh run-plan from the template (all options present).
2. **Ask the user about EVERY option group** (use the host's interactive
   question UI; batch related options). Cover ALL of them:
   - **Objectives & weights** — accuracy / cost / latency / effort; the ACL weights
     (accuracy-first early, e.g. 0.80/0.15/0.05; raise the cost weight as usage grows).
   - **Models** — span tiers: premium + mid + low + open-source, incl. a full vendor
     ladder; route via OpenRouter/LiteLLM so cost is metered.
   - **Knobs** — the model knob + **≥3 structural knobs** (each value-set), every one
     injected at the real call site and verified (a declared-but-unwired knob is a no-op).
   - **Search** — algorithm (bayesian/tpe/optuna smart; grid/random local), trial
     budget (MAX_CONFIGS), plateau stopping, reps.
   - **Cost** — hard `BUDGET_USD` cap.
   - **Execution** — hybrid (online → cloud smart optimizer + portal) is the default;
     local-only only if explicitly chosen.
   - Plus the remaining SDK options (dataset, injection, privacy, fallback, …).
3. **Record** their answers in the plan, including the config-space **permutation
   count** (product of value-counts), and name the run self-descriptively
   (who · weights · problem-space · permutations · date).
4. **Mock dry-run** (free, no spend) → validate the pipeline, report the permutation
   count + estimated cost → **STOP**.
5. **Real run** only on the user's explicit **go**, with the cost cap set.

## Rules
- Surface ALL options every run; defaults are *confirmed*, not silent.
- **Order each option's choices lowest-latency / cheapest / smallest FIRST, and mark
  that first one "(Recommended)".** A first-time user should be able to accept the
  recommended defaults with quick clicks and not wait long for a result.
- **Goldilocks space size — ALWAYS keep the configuration space at ~several hundred
  permutations** (roughly 100–600). Below ~50 perms you've hand-built a tiny grid the
  optimizer can't add value to — that's *handing it the answer*, not optimizing. Above
  a few thousand, the trial budget barely scratches it. Keep it in this band.
- **ALWAYS state the permutation count, every time** — when you present the plan, when
  you launch the run, and when you report results. Repeat it; the perm count is how the
  user sees the size of the space the optimizer is searching (and whether you've
  over-collapsed it).
- **Always pair perms with trials, and frame the gap as the VALUE.** Smart algorithms
  (bayesian/tpe/optuna) do NOT run every permutation — they sample a *fraction* and learn
  from each trial to home in on the best (e.g. "**~18 trials explore a 108-perm space**" —
  about 1 in 6 — and plateau may stop sooner). Say **"explores an N-perm space in T
  trials,"** NEVER "runs/exhausts N permutations." Not brute-forcing the grid is the whole
  point — that's smart search vs. grid search.
- **Speed comes from FEWER TRIALS and cheap, low-latency models — NOT from shrinking
  the space.** A fast scout = a *several-hundred-perm* space sampled lightly (~10–15
  trials of cheap low-latency models, `direct` paths), so it lands in minutes AND still
  lets the optimizer search. NEVER make run 1 fast by collapsing the space to a handful
  of configs.
- **Don't over-prune between runs.** Keep the high-value knobs IN PLAY so the optimizer
  *discovers* the optimum; fix a knob to a prior winner ONLY on strong, repeated
  evidence (not a run that plateaued after a handful of trials), and when you do fix
  one, **say so and say why** (e.g. "repair fixed off — adds a 2nd call/latency"). Run 2
  adds the ceiling levers and keeps searching; it does not shrink to the run-1 winners.
- **Explain "injection" once, up front:** the user writes their agent ONCE; Traigent
  **injects** each trial's chosen knob values into it at runtime (read via
  `traigent.get_config()`), so a single function runs hundreds of configs — they never
  rewrite anything between trials. Name the specific knobs you're injecting.
- Encode discrete/integer knobs as string categoricals; `int()` at the call site.
- After the run, hand control to `traigent-next-run` (share the portal link + recommend).

## Before the user's FIRST run (onboarding)
If the user hasn't run an optimization yet, **ask whether they want to start with the
text2SQL example or jump straight to their own agent — and warmly recommend the example
first.** One fast scout run shows the whole loop end-to-end (build-plan-with-me → run →
portal link with accuracy + cost per config); pointing Traigent at their own agent
afterward is the exact same motions. The `traigent-text2sql-optimize` skill ships a
self-contained, runnable example (no data setup).

## The EXAMPLE vs. the customer's REAL agent — optimize differently
The text2SQL **example** uses a gentle teaching pace — a minimal run 1 (minor knobs),
then add structural knobs so a cheap model visibly leaps (see `traigent-text2sql-optimize`).
**That minimal-first pacing is for the example only** — it exists to build intuition.

A customer's **real agent is usually a given** (they already have a model and an
approach), so optimize for VALUE from the very first run — actively **nag** the user to:
- **Add model variety — span high / mid / low tiers AND ≥2 vendors.** Never optimize a
  single model in isolation. The biggest cost wins come from discovering that a cheaper
  model/vendor matches the one they started on. If they name one model, push back and
  propose a tiered, multi-vendor slate.
- **Include SIGNIFICANT (high-impact) knobs from run 1 — not just minor ones.** Don't burn
  the first run on temperature/format alone; bring the structural levers that actually move
  the metric (few-shot **selection**, schema/context representation, generation structure,
  output mode). **Keep them low-latency** — defer multi-call knobs (repair, candidate-voting,
  exec-guided self-correct) to a later run; they add latency for often-marginal early gains.
- Keep the space ~several hundred perms (Goldilocks) and **state the perm count**.

Net: the example *teaches* by starting small; a real engagement *delivers* by going broad
(models + vendors) and deep (significant, low-latency knobs) immediately.

## See also
`traigent-next-run` · `traigent-run-optimization` · `traigent-configuration-space` · `traigent-choose-metric`
