<!-- GENERATED from sync_map.yml by tools/contract/render_sync_map.py — edit sync_map.yml -->

# Skill-to-SDK Sync Map

When SDK source files change (in the [`Traigent`](https://github.com/Traigent/Traigent) Python SDK repo or [`traigent-js`](https://github.com/Traigent/traigent-js) JavaScript/TypeScript SDK repo), review the corresponding skills here for accuracy.

| Skill | SDK Source Dependencies |
|-------|----------------------|
| `traigent-quickstart` | `docs/getting-started/*`, `pyproject.toml`, `examples/quickstart/` |
| `traigent` | `traigent/api/decorators.py`, `traigent/utils/env_config.py`, `traigent/core/optimized_function.py` |
| `traigent-js` | `traigent-js/src/optimization/*`, `traigent-js/src/core/context.ts`, `traigent-js/src/seamless/*`, `traigent-js/src/integrations/*`, `traigent-js/src/routing/*`, `traigent-js/README.md`, `traigent-js/docs/*` |
| `traigent-configuration-space` | `traigent/api/parameter_ranges.py`, `traigent/api/constraint_builders.py`, `docs/user-guide/tuned_variables.md` |
| `traigent-decorator-setup` | `traigent/api/decorators.py`, `docs/user-guide/injection_modes.md` |
| `traigent-run-optimization` | `traigent/core/optimized_function.py`, `traigent/core/orchestrator.py`, `traigent/config/parallel.py` |
| `traigent-analyze-results` | `traigent/api/types.py`, `traigent/core/optimized_function.py` |
| `traigent-integrations` | `traigent/integrations/*`, `docs/architecture/integrations-inventory.md` |
| `traigent-debugging` | `traigent/utils/exceptions.py`, `traigent/utils/env_config.py` |
| `traigent-structural-spine` | `traigent/api/decorators.py`, `traigent/api/parameter_ranges.py`, `traigent/api/constraint_builders.py`, `docs/user-guide/tuned_variables.md` |
| `traigent-composite-knobs` | `traigent/knobs/patterns.py`, `traigent/knobs/runtime.py`, `traigent/knobs/telemetry.py`, `examples/advanced/composite-knobs/*`, `docs/traceability/concepts/composite-knobs.md` |
| `traigent-boost-agent` | `traigent/config_generator/recommendations.py`, `traigent/config_generator/catalog/tvar_catalog.v1.json`, `traigent/api/decorators.py`, `traigent/core/optimized_function.py`, `traigent/knobs/patterns.py`, `traigent/knobs/runtime.py`, `traigent/knobs/telemetry.py`, `traigent/utils/insights.py`, `traigent/utils/importance.py`, `traigent/analytics/example_insights.py`, `traigent/testing/*` |
| `show-significant-tuned-variables` | `traigent/utils/importance.py`, `traigent/utils/insights.py`, `optimization trial artifact schema` |
| `traigent-curate-dataset` | `traigent/generation/*`, `traigent/analytics/example_insights.py`, `traigent/evaluators/base.py`, `traigent/api/decorators.py`, `traigent/core/optimized_function.py`, `traigent/testing/*` |
| `traigent-choose-metric` | `traigent/api/decorators.py`, `traigent/core/optimized_function.py` |
| `traigent-build-evaluator` | `traigent/api/decorators.py`, `traigent/api/types.py`, `traigent/evaluators/base.py`, `traigent/evaluators/local.py`, `traigent/evaluators/hybrid_api.py` |
| `traigent-evaluator-audit` | `traigent/api/decorators.py`, `traigent/api/types.py` |
| `traigent-iterate` | `traigent/utils/insights.py`, `traigent/utils/importance.py`, `traigent/analytics/example_insights.py`, `traigent/core/optimized_function.py`, `traigent/api/types.py` |
| `traigent-ci-safety-gate` | `traigent/api/decorators.py`, `traigent/api/safety.py`, `traigent/tvl/promotion_gate.py`, `traigent/tvl/models.py`, `traigent/tvl/__main__.py` |
| `traigent-run-plan` | `traigent/api/decorators.py`, `traigent/core/optimized_function.py` |
| `traigent-next-run` | `traigent/core/optimized_function.py`, `traigent/api/types.py` |
| `traigent-reflect-hard-examples` | `traigent/generation/*`, `traigent/analytics/example_insights.py`, `traigent/evaluators/base.py`, `traigent/core/optimized_function.py`, `traigent/testing/*` |
| `traigent-optimization-principles` | `traigent/api/decorators.py`, `traigent/core/optimized_function.py` |
| `traigent-run-recommendations` | `traigent/api/decorators.py`, `traigent/utils/env_config.py` |
| `traigent-text2sql-optimize` | `traigent/__init__.py`, `traigent/api/decorators.py`, `traigent/core/objectives.py`, `traigent/evaluators/base.py`, `traigent/testing/*`, `traigent/core/optimized_function.py` |
