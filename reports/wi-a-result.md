# WI-A result — skills posture + template survey + explanation duty

- **Repo / branch / base:** `Traigent/traigent-skills` | `feature/econ-model-wi-a` | `origin/main`
- **Worktree:** `/home/nimrod/TraigentProjects/worktrees/econ-model-2026-07-17/traigent-skills`
- **Governance:** Spine-Trail `st_6443b96904d7`; replacement ChangeSession `cs_8e10a485f94fda03`
- **Scope note:** WI-D incentives excluded. No commit, push, PR, or merge performed.
- **PR-ready:** **YES** (one owner-visible note in *Risks*, non-blocking)
- **Revision:** updated 2026-07-17 after the Terra review. Three BLOCK findings (install
  reachability of the canonical reference, `traigent-analyze-guidance` shaping economics
  locally, and the 3-option cap vs. five closed values) are repaired; the repair pass is
  reported separately in [`wi-a-review-fix-result.md`](wi-a-review-fix-result.md). The claims
  below describe the repaired state.

## What changed

One canonical reference, **authored once** and **generated into** the eight skills that use
it, so it is readable from every supported install. The posture is written **once**.

### New — the single source of truth

`docs/shared/economics-characterization.v0.md` (new, 1 file):

| Section | Contents |
|---|---|
| §1 Posture | The **exact** session3 §2 three-sentence posture, verbatim, quoted once |
| §1 (cont.) | What changed (cost avoidance is no longer the default) and the explicit list of safety rules that did **not** change |
| §2 | All five session2 questions — canonical wording **and** slot-tailored templates — with all exact options mapped to closed enum values |
| §3 | Who asks: the user's actual coding agent; name the real agent, infer first, confirmations carry evidence, Q1+Q3 always explicitly confirmed, Q2/Q4/Q5 only when not confidently inferable, target 2 asked |
| §4 | The explanation duty: options + one recommendation + WHY in the user's own numbers — stated as a product requirement, not styling — plus the **paging rule** that keeps all five closed values reachable inside the interaction policy's 3-option cap |
| §5 | Templates/tailoring are suggestions; the closed submission is the commitment |
| §6 | Until a submission path exists: write the closed draft to `.traigent/economics-survey.v0.json`, local + uncommitted, nothing transmitted |
| §7 | Budget/floors/caps, payback, stop rule, receipts, credibility rules — all labeled starting assumptions |

### New — the generator and its gate

- `tools/contract/sync_economics_reference.py` — copies the canonical doc into each economics
  skill's `references/economics-characterization.v0.md`. Targets are **discovered** (any
  SKILL.md carrying the pointer marker), not hardcoded. `--check` is the CI-usable gate.
- `tests/contract/test_economics_reference.py` — 43 tests: byte-identity of every generated
  copy, readability from a **simulated single-skill install**, the analyze-guidance
  local-budget regression lint, and the paging-rule reachability property.

### Modified — eight skills (SKILL.md + provenance.json + generated reference each)

Each got one `## Optimization Economics — Read This Before Sizing a Run` section inserted
immediately after `## When to Use` (outside every PROTECTED / SLOW_UPDATE /
INTERACTION_POLICY region), containing: a pointer to the reference **shipped inside the
skill**, the skill's own role per session3 §2, the mandatory explanation duty, and the
unchanged-safety restatement. **The three-sentence posture is not reproduced in any of them.**

| Skill | Version | doc_hash before → after | Role (session3 §2) |
|---|---|---|---|
| traigent-setup-quickstart | 1.0.18 → **1.0.20** | `3a19554c5624fb4f` → `1bceeccc65431713` | characterize value, propose bounded first experiment |
| traigent-boost-agent | 2.1.6 → **2.1.8** | `23c57e5772586d93` → `be83fe17856839da` | characterize value, propose bounded first experiment |
| traigent-optimize-run | 1.0.13 → **1.0.15** | `ad8b4d5c3c32a975` → `6fdd53351932dcb7` | enforce cap, receipt, stop rule |
| traigent-setup-decorator | 1.0.9 → **1.0.11** | `3db71bdafe5e0a1a` → `d0f6a46c79384fd9` | make cap/receipt/stop rule enforceable |
| traigent-analyze-guidance | 1.1.0 → **1.1.2** | `51a8c8aea0c8cf0f` → `59464aba14a2deb3` | collect/relay characterization; present **only** a service-authored budget |
| traigent-analyze-results | 1.1.13 → **1.1.15** | `39352a037b3de5b2` → `f2dda030a1ffec27` | winner / no-gain / insufficient-evidence receipt |
| traigent-dataset-curate | 1.1.2 → **1.1.4** | `f5481ef2791c45ef` → `363c38db65a63d3a` | confirmed defect receipts, human-QA equivalence |
| traigent-eval-audit | 1.1.4 → **1.1.6** | `0cfbd5cc6be2f30e` → `5dc6add523971e24` | confirmed defect receipts, human-QA equivalence |

