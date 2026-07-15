# SDK Version Matrix — behavior-delta facts

This file is the **single authoritative table** for SDK behavior-delta facts that
skills reference inline. Every inline stamp of one of these facts keeps its minimal
fact + version boundary locally (so a skill installed on its own stays comprehensible)
and points here with `see version-matrix: <fact_id>`. To restamp a fact when a new
SDK release changes it, edit **one row here** plus the canonical phrasing at the
pointer sites — `tests/contract/test_version_matrix.py` fails on dangling pointers,
dead rows, unreleased versions, and phrasing that diverges from the row's boundary.

Maintenance rules:

- `changed_in_version` must be a released SDK tag (see the static tag list in
  `tests/contract/test_version_matrix.py`) and must not exceed
  `sync_map.yml.current_released_sdk_version`.
- `issue_ref` uses public refs only (`Traigent/Traigent#…`).
- `canonical_phrasing` is the short form pointer sites carry; the full precise
  statement (lane caveats, what still holds) lives in `delta`.
- "after X" phrasing means the change ships in the first release **after** tag X
  (e.g. "after 0.22.0" = shipped in 0.23.0).

| fact_id | symbol/surface | delta | changed_in_version | issue_ref | canonical_phrasing |
|---|---|---|---|---|---|
| `latency-unit` | bare `metrics["latency"]` | Milliseconds on **every lane** since 0.23.0 (the first release after 0.22.0). Before 0.23.0 the lanes disagreed: the hybrid lane already reported ms, while the **local builtin** recorded seconds (1000x cross-lane disagreement). `execution_time` stays seconds on all versions. | 0.23.0 | Traigent/Traigent#1855, #1872 | bare `latency` is milliseconds on SDKs after 0.22.0 |
| `cost-unit` | bare `metrics["cost"]` | Per-trial TOTAL on every lane (local, hybrid, pruned) since 0.23.0, reconciling with `total_cost`; the per-example mean moved to `metrics["cost_per_example_mean"]`. On 0.22.0 and earlier, local runs reported `"cost"` as the per-example mean (~N× smaller than hybrid runs of the same config). | 0.23.0 | Traigent/Traigent#1853, #1869 | `"cost"` is the per-trial total on SDKs after 0.22.0 |
| `score-relocation` | `trial.score` / `metrics["score"]` | Since 0.22.0 (the first release after 0.21.3), `Trial.score` and `metrics["score"]` carry the primary objective's value; when a custom `scoring_function` owns "accuracy", the builtin exact-match scorer is recorded as `metrics["exact_match_default"]`. On 0.21.3 and earlier the builtin exact-match value appeared as `metrics["score"]`. | 0.22.0 | Traigent/Traigent#1845, #1849 | `score` mirrors the primary objective on SDKs after 0.21.3 |
| `tenacity-bundling` | `tenacity` dependency | `tenacity>=8.1.0` is a core dependency since 0.21.3, so litellm's `*_with_retries` helpers work on a clean install. On 0.21.2 and earlier `tenacity` is NOT in traigent's dependency closure: the retry path dies with `ModuleNotFoundError: tenacity` and the failed call scores 0. | 0.21.3 | Traigent/Traigent#1824, #1825 | `tenacity` is bundled since 0.21.3 (0.21.2 and earlier lack it) |
| `smart-selector-exec` | `algorithm="bayesian"` etc. (named smart selectors) | Since 0.20.1, on authenticated connected runs the supported named smart selectors (`bayesian`, `tpe`, `optuna`, `optuna_tpe`, `optuna_random`) bind to the typed backend Optuna strategy and are serialized on session creation; unsupported smart names (`nsga2`, `cmaes`) fail fast before session creation with a capability message. On 0.20.0 no named smart selector executed end-to-end. On every version: `offline=True` + any smart name raises `ConfigurationError` at decoration time, and the local optimizer registry supports only `grid`/`random` (`OptimizationError` for smart names). | 0.20.1 | Traigent/Traigent#1752, #1758 | named smart selectors execute on connected runs since 0.20.1 |
| `algorithms-cli` | `traigent algorithms` CLI | Since 0.20.1 the CLI lists the full public selector surface — `auto`, the local names, and the cloud-routed smart names — with a local/connected availability column. On 0.20.0 it omitted `auto` and the smart names. | 0.20.1 | Traigent/Traigent#1751, #1759 | `traigent algorithms` lists auto + smart names since 0.20.1 |
| `backend-url` | `traigent plan` / `traigent next-steps` URL resolution | Since 0.20.0 these commands resolve the backend URL as flag → `TRAIGENT_BACKEND_URL` → the URL stored by `traigent auth login` → the local default. On 0.19.x and earlier they ignored the stored auth-login URL and always defaulted to localhost unless the flag or env var was passed. | 0.20.0 | Traigent/Traigent#1721 | `plan`/`next-steps` honor the stored auth-login URL since 0.20.0 |
| `exampleinsights-deprecation` | `from traigent.analytics import ExampleInsightsClient` | The core `traigent.analytics` import emits a `DeprecationWarning` pointing at the `traigent-analytics` plugin — present since 0.13.x (verified at tag v0.13.0; the module marks the deprecation as of 0.9.0). The plugin does not export this class, so the core import (or the deep import `traigent.analytics.example_insights`) remains the working path. | 0.13.0 | — | core `ExampleInsightsClient` import warns deprecated since 0.13.x |
