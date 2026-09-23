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
greppable HTML comment immediately after the sentence that makes the claim.
This example is a real, currently-passing stamp (`traigent-optimize-run`):

```md
With `offline=True` the decorator raises `ConfigurationError` at decoration
time (*"requires managed optimization and cannot be used with
offline=True"*).
<!-- contract: literal "requires managed optimization" in traigent.config.types -->
<!-- contract: raises ConfigurationError in traigent.core.optimized_function -->
```

Grammar: `<!-- contract: <kind> <target> in <module> [@ SDK <version>] -->`.

- `path <target> in <module>` — `<target>` (a literal path string) must
  appear **verbatim in `<module>`'s source code** (or any `.py` file under
  it, if `<module>` is a package). This is a substring search over the
  source, not a runtime evaluation: a path assembled at runtime — e.g.
  `Path.home() / ".traigent" / "secure_credentials.enc"` — never appears as
  one literal string in source, so a `path` stamp for it always fails even
  though the behavior is real. Stamp the literal fragment that *does* appear
  verbatim instead (here, `literal "secure_credentials.enc" in
  traigent.security.credentials`), or use `path` only for a route/path built
  as one plain string constant (e.g. `path = "/api/v1/optimization-comparisons"`).
- `literal "<target>" in <module>` — same source-substring check, for a
  double-quoted literal string (Python-escaped).
- `raises <ExceptionName> in <module>` — the source must contain
  `raise <ExceptionName>` (recursively for a package). `<ExceptionName>` must
  be a bare identifier (`ConfigurationError`, not `pkg.ConfigurationError` or
  `mod.errors.ConfigurationError`) — stamp against the module where the bare
  name is actually raised.
- `<module>` must start with `traigent` (the regex enforces this) and should
  name the most specific submodule that contains the claim, not the bare
  `traigent` package — a bare `in traigent` stamp source-scans every `.py`
  file installed with the SDK, which is slow and makes review harder (it
  cannot tell you which file actually proves the claim). The bare form is
  used in this repo's own contract self-tests to exercise the checker against
  the whole installed SDK; it is not a pattern to copy into a skill.
- **All three checks are matched against source with docstrings blanked
  out.** A claim that is only true of a module's *documentation* (its
  docstring) and not of the executable code is not decay-checked by that
  documentation — it must match real code, or it fails as
  `source ... missing` even though grepping the raw file would find it.
  Python comments are removed with `tokenize`, preserving `#` inside strings
  (including URL fragments and f-strings). Comment-only claims fail. Malformed
  Python fails explicitly with `DOCSTAMP SOURCE UNVERIFIABLE`. These stamps
  establish source-text presence, not that a behavior occurs for a given input.
- Put the stamp in plain prose. The extractor scans the **whole raw file
  text**, so a stamp written inside a fenced code block or inline code span
  is scanned exactly the same as one in prose — nothing exempts an
  illustrative example. Do not paste a stamp into a `tests/README.md`-style
  example without expecting it to be live if that file is ever added to the
  scanned corpus (currently only `skills/**/SKILL.md` and
  `skills/**/references/*.md`).
- One stamp per HTML comment; two stamps are allowed on the same line
  (`<!-- contract: ... --> <!-- contract: ... -->`) since they are two
  separate comments. A single stamp's `<!-- contract: ... -->` must not be
  split across multiple lines — that is flagged as malformed, not silently
  ignored (see below).
- A malformed stamp — one that does not match the grammar above, or whose
  `@ SDK <version>` is not a parseable version — is **not silently ignored**.
  It becomes a `docstamp` fact of its own that always fails, reported as
  `MALFORMED CONTRACT STAMP <file>:<line>`, in every bucket that skill runs
  in. A typo in a stamp is a red test, never a check that quietly never ran.

The optional `@ SDK <version>` suffix works like `env_version_floors`: the
stamp is only checked in buckets at or above that version, so a claim
honestly restamped against a newer release does not red an older bucket. It
must be at or above the skill's own `min_sdk_version` in `sync_map.yml` — a
suffix below the skill's floor is a no-op (every bucket the skill runs in is
already above it) and is rejected by `test_docstamp_floor_not_below_skill_floor`.
Unlike `env_version_floors` (which lives in `sync_map.yml`, in plain sight
next to the skill) or a `references/<name>.md` python-version-floor prose
requirement, a docstamp's `@ SDK` floor lives only inside an HTML comment a
reader will not normally see rendered — when in doubt, also say the version
requirement in the prose sentence the stamp is attached to. A stamp on a
`references/<name>.md` file that already has its own `python_version_floors`
entry still needs its own `@ SDK` if the claim's true-since version differs
from that file's floor; the two mechanisms are not linked.

Because the stamp is a fixed, one-line comment, `grep -rn '<!-- contract: '
skills/` enumerates every load-bearing SDK claim currently decay-checked and
its target module — useful both for a human audit and for finding claims
that still need a stamp. (A looser `grep -rn 'contract: ' skills/` also
matches the unrelated `# contract: skip` runnable-block marker and any prose
that happens to contain the word "contract:" — anchor on `<!-- contract: `
to enumerate stamps only.)

Runnable examples are opt-in. Mark only complete, keyless Python examples with
````text
```python runnable
...
```
````
The contract suite executes those snippets in a temporary directory with
`TRAIGENT_OFFLINE_MODE=true`, no provider API keys, and unexpected deprecation
warnings treated as failures. The subprocess environment is an allowlist
(`PATH`, locale, temp-dir and interpreter variables) plus a private `HOME`, so
no `TRAIGENT_*` setting, provider key or CI marker from the caller's shell
reaches it: the snippet is tested as a new-user local dry run, not as an
approved CI optimization, and the verdict does not depend on who runs it. The runner currently allows known SDK-internal `TraigentConfig`
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

## Local onboarding journey

`pytest tests/contract/test_onboarding_journey.py --sdk-version=0.27.0` executes
three documented Python blocks together: the quickstart, holdout adapter, and
promotion gate. It runs the installed SDK, exports a candidate configuration,
then checks that equal mock holdout scores do not authorize promotion. Companion
cases cover invalid/unmeasured cost, exhausted `ExecutionBudget` (0.27.0+), and a
run with no eligible winner. `test_recipe_text2sql_runtime.py` covers missing
credentials and the presentation of injected cloud-persistence/fallback results.

These are local contract and wiring tests. Provider responses are canned; the
holdout is synthetic; the cloud-result diagnostic cases inject result objects.
The socket tripwire catches connection attempts but is not OS network isolation.
No live portal persistence, paid-provider success, evaluator quality, or an AI
agent's interpretation of prose is certified by this suite.
