# Skill-to-SDK Sync Map

When SDK source files change (in the [`Traigent`](https://github.com/Traigent/Traigent) Python SDK repo or [`traigent-js`](https://github.com/Traigent/traigent-js) JavaScript/TypeScript SDK repo), review the corresponding skills here for accuracy.

| Skill | SDK Source Dependencies |
|-------|----------------------|
| `traigent-quickstart` | `docs/getting-started/*`, `pyproject.toml`, `examples/quickstart/` |
| `traigent` | `traigent/api/decorators.py`, `traigent/utils/env_config.py` (mock/offline flags), `traigent/core/optimized_function.py` (optimize/optimize_sync) |
| `traigent-js` | `traigent-js/src/optimization/*`, `traigent-js/src/core/context.ts`, `traigent-js/src/seamless/*`, `traigent-js/src/integrations/*`, `traigent-js/src/routing/*`, `traigent-js/README.md`, `traigent-js/docs/*` |
| `traigent-configuration-space` | `traigent/api/parameter_ranges.py`, `traigent/api/constraint_builders.py`, `docs/user-guide/tuned_variables.md` |
| `traigent-decorator-setup` | `traigent/api/decorators.py` (EvaluationOptions, InjectionOptions, ExecutionOptions), `docs/user-guide/injection_modes.md` |
| `traigent-run-optimization` | `traigent/core/optimized_function.py` (optimize/optimize_sync), `traigent/core/orchestrator.py`, `traigent/config/parallel.py` |
| `traigent-analyze-results` | `traigent/api/types.py` (OptimizationResult, TrialResult, StopReason), `traigent/core/optimized_function.py` (apply_best_config) |
| `traigent-integrations` | `traigent/integrations/*`, `docs/architecture/integrations-inventory.md` |
| `traigent-debugging` | `traigent/utils/exceptions.py`, `traigent/utils/env_config.py` |
| `traigent-structural-spine` | `traigent/api/decorators.py`, `traigent/api/parameter_ranges.py`, `traigent/api/constraint_builders.py`, `docs/user-guide/tuned_variables.md` |
| `traigent-composite-knobs` | `traigent/knobs/patterns.py`, `traigent/knobs/runtime.py`, `traigent/knobs/telemetry.py`, `examples/advanced/composite-knobs/*`, `docs/traceability/concepts/composite-knobs.md` |
| `show-significant-tuned-variables` | `traigent/utils/importance.py` (ParameterImportanceAnalyzer), `traigent/utils/insights.py` (get_optimization_insights), optimization trial artifact schema |
