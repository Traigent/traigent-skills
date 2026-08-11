<!-- GENERATED from sync_map.yml by tools/contract/render_sync_map.py — edit sync_map.yml -->

# Skill-to-SDK Sync Map

When SDK source files change (in the [`Traigent`](https://github.com/Traigent/Traigent) Python SDK repo or [`traigent-js`](https://github.com/Traigent/traigent-js) JavaScript/TypeScript SDK repo), review the corresponding skills here for accuracy.

| Skill | SDK Source Dependencies |
|-------|----------------------|
| `traigent-setup-quickstart` | `traigent/utils/cost_calculator.py`, `traigent/core/cost_estimator.py`, `docs/getting-started/*`, `docs/features/safety-gates.md`, `pyproject.toml`, `examples/quickstart/` |
| `traigent-js` | `traigent-js/src/optimization/*`, `traigent-js/src/core/context.ts`, `traigent-js/src/seamless/*`, `traigent-js/src/integrations/*`, `traigent-js/src/routing/*`, `traigent-js/README.md`, `traigent-js/docs/*` |
| `traigent-optimize-config-space` | `traigent/api/parameter_ranges.py`, `traigent/api/constraint_builders.py`, `docs/user-guide/tuned_variables.md` |
| `traigent-setup-decorator` | `traigent/api/decorators.py`, `traigent/utils/cost_calculator.py`, `traigent/core/cost_estimator.py`, `docs/user-guide/injection_modes.md`, `docs/features/safety-gates.md` |
| `traigent-optimize-run` | `traigent/core/optimized_function.py`, `traigent/core/orchestrator.py`, `traigent/config/parallel.py` |
| `traigent-analyze-results` | `traigent/api/types.py`, `traigent/core/optimized_function.py` |
| `traigent-setup-integrations` | `traigent/integrations/*`, `docs/architecture/integrations-inventory.md` |
| `traigent-debugging` | `traigent/utils/exceptions.py`, `traigent/utils/env_config.py` |
| `traigent-optimize-composite-knobs` | `traigent/knobs/patterns.py`, `traigent/knobs/runtime.py`, `traigent/knobs/telemetry.py`, `examples/advanced/composite-knobs/*`, `docs/traceability/concepts/composite-knobs.md` |
| `traigent-boost-agent` | `traigent/config_generator/__init__.py`, `traigent/config_generator/catalog/tvar_catalog.v1.json`, `traigent/api/decorators.py`, `traigent/core/optimized_function.py`, `traigent/knobs/patterns.py`, `traigent/knobs/runtime.py`, `traigent/knobs/telemetry.py`, `traigent/utils/insights.py`, `traigent/utils/importance.py`, `traigent/utils/env_config.py`, `traigent/utils/cost_calculator.py`, `traigent/core/cost_estimator.py`, `traigent/analytics/example_insights.py`, `traigent/testing/*` |
| `traigent-analyze-variable-importance` | `traigent/utils/importance.py`, `traigent/utils/insights.py`, `optimization trial artifact schema` |
| `traigent-dataset-curate` | `traigent/generation/*`, `traigent/analytics/example_insights.py`, `traigent/evaluators/base.py`, `traigent/api/decorators.py`, `traigent/core/optimized_function.py`, `traigent/testing/*` |
| `traigent-eval-choose-metric` | `traigent/api/decorators.py`, `traigent/core/optimized_function.py` |
| `traigent-eval-build` | `traigent/api/decorators.py`, `traigent/api/types.py`, `traigent/evaluators/base.py`, `traigent/evaluators/local.py`, `traigent/evaluators/hybrid_api.py` |
| `traigent-eval-audit` | `traigent/api/decorators.py`, `traigent/api/types.py` |
| `traigent-ci-safety-gate` | `traigent/api/decorators.py`, `traigent/api/safety.py`, `traigent/tvl/promotion_gate.py`, `traigent/tvl/models.py`, `traigent/tvl/__main__.py` |
| `traigent-analyze-guidance` | `traigent/api/decorators.py`, `traigent/generation/*`, `traigent/core/optimized_function.py`, `traigent/api/types.py`, `traigent/utils/insights.py`, `traigent/utils/importance.py`, `traigent/analytics/example_insights.py` |
| `traigent-recipe-text2sql` | `traigent/__init__.py`, `traigent/api/decorators.py`, `traigent/core/objectives.py`, `traigent/evaluators/base.py`, `traigent/testing/*`, `traigent/core/optimized_function.py` |
