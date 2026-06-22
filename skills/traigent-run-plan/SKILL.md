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
- Encode discrete/integer knobs as string categoricals; `int()` at the call site.
- After the run, hand control to `traigent-next-run` (share the portal link + recommend).

## See also
`traigent-next-run` · `traigent-run-optimization` · `traigent-configuration-space` · `traigent-choose-metric`
