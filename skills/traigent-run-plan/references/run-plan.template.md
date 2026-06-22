# Traigent — Run Plan (TEMPLATE)

**Copy this file for EVERY run and fill it out _before_ you run.** It surfaces
**every** SDK-configurable option so nothing is chosen for you. Your coding
assistant must ASK you about ALL of them (skill `traigent-run-plan`) — accept the
shown default or choose — and may never set any option silently. Save the filled
copy with the run (P6), e.g. `run-plan_<RUN_NAME>.md`.

Format: `KEY = value   # allowed | what it does`. Concrete values are DEFAULTS you
may change; `<FILL: ...>` you MUST set.

```
# ── A. Run identity ──────────────────────────────────────────────────────────
RUN_NAME        = <FILL: name_ACL_<a>_<c>_<l>_<space>_<perms>perms_YYYYMMDD>
PROBLEM_SPACE   = <FILL: txt2sql | RAG-QA | summarization | classification | …>
AGENT           = <FILL: the agent entry function OR service endpoint>
EXPERIMENT_NAME = <FILL: portal experiment name; usually = RUN_NAME>

# ── B. Objectives (KPIs) ─────────────────────────────────────────────────────
OBJECTIVES      = <FILL: subset/order of: accuracy, cost, latency, effort>
ACL_WEIGHTS     = <FILL: one per objective, same order, ~sum 1.0>
ORIENTATIONS    = accuracy=maximize, cost=minimize, latency=minimize, effort=minimize

# ── C. Dataset & scoring ─────────────────────────────────────────────────────
DATASET         = <FILL: eval set (inputs + expected); fixed, seeded, no leakage>
SCORING         = <FILL: objective metric (execution/exact-match), not an LLM judge>
METRICS_EMITTED = accuracy, cost, latency

# ── D. Models (biggest cost lever, P1) ───────────────────────────────────────
MODELS          = <FILL: ids you have keys for; premium + mid + low + open-source>

# ── E. Knobs (model + ≥3 structural, P2; each injected & verified, P9) ────────
KNOBS           = <FILL: one per line, e.g. temperature=0.0,0.2,0.4; fewshot_k=0,2,4; …>
KNOBS_EXTRA     = none           # add/drop structural knobs
# permutation count = product of value-counts across MODELS + all knobs

# ── F. Search strategy ───────────────────────────────────────────────────────
ALGORITHM       = <FILL: auto|bayesian|tpe|optuna (online smart) | grid|random (local)>
MAX_CONFIGS     = <FILL: trials to sample>
TIMEOUT         = none           # wall-clock seconds cap, or none
PLATEAU_WINDOW  = <FILL: e.g. 8, or 0 = off>
PLATEAU_EPSILON = <FILL: e.g. 0.005>
STRATEGY        = none
STRATEGY_PARAMS = none

# ── G. Repetition & sampling ─────────────────────────────────────────────────
REPS_PER_TRIAL     = 1           # repeats per config
REPS_AGGREGATION   = mean        # mean | median | min | max
MAX_TOTAL_EXAMPLES = none        # cap evals across the run, or none
SAMPLES_INCLUDE_PRUNED = true
PARALLELISM        = auto        # auto | <int> concurrent trials

# ── H. Cost / budget (P10) ───────────────────────────────────────────────────
BUDGET_USD      = <FILL: hard cost cap>
COST_APPROVED   = true

# ── I. Execution selector (ExecutionOptions) ─────────────────────────────────
OFFLINE          = false          # DEFAULT. false = online, portal-tracked | true = local zero-egress
EXECUTION_OPTIONS = ExecutionOptions(offline=OFFLINE)
CLOUD_FALLBACK_POLICY = auto      # auto | never
LOCAL_STORAGE_PATH = default
SAVE_TO         = none
MINIMAL_LOGGING = true
PROGRESS_BAR    = true

# ── J. Config injection (InjectionOptions, P9) ───────────────────────────────
INJECTION_MODE  = context        # context | parameter | seamless
CONFIG_PARAM    = none
INJECTION_OPTIONS = InjectionOptions(injection_mode=INJECTION_MODE, config_param=CONFIG_PARAM)
AUTO_OVERRIDE_FRAMEWORKS = false

# ── K. Best-config reuse ─────────────────────────────────────────────────────
DEFAULT_CONFIG    = baseline
AUTO_LOAD_BEST    = false
LOAD_FROM         = none
CONFIG_ID         = none
BEST_CONFIG_SOURCE = off          # off | portal | local

# ── L. Constraints ───────────────────────────────────────────────────────────
CONSTRAINTS        = none
SAFETY_CONSTRAINTS = none

# ── M. Advanced (leave none unless needed) ───────────────────────────────────
EFFECTUATION   = false            # apply the winning config back to the agent
PROMPT_REWRITE = none
GROW_DATASET   = none
SKILL_TRAIN    = none
AGENTS         = none
TVL            = none

# ── N. External service adapter (optional) ───────────────────────────────────
SERVICE_ENDPOINT    = none
SERVICE_BATCH_SIZE  = 1
SERVICE_PARALLELISM = 1
SERVICE_KEEP_ALIVE  = true

# ── O. Mock dry-run ──────────────────────────────────────────────────────────
MOCK_BASE_ACCURACY = 0.75
MOCK_VARIANCE      = 0.25

# ── Carry-forward ────────────────────────────────────────────────────────────
CARRY_FORWARD   = <FILL after a run: what won/lost, knobs that mattered, next weights>
```

## How to use this
1. Copy → `run-plan_<RUN_NAME>.md`.
2. Your assistant ASKS you about EVERY option above (skill `traigent-run-plan`) —
   choose or confirm the default for each. None are set silently.
3. Paste the run prompt (Setup Guide Part F) — it consumes this plan.
4. Keep the filled file with the run as its record.
