# E1 — spine skill-interface projection (implementation plan)

Designed with codex gpt-5.5 (xhigh), which converged on a **spine-side committed projection** and
surfaced a **proven precedent**: the spine already ships an in-repo projection of exactly this shape —
the **agent-rule projection** (spine PR #240): `src/validation_spine/agent_rules.py` →
`health/latest-agent-rule-projection.json` + `schemas/agent_rule_projection.schema.json`, registered
in `catalog/artifacts.yaml`, freshness-tracked by the artifact registry, exposed via MCP. **E1 mirrors
this pattern exactly** for skills, so it carries near-zero new architectural risk.

This is implemented **in the spine repo via `/spine:change`** (a governed change to the spine core),
not in the skill repos. It is **additive and advisory-first**.

## Why a projection (not direct cross-repo artifacts)

The artifact registry requires every artifact `path` to be **relative, within the spine repo**
(`artifact_registry.py:151`), so it cannot hash the skill snapshots that live in sibling repos. A
spine-side **projection JSON** sidesteps this entirely: the registry only ever hashes the in-repo
projection file; the projection itself *records* the foreign snapshot hashes, and a freshness check
compares recorded-vs-live. (Precedent: `validators.yaml` already lists cross-repo input paths, so
cross-repo *inputs* are established; only the artifact `path` must be in-repo — which the projection is.)

## Files to add (mirror the agent-rule projection)

| New file | Role (template) |
|---|---|
| `src/validation_spine/skill_interface.py` | Projector. Mirrors `agent_rules.py`. Reads the skill repos at **pinned refs** (`origin/main` for traigent-skills, agents-skills) + their `sync_map.yml` + the 3 vendored snapshots; emits the projection. |
| `health/latest-skill-interface-projection.json` | The materialized projection (in-repo → registry can hash it). |
| `schemas/skill_interface_projection.schema.json` | New schema (mirror `agent_rule_projection.schema.json`). **Do not bend `artifact_catalog.schema.json`.** |
| `catalog/artifacts.yaml` entry | `id: artifact:skill_interface_projection`, `kind: generated_projection`, `gate_impact: advisory`, `replay_role: output`, `status: active`, `derived_from:` the interface-source paths it watches (see below). |
| `tests/test_skill_interface.py` | Projection shape, freshness (fresh/stale/missing), determinism. Mirror `tests/test_agent_rules.py`. |

## Projection contents

```jsonc
{
  "schema": "skill-interface-projection/v1",
  "generated_from": { "traigent_skills_ref": "origin/main@<sha>", "agents_skills_ref": "origin/main@<sha>" },
  "skills": [
    { "repo": "traigent-skills", "skill": "traigent-js", "family": "js",
      "taught_interface_ids": ["js:@traigent/sdk#optimize", ...],
      "snapshot_path": "tests/data/js_api_snapshot.json", "snapshot_sha256": "<hex>" },
    { "repo": "agents-skills", "skill": "traigent-validation-spine-update", "family": "mcp",
      "taught_interface_ids": ["mcp:ops.kg.precheck", ...],
      "snapshot_path": "tests/data/mcp_tools_snapshot.json", "snapshot_sha256": "<hex>" }
    // backend family likewise
  ]
}
```

`taught_interface_ids` reuse the coverage-ledger ID scheme (`js:`/`mcp:`/`be:`); the projector derives
them from the already-extracted contract facts + each skill's `sync_map` declarations.

## Staleness — rides the registry, plus one small check

- **Registry freshness (reused):** registering `health/latest-skill-interface-projection.json` in the
  catalog makes `artifact_registry` track *the projection file's own* freshness (fresh/missing/stale by
  age + `derived_from` hashes of the **in-repo** interface sources it watches — see below). This is the
  exact mechanism agent-rule-projection uses; no new machinery.
- **Cross-repo divergence (small dedicated check):** a tiny `skill_interface.verify_fresh()` re-reads
  each skill repo at its pinned ref, recomputes the snapshot sha256, and compares to the recorded value.
  On divergence it emits a **non-confident gap** (`kind: skill_interface_stale`, advisory). This is the
  one piece registry `dependency_staleness()` can't do (foreign paths), so it lives in the projector,
  not the registry.

`derived_from` for the catalog entry lists the **in-repo** interface sources the registry *can* hash —
chiefly `src/validation_spine/mcp/services.py` (the MCP registry). JS/backend sources live in other
repos, so those are covered by the `verify_fresh()` cross-repo check above, not `derived_from`.

## impact.py extension

Add a skill-impact pass to `build_impact_report()`: load the projection; for the change_set, intersect
the changed paths against per-family **interface-source globs**:
- mcp → `src/validation_spine/mcp/services.py`
- js → (traigent-js) `src/index.ts`, `src/**/index.ts`, `package.json`
- backend → (TraigentBackend) route files

Emit a new output key `impacted_skills: [{repo, skill, family, reason}]`, surfaced through
`ops.impact.analyze` / `ops.change.impact`. Path-intersection mirrors the existing `_impacted_modules()`.

## CI — the projector job

A scheduled + dispatch job **in the spine repo** (next to the spine's own CI) that:
1. checks out traigent-skills + agents-skills at `origin/main` (deterministic; **pinned refs, not sibling
   working trees** — codex flagged that the parked workspace clones must not be the source) using a
   read-only token (the same `SKILLS_REPO_TOKEN` PAT already provisioned);
2. runs `python -m validation_spine.skill_interface materialize` to regenerate the projection;
3. commits it if changed (like the other `health/latest-*` projections) and runs `verify_fresh()`.
This stays in sync with the weekly drift jobs because both read the same committed snapshots at `origin/main`.

## Phasing

- **P1 (advisory projection):** projector + schema + catalog entry + `verify_fresh()` emitting advisory
  `skill_interface_stale` gaps. Smallest valuable increment.
- **P2 (impact):** the `impact.py` skill-impact pass + `ops.impact.analyze` output + (optional) an MCP
  read tool `ops.skills.interface_coverage` (mirror `ops.agent_rules.context`).
- **P3 (enforcement):** flip the gap to non-confident/blocking once trusted; tie into release readiness.

## Top risks → mitigations

1. **Schema breakage** → brand-new `skill_interface_projection.schema.json`; never touch `artifact_catalog`.
2. **Stale / non-deterministic projection** → always materialize from **pinned `origin/main` refs**, never
   the dirty workspace clones; record both refs' shas in `generated_from`; idempotent projector.
3. **Spine-CI cross-repo coupling** → read-only token, advisory-only; the spine's own gates never hard-depend
   on the skill repos being reachable (the projector job is separate + non-blocking).
4. **False staleness** → compare snapshot sha256 (content), ignore `commit_sha` churn — same lesson as the
   drift jobs; only a real content change flags a gap.
5. **Governance** → land via `/spine:change` on spine `develop` (where the precedent + active line live);
   advisory `gate_impact`; one focused ChangeSession, mirroring agent-rule-projection PR #240.

## Reference
- Template/precedent: spine PR #240 (`agent_rules.py`, `agent_rule_projection.schema.json`,
  `health/latest-agent-rule-projection.json`, registered + MCP-exposed).
