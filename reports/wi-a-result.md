# WI-A result — skills posture + template survey + explanation duty

- **Repo / branch / base:** `Traigent/traigent-skills` | `feature/econ-model-wi-a` | `origin/main`
- **Worktree:** `/home/nimrod/TraigentProjects/worktrees/econ-model-2026-07-17/traigent-skills`
- **Governance:** Spine-Trail `st_6443b96904d7`; replacement ChangeSession `cs_8e10a485f94fda03`
- **Scope note:** WI-D incentives excluded. No commit, push, PR, or merge performed.
- **PR-ready:** **YES** (with two owner-visible notes in *Risks*, neither blocking)

## What changed

One new canonical reference, eight skills pointed at it. The posture is written **once**.

### New — the single source of truth

`docs/shared/economics-characterization.v0.md` (new, 1 file):

| Section | Contents |
|---|---|
| §1 Posture | The **exact** session3 §2 three-sentence posture, verbatim, quoted once |
| §1 (cont.) | What changed (cost avoidance is no longer the default) and the explicit list of safety rules that did **not** change |
| §2 | All five session2 questions — canonical wording **and** slot-tailored templates — with all exact options mapped to closed enum values |
| §3 | Who asks: the user's actual coding agent; name the real agent, infer first, confirmations carry evidence, Q1+Q3 always explicitly confirmed, Q2/Q4/Q5 only when not confidently inferable, target 2 asked |
| §4 | The explanation duty: options + one recommendation + WHY in the user's own numbers — stated as a product requirement, not styling |
| §5 | Templates/tailoring are suggestions; the closed submission is the commitment |
| §6 | Until a submission path exists: write the closed draft to `.traigent/economics-survey.v0.json`, local + uncommitted, nothing transmitted |
| §7 | Budget/floors/caps, payback, stop rule, receipts, credibility rules — all labeled starting assumptions |

### Modified — eight skills (SKILL.md + provenance.json each)

Each got one `## Optimization Economics — Read This Before Sizing a Run` section inserted
immediately after `## When to Use` (outside every PROTECTED / SLOW_UPDATE /
INTERACTION_POLICY region), containing: a pointer to the shared reference, the skill's own
role per session3 §2, the mandatory explanation duty, and the unchanged-safety restatement.
**The three-sentence posture is not reproduced in any of them.**

| Skill | Version | doc_hash before → after | Role (session3 §2) |
|---|---|---|---|
| traigent-setup-quickstart | 1.0.18 → **1.0.19** | `3a19554c5624fb4f` → `d1fcc507af83c0ee` | characterize value, propose bounded first experiment |
| traigent-boost-agent | 2.1.6 → **2.1.7** | `23c57e5772586d93` → `4665b7cf92bd385a` | characterize value, propose bounded first experiment |
| traigent-optimize-run | 1.0.13 → **1.0.14** | `ad8b4d5c3c32a975` → `738713d34a109be3` | enforce cap, receipt, stop rule |
| traigent-setup-decorator | 1.0.9 → **1.0.10** | `3db71bdafe5e0a1a` → `7af2edc441c2c350` | make cap/receipt/stop rule enforceable |
| traigent-analyze-guidance | 1.1.0 → **1.1.1** | `51a8c8aea0c8cf0f` → `368bf51ad808152b` | weigh next-run cost vs conservative value + value of further information |
| traigent-analyze-results | 1.1.13 → **1.1.14** | `39352a037b3de5b2` → `3e30b2333041940f` | winner / no-gain / insufficient-evidence receipt |
| traigent-dataset-curate | 1.1.2 → **1.1.3** | `f5481ef2791c45ef` → `34eec3149f68cccd` | confirmed defect receipts, human-QA equivalence |
| traigent-eval-audit | 1.1.4 → **1.1.5** | `0cfbd5cc6be2f30e` → `08dc15f37da5a849` | confirmed defect receipts, human-QA equivalence |

Every `provenance.json` got its `doc_hash` updated plus **one** appended `manual_edit` record
(`edit_id: economics-bounded-investment-posture-2026-07-17`) following the existing format
exactly: `edit_id, op, status, run_id, timestamp, doc_before_hash, doc_after_hash, note,
source_type`. Provenance was edited by surgical string replacement rather than a JSON
round-trip, because `traigent-boost-agent` and `traigent-analyze-results` contain raw
em-dashes in existing entries that `json.dump(ensure_ascii=True)` would have re-escaped —
that would have produced unrelated churn. Diff is +13/-1 lines per file, nothing else touched.

**Full change set (17 files, all in scope; verified nothing outside scope was touched):**
1 new `docs/shared/economics-characterization.v0.md`; 8 × `SKILL.md`; 8 × `provenance.json`.

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
not pin the SDK, so it must be installed to get a real signal):
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
| One source of truth, no duplicated posture | **PASS** | `grep -rl "bounded investment, not a cost to avoid by default"` returns **exactly one** file |
| All 8 skills point at it | **PASS** | 1 pointer each, 8/8 |
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
| Contract tests pass | **PASS** | 806 passed / 0 failed |

## Risks and owner-visible notes

1. **`traigent-analyze-guidance` has a doctrinal tension worth a reviewer's eye (non-blocking).**
   That skill is lint-enforced as a *thin client* that must defer next-step decisions to the
   Traigent service (`test_next_run_skill_stays_service_decided_thin_client`), while the shared
   economics reference contains local budget arithmetic. I scoped its block to *how much* to
   propose and added an explicit sentence that it "never overrides the Traigent service, which
   still owns the next-step decision itself". The lint passes, and no banned local-decision
   vocabulary (`formula`, `threshold`, …) appears in the block. When WI-C makes the calculator
   backend-authoritative this tension disappears — the skill will call it rather than reason
   locally. Flagging it so it is a conscious call, not an accident.

2. **The interaction policy caps presented options at 3; the closed fields have 5 values.**
   A real contradiction between two shipped policies. Resolved explicitly in §4: present the
   recommended value plus one or two nearest alternatives (3 shown, 1 recommended), full list
   on request, while the *submitted* value must still be one of the five closed values.
   Presentation narrows; the contract does not. Worth owner confirmation that this is the
   intended reconciliation.

3. **Pointer style, not synced-region style.** The existing shared doc
   (`interaction-policy.v1.md`) is *copied* into every skill by
   `tools/contract/sync_interaction_policy.py`. WI-A explicitly required pointing without
   duplicating, so I used a repo-relative path pointer — the same convention `docs/version-matrix.md`
   already uses. Consequence: there is **no** sync tool or hash-pinning guarding the economics
   reference, so a skill pointer could drift from the file's contents without a test noticing.
   The plugin ships the whole repo (`marketplace.json` `source: "./"`), so the path does
   resolve for installed users. If drift protection is wanted later, the cheap fix is a lint
   asserting each of the 8 skills contains the pointer string.

4. **All dollar figures are unvalidated starting assumptions.** The reference says so at the
   top and labels the archetype table accordingly. Nothing in the copy presents them as
   validated — WI-B's funnel data is what would validate them.

5. **Not done (out of scope, by design):** no `sync_map.yml` / `coverage_ledger.yml` entry for
   the new doc (neither indexes `docs/`, and both are outside the write scope); no telemetry
   (WI-B); no MCP tool or calculator (WI-C); no incentives (WI-D).

## Blockers

None. The work is complete and the contract suite is green.
