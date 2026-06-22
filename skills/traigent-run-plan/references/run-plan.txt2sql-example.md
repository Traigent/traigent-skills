# Traigent — Run Plan · txt2SQL SPIDER example  (READY TO RUN)
#
# Pre-filled so you get instant gratification on a known space — run it as-is to
# see the whole loop. The ONLY thing you may want to change is MODELS (marked
# below): keep the default recommendation, or swap in models you have keys for.

```
# --- Run identity -----------------------------------------------------------
RUN_NAME      = {your_name}_ACL_80_15_05_txt2sql_{YYYYMMDD-HHMM}   # <- just set {your_name}
PROBLEM_SPACE = txt2sql
AGENT         = SPIDER text2SQL example agent (set up by the example / icebreaker skill)

# --- What to optimize (KPIs) ------------------------------------------------
OBJECTIVES    = accuracy, cost, latency
ACL_WEIGHTS   = 0.80, 0.15, 0.05        # accuracy-first; a cheaper near-equal config can still win

# --- What to try ------------------------------------------------------------
DATASET       = SPIDER, 30 questions — bundled with the example (objective execution-match scoring)

MODELS        = openrouter/openai/gpt-4o-mini, openrouter/qwen/qwen3-coder:free
#  ^^^ DEFAULT RECOMMENDATION: one low-cost (gpt-4o-mini) + one open-source (qwen, free tier).
#  <-- CHANGE ONLY THIS LINE if you want different models (use ids you have keys for in .env;
#      e.g. add a mid/premium tier). Everything else can stay as-is.

KNOBS         = # Traigent's recommended txt2SQL structural knobs — INJECTED into the example agent:
                temperature      = 0.0, 0.2, 0.4
                fewshot_k        = 0, 2, 4
                candidate_count  = 1, 3
                schema_context   = ddl_fk, ddl_fk_rows
                repair           = off, on
MAX_CONFIGS   = 20
BUDGET_USD    = 1.0
ALGORITHM     = bayesian
SDK_PARAMS    = plateau stopping on
OFFLINE       = false                   # DEFAULT: online, portal-tracked. true ONLY if explicitly chosen.
EXECUTION_OPTIONS = ExecutionOptions(offline=OFFLINE)
INJECTION_MODE = context

# --- Carry-forward ----------------------------------------------------------
#   First run — nothing yet. After it converges, note what won / lost here; you'll
#   reuse this same run-plan pattern on your OWN agent (Part D onward).
```

## Run it
1. Set `{your_name}` in `RUN_NAME` (and change `MODELS` only if you want models other than the default).
2. Paste the txt2SQL example prompt from the Setup Guide ("break the ice with the txt2SQL example first"). It uses this file.
3. Watch it converge in your portal — then point Traigent at your own agent.
