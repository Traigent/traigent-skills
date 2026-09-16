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
- Doc-claim stamps from a `<!-- contract: ... -->` HTML comment anywhere in the
  prose: `path`, `literal`, and `raises` claims (see below).

## Doc-claim stamps

Every fact above only sees fenced code blocks or code spans. A **prose** claim
about the SDK — a file-layout path, a quoted error/warning string, or "this
symbol does/does not raise X" — is invisible to the harness by default, so it
can silently drift out of sync with the installed SDK and nothing goes red.

Opt a specific prose claim into decay-checking by stamping it with a
greppable HTML comment immediately after the sentence that makes the claim:

```md
The key is saved to `~/.traigent/secure_credentials.enc`.
<!-- contract: path ~/.traigent/secure_credentials.enc in traigent.security.credentials -->
```
```md
Watch the dry-run for a `found no injectable targets` warning.
<!-- contract: literal "found no injectable targets" in traigent.config.providers -->
```
```md
A pre-run over-budget estimate raises `CostLimitExceeded`.
<!-- contract: raises CostLimitExceeded in traigent.core.cost_estimator -->
```

Grammar: `<!-- contract: <kind> <target> in <module> [@ SDK <version>] -->`,
one stamp per comment line.

- `path <target> in <module>` — `<target>` (a literal path string) must appear
  in `<module>`'s source (or any `.py` file under it, if `<module>` is a
  package).
- `literal "<target>" in <module>` — same check, for a double-quoted literal
  string (Python-escaped).
- `raises <ExceptionName> in <module>` — the source must contain
  `raise <ExceptionName>` (recursively for a package).

The optional `@ SDK <version>` suffix works like `env_version_floors`: the
stamp is only checked in buckets at or above that version, so a claim honestly
restamped against a newer release does not red an older bucket. Never edit a
stamp's target without re-verifying the claim; a mismatch fails as
`DEAD TEACHING` with the fix menu (restamp / update the prose / remove the
stamp because it is no longer an SDK claim).

Because the stamp is a fixed, one-line comment, `grep -rn 'contract: '
skills/` enumerates every load-bearing SDK claim currently decay-checked and
its target module — useful both for a human audit and for finding claims that
still need a stamp.

Runnable examples are opt-in. Mark only complete, keyless Python examples with
````text
```python runnable
...
```
````
The contract suite executes those snippets in a temporary directory with
`TRAIGENT_OFFLINE_MODE=true`, no provider API keys, and unexpected deprecation
warnings treated as failures. The subprocess also clears CI marker env vars so
the snippet is tested as a new-user local dry run, not as an approved CI
optimization. The runner currently allows known SDK-internal `TraigentConfig`
transition warnings so the gate still catches skill-taught deprecated APIs such
as `traigent.analytics`.

Public installability is checked in two ways:

- Python buckets install `traigent==<version>` from PyPI before running the
  contract suite, then `test_public_installability.py` verifies the installed
  distribution matches the selected bucket.
- `@traigent/sdk` is not on public npm yet, so public docs must not teach
  `npm install @traigent/sdk` as an install path while Traigent/traigent-js#165
  remains open.

`sync_map.yml` assigns each skill to an SDK-version bucket. The default floor is
`default_min_sdk_version`; a skill can override it with `min_sdk_version`.
`env_version_floors` lets one env var require a newer SDK than the rest of the
skill, and the skill text must state that requirement. `backend_prefixes` makes
URL endpoint checks blocking only for backend path families a skill explicitly
owns; otherwise URL facts are advisory skips.

Run the released SDK buckets emitted by `sync_map.yml`:

```bash
python tools/contract/list_buckets.py
# then run each bucket it emits, e.g. (current set):
python -m pytest tests/contract --sdk-version=0.21.3 -q
python -m pytest tests/contract --sdk-version=0.24.0 -q
python -m pytest tests/contract --sdk-version=0.27.0 -q
```

`current_released_sdk_version` is intentionally pinned in `sync_map.yml` so PR
CI is hermetic. Update that field in the same PR that should start testing a
new public PyPI release.

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