Each `provenance.json` carries **two** appended `manual_edit` records — the original
`economics-bounded-investment-posture-2026-07-17` and the repair
`economics-reference-install-reachability-2026-07-17` — following the existing field format
exactly. Provenance is **append-only**: the first record was left untouched, hashes chain
`before → after → after'`, and no history was rewritten. Version bumped twice for the same
reason: the SKILL.md bytes changed twice.

**Full change set (28 files, all in scope):** 1 × `docs/shared/economics-characterization.v0.md`;
8 × `SKILL.md`; 8 × `provenance.json`; 8 × generated `references/economics-characterization.v0.md`;
1 × `tools/contract/sync_economics_reference.py`; 1 × `tests/contract/test_economics_reference.py`;
plus `README.md` and one allowlist line in `tests/contract/test_skill_names.py` (see the repair
report).

## Commands run and results

```
pwd                     → /home/nimrod/TraigentProjects/worktrees/econ-model-2026-07-17/traigent-skills
git remote -v           → origin https://github.com/Traigent/traigent-skills
git branch --show-current → feature/econ-model-wi-a
```
Preflight matched the assignment; proceeded.

**Provenance baseline integrity** — every pre-edit `SKILL.md` hash at `HEAD` equaled the
`doc_hash` already recorded in its `provenance.json` (8/8 `OK`), so each `doc_before_hash`
is a true predecessor and the chain is unbroken.

**Focused skills contract / provenance tests** (no SDK needed):
```
uv run --frozen pytest tests/contract/test_provenance.py tests/contract/test_interaction_policy.py \
  tests/contract/test_skill_lints.py tests/contract/test_text_requirements.py \
  tests/contract/test_readme_catalog_completeness.py tests/contract/test_skill_names.py -q
→ 66 passed, 1 skipped in 1.13s
```

**Full contract suite, with the released SDK installed** (`pyproject.toml` deliberately does
not pin the SDK, so it must be installed to get a real signal). Figures below are from the
original pass; the post-repair run is **849 passed / 0 failed** — see the repair report:
```
uv pip install "traigent==0.23.0"            # sync_map.yml: current_released_sdk_version
uv run --no-sync pytest tests/contract -q --sdk-version 0.23.0
→ 806 passed, 451 skipped, 1 warning in 68.77s   (0 failed)

uv run --no-sync pytest tests/repo_forensics tests/test_repo_forensics_ioc_manager.py -q
→ 14 passed
```

**Pre-existing-failure control.** Before installing the SDK, `pytest tests/` reported
`602 failed, 137 passed, 532 skipped` — all `ModuleNotFoundError: No module named 'traigent'`.
I proved this was environmental, not mine, by running the identical suite on a pristine
detached worktree at `HEAD`:
```
git worktree add --detach /tmp/wi-a-base HEAD && cd /tmp/wi-a-base && uv run --frozen pytest tests/ -q
→ 602 failed, 137 passed, 532 skipped     # byte-identical to the changed tree
```
Same numbers with and without my change ⇒ zero new failures. Worktree removed afterwards.
With the SDK present the suite is fully green, so no failure is being carried.

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| One source of truth, no duplicated posture | **PASS** | Authored in exactly one file; the 8 skill copies are generated artifacts pinned byte-identical to it by `test_economics_reference.py`, and a hand-edited copy fails the suite (proved by `test_sync_tool_detects_a_tampered_copy`) |
| All 8 skills point at it | **PASS** | 1 pointer each, 8/8, at the skill-relative path |
| Reference readable from a single-skill install | **PASS** | `test_single_skill_install_can_read_the_reference` copies each skill dir **alone** into a tmpdir (no repo, no `docs/`) and reads the reference there — 8/8 |
| All exact questions present | **PASS** | 5/5 canonical questions matched with `grep -F` |
| All exact options present | **PASS** | 24/24 distinct option strings matched with `grep -F` |
| Slots used | **PASS** | `{agent_name} {dataset_name} {evidence} {model_name} {observed_volume}` |
| Explanation duty unmistakably mandatory | **PASS** | §4 titled "mandatory"; "product requirement, not styling, and not optional"; repeated in all 8 skills |
| No implication paid runs bypass approval | **PASS** | §1: "Nothing in this document authorizes an agent to spend on a user's behalf without their explicit go-ahead"; every skill block: "sets *how much* to invest; it never affects *whether* approval is required — it always is" |
| Cost avoidance removed as default posture | **PASS** | "**Do not default to recommending zero spend.**" leads all 8 blocks |
| Mock/approval/caps/receipts/stop rules/prod safety preserved | **PASS** | Explicit non-changed list in §1; no existing safety text removed (diff is additive: +260/−16, deletions are only version + doc_hash lines) |
| No nonexistent MCP tool taught | **PASS** | §6 states plainly "There is no Traigent survey tool to call today"; no tool-call syntax anywhere |
| Local uncommitted draft | **PASS** | `.traigent/economics-survey.v0.json` + `.gitignore` instruction + "nothing is transmitted" |
| Provenance hashes valid | **PASS** | `test_provenance.py` green; `doc_hash == live SKILL.md` 8/8; `doc_after_hash == doc_hash` 8/8 |
| Protected regions undisturbed | **PASS** | `test_interaction_policy.py` green; insertions placed after `## When to Use`, outside all PROTECTED/SLOW_UPDATE regions |
| analyze-guidance authors no budget locally | **PASS** | `test_analyze_guidance_does_not_author_a_budget_locally` + `..._carries_no_budget_arithmetic`; the lint was shown to fire on the pre-repair wording |
| All 5 closed values reachable within the 3-option cap | **PASS** | `test_every_closed_value_is_reachable_without_breaking_the_option_cap` — for every field, for **every** choice of recommendation |
| Contract tests pass | **PASS** | 849 passed / 0 failed (806 baseline + 43 new) |

