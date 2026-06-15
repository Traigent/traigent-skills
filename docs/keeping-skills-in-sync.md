# Keeping skills in sync with the interfaces they (should) use

Skills (markdown docs that teach users/agents how to call our interfaces) silently rot when
we change the interfaces underneath them. The **skill ⟷ interface contract** guards this in two
directions:

- **Reactive (in this repo):** a skill that teaches a non-existent SDK symbol, MCP tool, JS export,
  or backend route fails CI. Covered by the contract harness (`tests/contract/`) + the MCP contract
  in `agents-skills` + the weekly drift jobs.
- **Proactive (upstream):** a PR that changes an interface gets an **in-PR signal of which skills it
  would break** — caught at the source, not nightly. This page sets that up.

## One-time setup: the read-only token

The upstream jobs check out the skills contract from another repo, which needs read access. Create
a **fine-grained PAT or GitHub App installation** with **read-only** access to `Traigent/traigent-skills`
(and `Traigent/agents-skills` for the MCP caller), and add it as the secret **`SKILLS_REPO_TOKEN`** in
each upstream repo (or as an org-level secret shared to them).

Until that secret exists, every caller below **skips cleanly** (green no-op), so you can land the
callers first and arm them later. Roll out **advisory first** (don't mark the check required); flip a
surface to required once it has been green across a few PRs.

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
      - uses: actions/checkout@v6            # the BE PR
      - uses: actions/checkout@v6
        with: { repository: Traigent/traigent-skills, token: "${{ secrets.SKILLS_REPO_TOKEN }}", path: _skills }
      - uses: actions/setup-python@v6
        with: { python-version: "3.12" }
      - run: python -m pip install pytest pyyaml packaging
      - name: Validate taught endpoints against THIS PR's routes
        if: ${{ secrets.SKILLS_REPO_TOKEN != '' }}
        run: |
          python _skills/tools/contract/refresh_backend_routes.py --repo . --ref HEAD \
            --out _skills/tests/data/backend_routes_snapshot.json
          cd _skills && python -m pytest tests/contract/test_endpoints.py --sdk-version=develop -q -rs
```

### ops/_validation → traigent-validation-spine (MCP tools)
```yaml
name: Skill Contract (MCP tools)
on:
  pull_request:
    paths: ["src/validation_spine/mcp/services.py"]
permissions: { contents: read }
jobs:
  skill-mcp-contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6            # the spine PR
      - uses: actions/checkout@v6
        with: { repository: Traigent/agents-skills, token: "${{ secrets.SKILLS_REPO_TOKEN }}", path: _agents }
      - uses: actions/setup-python@v6
        with: { python-version: "3.12" }
      - run: python -m pip install pytest pyyaml packaging
      - name: Validate taught MCP tools against THIS PR's registry
        if: ${{ secrets.SKILLS_REPO_TOKEN != '' }}
        run: |
          src=./src; [ -d "$src/validation_spine" ] || src=.
          python _agents/tools/contract/refresh_mcp_tools.py --spine-src "$src" --spine-repo . --ref HEAD \
            --out _agents/tests/data/mcp_tools_snapshot.json
          cd _agents && python -m pytest tests/contract/test_mcp.py -q -rs
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
      - uses: actions/checkout@v6            # the JS PR (its api-surface.snapshot.json is gated by its own test)
      - uses: actions/checkout@v6
        with: { repository: Traigent/traigent-skills, token: "${{ secrets.SKILLS_REPO_TOKEN }}", path: _skills }
      - uses: actions/setup-python@v6
        with: { python-version: "3.12" }
      - run: python -m pip install pytest pyyaml packaging
      - name: Validate taught JS imports against THIS PR's exports
        if: ${{ secrets.SKILLS_REPO_TOKEN != '' }}
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
