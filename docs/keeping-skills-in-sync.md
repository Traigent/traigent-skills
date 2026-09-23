# Keeping skills in sync with the interfaces they (should) use

Skills (markdown docs that teach users/agents how to call our interfaces) silently rot when
we change the interfaces underneath them. The **skill ⟷ interface contract** guards this in two
directions:

- **Reactive (in this repo):** a skill that teaches a non-existent SDK symbol, MCP tool, JS export,
  or backend route fails CI. Covered by the contract harness (`tests/contract/`) + the MCP contract
  in `agents-skills` + the weekly drift jobs.
- **Proactive (upstream):** a PR that changes an interface gets an **in-PR signal of which skills it
  would break** — caught at the source, not nightly. This page sets that up.

## One-time setup: none

`Traigent/traigent-skills` is public, so the callers below check out the contract harness without any
token or secret. There is no "not yet armed" state: every caller always runs the contract, and a
failure to fetch or run it fails the check instead of reporting success.

Roll out **advisory first** (don't mark the check required); flip a surface to required once it has
been green across a few PRs.

## Callers (one per upstream repo)

### Traigent (Python SDK)
Uses the reusable workflow `.github/workflows/skill-contract-upstream.yml`. Drop in
`.github/upstream-templates/traigent-sdk-caller.yml` → `Traigent/.github/workflows/skill-contract.yml`.
It installs the PR SDK and validates every taught Python fact against it.

### TraigentBackend (REST routes)
```yaml
name: Skill Contract (backend routes)
on:
  pull_request:
    paths: ["src/**/*.py"]
permissions: { contents: read }
jobs:
  skill-route-contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with: { persist-credentials: false }   # the BE PR
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with: { repository: Traigent/traigent-skills, path: _skills, persist-credentials: false }
      - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6.2.0
        with: { python-version: "3.12" }
      - run: python -m pip install pytest pyyaml packaging
      - name: Validate taught endpoints against THIS PR's routes
        run: |
          python _skills/tools/contract/refresh_backend_routes.py --repo . --ref HEAD \
            --out _skills/tests/data/backend_routes_snapshot.json
          cd _skills && python -m pytest tests/contract/test_endpoints.py --sdk-version=develop -q -rs
```

### traigent-js (JS SDK)
```yaml
name: Skill Contract (JS API)
on:
  pull_request:
    paths: ["src/index.ts", "src/**/index.ts", "package.json", "tests/integration/fixtures/api-surface.snapshot.json"]
permissions: { contents: read }
jobs:
  skill-js-contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with: { persist-credentials: false }   # the JS PR (its api-surface.snapshot.json is gated by its own test)
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with: { repository: Traigent/traigent-skills, path: _skills, persist-credentials: false }
      - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6.2.0
        with: { python-version: "3.12" }
      - run: python -m pip install pytest pyyaml packaging
      - name: Validate taught JS imports against THIS PR's exports
        run: |
          python _skills/tools/contract/refresh_js_api.py --js-repo . --ref HEAD \
            --out _skills/tests/data/js_api_snapshot.json
          cd _skills && python -m pytest tests/contract/test_js.py -q -rs
```

## How it works

Each caller **regenerates the relevant snapshot from the PR** and runs the matching skill contract
against it. If a skill teaches a symbol/tool/route/export the PR removed or renamed, the contract goes
red on the upstream PR — naming the skill and the dead teaching — so the interface change and the skill
fix land together. The Python SDK caller installs the PR wheel and runs `--sdk-version=develop` (no
version-bucket gating) so every taught Python fact is checked against the PR build.

This is the same harness the skills repo runs reactively; here it is pointed at the PR's surface so the
signal arrives at the source instead of nightly.
