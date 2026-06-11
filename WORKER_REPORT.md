# Worker Report W6 — Backend Endpoint Contract Leg

## Parser Coverage

- Reads TraigentBackend only through git refs: `git rev-parse`, `git ls-tree`,
  and `git show`.
- Handles blueprint creation through `Blueprint(...)`, `flask.Blueprint(...)`,
  and the local `create_api_blueprint(...)` helper.
- Handles `@<bp>.route(...)` plus `.get/.post/.put/.patch/.delete` shorthands.
- Handles literal route paths, literal `methods=[...]`, and simple module-level
  string-list method constants.
- Handles `app.register_blueprint(...)` and direct nested
  `<parent_bp>.register_blueprint(...)`, including registration-time
  `url_prefix` overrides.
- Skips dynamic/non-literal route paths, dynamic method expressions, and wrapper
  registration helpers where the parent blueprint is only known through a
  function parameter, such as v1beta project-scoped helper registrations.

## Snapshot Stats

- Snapshot file: `tests/data/backend_routes_snapshot.json`
- Backend repo/ref: `Traigent/TraigentBackend` `origin/develop`
- Commit SHA: `cabbac8fee8461e62ea4322ecdc5c77a2b311a65`
- Route records: `361`

## Verification

```text
$ /tmp/venv-skills/bin/python tools/contract/refresh_backend_routes.py
wrote tests/data/backend_routes_snapshot.json with 361 routes from cabbac8fee8461e62ea4322ecdc5c77a2b311a65

$ /tmp/venv-skills/bin/python -m pytest tests/contract --sdk-version=0.12.0 -q
304 passed, 47 skipped in 12.30s

$ /tmp/venv-skills-dev/bin/python -m pytest tests/contract --sdk-version=0.13.0.dev1 -q
342 passed, 50 skipped in 12.63s

$ /tmp/venv-skills/bin/python tools/contract/render_sync_map.py --check
passed
```

## Findings

- Current URL extraction finds the `traigent-decorator-setup` hybrid endpoint
  example as advisory. It is an absolute `hybrid_api_endpoint` base URL, not an
  exact backend route in the snapshot, so I did not rewrite the skill text.
- Added `backend_prefixes` for the concrete hybrid optimizer backend family in
  `sync_map.yml`. The current base URL does not fall under that exact prefix, so
  it remains advisory rather than blocking.
- `tools/contract/render_sync_map.py` ignores unknown sync-map keys, so
  `SYNC_MAP.md` did not change and the render check still passes.

## Deferred Items

- If the skills later document exact session, dataset, analytics, experiment-run,
  optimization-comparison, or hybrid route paths, declare the matching
  `backend_prefixes` and let `test_endpoints.py` make those facts blocking.
- If v1beta project-scoped endpoints become part of the taught public contract,
  extend `refresh_backend_routes.py` to model the helper wrappers in
  `src/routes/api_v1beta.py`.