## Risks and owner-visible notes

1. ~~**`traigent-analyze-guidance` doctrinal tension.**~~ **Repaired.** Terra was right that
   this was a contradiction, not a tension to note: the skill claimed local economics shapes
   *how much* to propose while being lint-enforced as a thin client. It now collects and
   relays the characterization and presents **only** a service-authored budget; with no
   economics result from the service it says so and stops, or falls back with no number.
   Regression-linted. See the repair report.

2. ~~**3-option cap vs. 5 closed values.**~~ **Repaired.** The old resolution ("full list on
   request") left the remaining-options behavior undefined. §4 now defines a concrete paging
   rule — page 1 is the recommendation plus up to 2 alternatives; every later page carries the
   *same* recommendation plus up to 2 unseen values; ≤3 options and exactly one **Recommended**
   per page; five values need at most two pages; a value is never dropped for not fitting.
   Property-tested for every field and every choice of recommendation.

3. ~~**Pointer style, not synced-region style.**~~ **Repaired — the claim in this slot was
   wrong.** It said the plugin ships the whole repo "so the path does resolve for installed
   users". That is true only for the full-plugin install. The two documented single-skill
   paths (`npx skills add --skill <one>`, `cp -r traigent-skills/skills/<one> ...`) copy one
   skill directory, so `docs/shared/...` was a dangling pointer for exactly the users most
   likely to hold one skill. The reference is now generated into each skill, and the test
   proves it from the **installed layout** rather than the source tree.

4. **All dollar figures are unvalidated starting assumptions.** The reference says so at the
   top and labels the archetype table accordingly. Nothing in the copy presents them as
   validated — WI-B's funnel data is what would validate them.

5. **Not done (out of scope, by design):** no `sync_map.yml` / `coverage_ledger.yml` entry for
   the new doc (neither indexes `docs/`, and both are outside the write scope); no telemetry
   (WI-B); no MCP tool or calculator (WI-C); no incentives (WI-D).

## Blockers

None. The work is complete and the contract suite is green.

---

## Sol remediation (2026-07-18)

Sol issued SHIP NO-GO on WI-A with four merge-blockers. All are addressed here in the
`feature/econ-model-wi-a` worktree (uncommitted). TraigentSchema `@ c27a034` is canonical and
was read-only.

### 1. Adopt the canonical TraigentSchema vocabulary (contract-first)
The shared reference `docs/shared/economics-characterization.v0.md` now uses the Schema enums
exactly, across Q1–Q5 option tables, the §4 paging worked example, and the §6 local-draft JSON:

| Field | Was (skills) → Now (Schema) |
|---|---|
| `value_channel` | `developer_time_saved/manual_ops_replaced/volume_throughput/revenue_growth/mistake_prevention` → `save_expert_time/replace_manual_operations/process_volume_cheaper/increase_revenue/prevent_costly_mistakes` |
| `daily_volume_band` | `band_lt_100/band_100_999/band_1k_99k/band_100k_999k/band_1m_plus` → `under_100/100_to_999/1k_to_99k/100k_to_999k/1m_or_more` |
| `error_cost_band` | `retry_lt_1/human_fix_1_50/escalation_50_5k/severe_gt_5k/not_measured` → `cheap_retry_under_1_usd/human_correction_1_to_50_usd/escalation_50_to_5k_usd/severe_harm_above_5k_usd/not_measured` |
| `lifecycle_stage` | `build_no_trusted_eval/build_with_trusted_eval/limited_prod_self_paid/full_prod_self_paid/prod_customer_paid` → `building_without_trusted_eval/building_with_trusted_eval/limited_production_we_pay/full_production_we_pay/production_customer_pays` |
| `human_cycle_hours_band` | `lt_1h/1_8h/8_40h/gt_40h_or_specialist/not_measured` → `automated_under_1h/1_to_8h/8_to_40h/over_40h_or_specialist/not_measured` |

Field names already matched the Schema (`value_channel`, `daily_volume_band`, `error_cost_band`,
`lifecycle_stage`, `human_cycle_hours_band`, plus the typed overrides incl. `value_per_task_usd`).
The 8 generated skill copies were re-synced byte-identical via
`tools/contract/sync_economics_reference.py`.

**Schema-backed test (fails closed if the sibling is absent):**
`test_documented_band_values_match_schema_enum_exactly` (5 params, one per field),
`test_documented_field_names_match_schema_field_allowlist`, and
`test_documented_survey_json_values_are_schema_enums` load the sibling
`TraigentSchema/traigent_schema/schemas/economics/economics_characterization_vocabulary_schema.json`
(searched under a `TraigentSchema*` sibling or `$TRAIGENT_SCHEMA_REPO`) and assert the doc's
tokens are exactly the Schema enums/field allowlist. If the sibling is not present they
`pytest.skip` with a reason — never a false pass.

### 2. "Characterize, never compute a budget locally" across ALL EIGHT skills
Previously only `traigent-analyze-guidance` carried the service-owned-budget boundary; the
other seven implied local sizing ("propose a bounded first experiment sized to it", "enforce
the calculated cap"). All eight economics `SKILL.md` sections now state the boundary
(budget authorship belongs to the service; no local arithmetic; when no service result,
give no number). The reference §7 was rewritten from a followable local calculator (the
`B_day = clamp(...)` formula, the archetype floor/cap dollar table, `payback_days = ...`, and
the EVSI/UCB/LCB inequalities) into a description of WHAT the service computes, explicitly
stating there is no budget to compute locally until the WI-C backend calculator ships.

**Lint extended to all eight (previously analyze-guidance only):**
`test_no_skill_authors_a_budget_locally`, `test_every_skill_states_the_service_owned_budget_boundary`,
and `test_no_skill_carries_budget_arithmetic` are now parametrized over all 8 economics skills;
`test_reference_carries_no_followable_budget_arithmetic` guards the shipped reference (no
`B_day=`/`clamp(`/`0.10 ×`/`payback_days=`, no archetype floor/cap table).

### 3. Scope the Track R2 claim as one pilot, not a general law
§1 no longer asserts "In practice that produced agents that proposed `$0` and never started."
It now reads "A single Track R2 pilot observed that this cost-caution-first wording led
autonomous coding agents to propose `$0` and never start … candidate, unvalidated evidence
from one pilot — a motivating observation, not a general law." This matches the §1 status
("v0 — a starting model, not a validated one").

### 4. PROTECTED/SLOW_UPDATE + provenance-hash machinery respected
No PROTECTED/SLOW_UPDATE regions were edited. Reference copies were regenerated via the
documented tools; `reference_hashes` refreshed via `tools/contract/update_reference_hashes.py`
(both `--check`s clean). The 7 edited `SKILL.md` files had `metadata.version` bumped, `doc_hash`
recomputed (SHA-256[:16] of the new bytes), and a `manual_edit` provenance audit entry appended
(`economics-schema-vocabulary-alignment-2026-07-18`).

### Test counts
- Full contract suite: **878 passed, 451 skipped** (baseline before remediation: 849 passed,
  451 skipped; net +29 from the new/extended economics tests — Schema cross-check present and
  passing in this workspace).
- `tests/contract/test_economics_reference.py` alone: **71 passed**.
- `tools/contract/sync_economics_reference.py --check` and
  `tools/contract/update_reference_hashes.py --check`: both clean.

### Residuals
- The 7 Schema-backed cross-check tests SKIP (never fail) in a skills-only CI checkout without
  the sibling `TraigentSchema` (or `$TRAIGENT_SCHEMA_REPO`). They passed here because the
  sibling worktree is present.
- Report residual #4 above ("archetype table") is superseded: that table was removed in fix #2.
- WI-C (backend calculator) and WI-D (pricing) remain out of scope; until WI-C ships the skills
  characterize and relay only, with no local budget number.
