# Phase E — spine staleness integration + human-gated SkillOpt remediation

The contract program (phases A–D + the upstream gate C) is the enforcement core and is **live**:
skills fail CI when they teach a non-existent SDK symbol, MCP tool, JS export, or backend route;
new interfaces with no skill are flagged; and upstream PRs can run the contract against their own
surface. Phase E is the optional **governance + auto-remediation capstone**. Both pieces touch
infrastructure outside the skill repos, so this spec is precise and ready to implement — via the
proper governed path for each.

## E1 — register skills as spine artifacts (dependency staleness + impact)

**Goal:** when an interface (or its vendored snapshot) changes, the spine marks the dependent skill
**dependency-stale**, and `ops.impact.analyze` answers "this change affects skills X, Y" — surfacing
skill drift in the spine dashboard/posture, not just CI.

**Why a spec, not an edit here:** `ops/_validation/catalog/artifacts.yaml` and `impact.py` are the
spine governance core; per the workspace rules a change to them is a governed spine ChangeSession,
not an ad-hoc edit. Implement via `/spine:change`.

**Reuse:** `validation_spine.artifact_registry.dependency_staleness()` already implements
"an input hash changed → the artifact is dependency-stale" for any artifact whose `derived_from`
lists its inputs. No new mechanism — just register skills.

**Catalog entries** (one per contract surface; `gate_impact: advisory` to start). Add to
`ops/_validation/catalog/artifacts.yaml`:

```yaml
- id: artifact:skill_contract:mcp
  path: skills/agents-skills/tests/data/mcp_tools_snapshot.json
  kind: vendored_snapshot
  artifact_domain: learning_material
  subject_domains: [traigent_product, spine_system]
  producer: agents-skills.tools.contract.refresh_mcp_tools
  consumers: [agents-skills.tests.contract.test_mcp]
  gate_impact: advisory
  status: active
  derived_from:
    - ops/_validation/src/validation_spine/mcp/services.py   # the TOOLS registry
  notes: When services.TOOLS changes, the MCP tool snapshot (and the skills that teach those tools) go dependency-stale.

- id: artifact:skill_contract:js
  path: skills/traigent-skills/tests/data/js_api_snapshot.json
  kind: vendored_snapshot
  artifact_domain: learning_material
  subject_domains: [traigent_product]
  producer: traigent-skills.tools.contract.refresh_js_api
  consumers: [traigent-skills.tests.contract.test_js]
  gate_impact: advisory
  status: active
  derived_from:
    - traigent-js/tests/integration/fixtures/api-surface.snapshot.json

- id: artifact:skill_contract:backend
  path: skills/traigent-skills/tests/data/backend_routes_snapshot.json
  kind: vendored_snapshot
  artifact_domain: learning_material
  subject_domains: [traigent_product]
  producer: traigent-skills.tools.contract.refresh_backend_routes
  consumers: [traigent-skills.tests.contract.test_endpoints]
  gate_impact: advisory
  status: active
  derived_from:
    - (TraigentBackend route source files; pinned by commit_sha in the snapshot header)
```

**impact.py extension:** in `build_impact_report()`, after the module/UCM/gap traversal, add a
skill-impact pass: load the three snapshots' `derived_from` sets; if any path in the change_set
intersects a snapshot's inputs, append the consuming skills to the report under a new
`impacted_skills` key. Surface it in `ops.impact.analyze` / `ops.change.impact` output. Mirror the
existing `_impacted_modules()` path-intersection helper.

**Verification:** a change to `mcp/services.py` makes `artifact:skill_contract:mcp` report
`dependency_hash_changed`; `ops.impact.analyze` on that change lists the MCP-teaching skills.

## E2 — human-gated SkillOpt draft-PR remediation

**Goal:** when a skill drifts (contract red on main, or a drift issue opens), regenerate it with the
SkillOpt trainer and open a **DRAFT PR** for human review. Never auto-merge, never auto-apply.

**Reuse:** the headless trainer `integrations/skill-evals` (`python -m cli train --skill X
--skills-root <skills> [--live --apply --optimizer claude]`). Dry-run is the default (no model
spend); `--apply` validates provenance schema + PROTECTED/SLOW_UPDATE marker balance before
atomically writing `SKILL.md` + `provenance.json`.

**Why gated, not auto:** the SkillOpt live-training path is owner-gated and corpus-limited
(~5–6 tasks/skill today); auto-applying LLM-rewritten docs is exactly the risk to avoid. So this is
a **`workflow_dispatch`-only** workflow (never auto-fires) that defaults to dry-run.

**Workflow** (`skills/traigent-skills/.github/workflows/skill-remediation.yml`, sketch):

```yaml
on:
  workflow_dispatch:
    inputs:
      skill: { required: true }
      live:  { type: boolean, default: false }   # false = dry-run, no spend, no PR
permissions: { contents: write, pull-requests: write }
jobs:
  remediate:
    if: ${{ secrets.SKILLOPT_TOKEN != '' }}        # skips cleanly until armed
    runs-on: ubuntu-latest
    steps:
      - checkout traigent-skills (target)
      - checkout integrations/skill-evals (trainer) + Traigent (SkillTrainer)   # via SKILLOPT_TOKEN
      - set up Python; install the SDK + skill-evals deps
      - run: |
          cd skill-evals
          python -m cli train --skill "${{ inputs.skill }}" \
            --skills-root "$GITHUB_WORKSPACE/skills" \
            ${{ inputs.live && '--live --apply --optimizer claude' || '--dry-run' }}
      - if: ${{ inputs.live }}                       # re-VERIFY the regenerated skill before any PR
        run: |
          cd "$GITHUB_WORKSPACE"
          python -m pytest tests/contract -q                       # contract + lints
          python -c "import json,hashlib,glob,os; ..."             # provenance doc_hash consistency
      - if: ${{ inputs.live }}
        uses: peter-evans/create-pull-request@<pinned>             # DRAFT only
        with:
          draft: true
          branch: skillopt/remediate-${{ inputs.skill }}
          title: "skillopt: regenerate ${{ inputs.skill }} after interface drift"
          body: "Auto-regenerated by SkillOpt after a contract drift signal. Review required; do not auto-merge."
```

**Hard requirements before merge of any draft PR it opens:** the regenerated skill must pass the full
contract suite + all lints + provenance `doc_hash` consistency (the same gates a human PR must pass).
A human reviews the diff. This makes the remediation a *suggestion*, never an unattended write.

## Recommended sequencing

1. **E1** as a spine ChangeSession (`/spine:change`) — additive, advisory `gate_impact`, low risk.
2. **E2** after the SkillOpt live-training path is owner-approved for unattended dry-runs; arm with a
   `SKILLOPT_TOKEN` and keep it `workflow_dispatch`-only + draft-PR until trust is established.
