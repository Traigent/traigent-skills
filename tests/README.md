# Contract Tests

The `tests/contract` suite checks that skill text does not teach dead Traigent
interfaces.

It extracts these facts from skills and references:

- Python facts from fenced Python blocks: imports, imported symbols, and
  Traigent call keyword arguments.
- Env facts from Markdown text: `TRAIGENT_*` variables.
- CLI facts from fenced shell blocks: `traigent ...` and
  `python -m traigent...` commands.
- URL facts from inline code and fenced blocks: backend endpoint paths under
  `/datasets`, `/analytics`, `/experiment-runs`, `/optimization-comparisons`,
  `/sessions`, and `/hybrid`.

`sync_map.yml` assigns each skill to an SDK-version bucket. The default floor is
`default_min_sdk_version`; a skill can override it with `min_sdk_version`.
`env_version_floors` lets one env var require a newer SDK than the rest of the
skill, and the skill text must state that requirement. `backend_prefixes` makes
URL endpoint checks blocking only for backend path families a skill explicitly
owns; otherwise URL facts are advisory skips.

Run both local buckets:

```bash
/tmp/venv-skills/bin/python -m pytest tests/contract --sdk-version=0.12.0 -q
/tmp/venv-skills-dev/bin/python -m pytest tests/contract --sdk-version=0.13.0.dev1 -q
```

Refresh the vendored backend route snapshot from the local TraigentBackend git
ref:

```bash
/tmp/venv-skills/bin/python tools/contract/refresh_backend_routes.py
```

The snapshot is trusted the same way as other vendored contract fixtures: it is
deterministic JSON generated from `TraigentBackend` git refs using `git show` and
`git ls-tree`, never from the backend working tree. Review snapshot diffs when
routes change, and refresh it only from the intended backend ref.

## JS SDK contract

`test_js.py` validates `import { X } from '@traigent/sdk[/sub]'` in the `traigent-js`
skill against `tests/data/js_api_snapshot.json`, vendored from traigent-js's committed
`api-surface.snapshot.json` (the JS repo's own gated export surface). Blocking only for
skills that declare `js: true` in `sync_map.yml`. Refresh:

```bash
python tools/contract/refresh_js_api.py --js-repo <traigent-js> --ref origin/main
```

The weekly `js-api-drift` workflow regenerates and opens an issue when exports change.

## Coverage ("should-use") ledger

`test_coverage_ledger.py` flags a **new** interface element (JS export / backend route) that no
skill teaches and no waiver covers — the "should-use" direction. The baseline lives in
`tests/data/interface_inventory.json` (today's surface is grandfathered). When a snapshot refresh
adds a new element, decide: teach it in a skill, or add a `no_skill` waiver to `coverage_ledger.yml`,
then refresh the baseline:

```bash
python tools/contract/build_interface_inventory.py
```
