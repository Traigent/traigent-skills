# WI-A review repair — Terra BLOCK findings

- **Repo / branch / base:** `Traigent/traigent-skills` | `feature/econ-model-wi-a` | base candidate `645264f` (parent `origin/main`)
- **Worktree:** `/home/nimrod/TraigentProjects/worktrees/econ-model-2026-07-17/traigent-skills`
- **Governance:** ChangeSession `cs_8e10a485f94fda03`; Spine-Trail `st_6443b96904d7`
- **Model identity:** Claude Opus 4.8 (`claude-opus-4-8`), Claude Code implementation worker
- **Scope:** repair of the three Terra BLOCK findings on WI-A only. No WI-B/WI-C/WI-D work, no
  unrelated skills touched, **no commit, push, or PR**. Captain owns refs and final review.
- **Status:** all three findings repaired; full contract suite green (849 passed, 0 failed).

## Finding 1 (High) — the canonical reference was unreachable from a single-skill install

**The finding was correct.** Every changed skill pointed at `docs/shared/economics-characterization.v0.md`.
The repo's own README documents two single-skill install paths that copy **one skill directory**
and nothing else:

```bash
npx skills add Traigent/traigent-skills --skill traigent-setup-quickstart
cp -r traigent-skills/skills/traigent-setup-quickstart .agents/skills/
```

Under either one, `docs/` does not exist on the user's machine, so the pointer named a file
the agent could never read. The original report's defense ("the plugin ships the whole repo, so
the path does resolve") held only for the full-plugin install — the narrower the install, the
more certainly the reference was missing.

**Repair — generate, don't re-author.** The doc stays authored in exactly one place; a
generator propagates byte-identical copies into the skills that use it:

- `tools/contract/sync_economics_reference.py` (new) — copies
  `docs/shared/economics-characterization.v0.md` → `skills/<name>/references/economics-characterization.v0.md`
  for every skill whose SKILL.md carries the pointer marker (**discovered, not hardcoded**, so
  adding or dropping a skill cannot silently desync). `--check` exits 1 on missing, stale, or
  orphaned copies and is the CI-usable gate.
- All 8 SKILL.md pointers now name `references/economics-characterization.v0.md` — a
  skill-relative path that resolves in **every** install — and cite the `docs/shared` path only
  as the generated-from source, so contributors still know where edits go.
- README gained an "Optimization economics" section documenting the source of truth, the
  generator, and the rule that the copies are generated artifacts.

**This is the repo's existing pattern, not a new one.** `docs/shared/interaction-policy.v1.md`
is already propagated into every SKILL.md by `sync_interaction_policy.py` for exactly this
reason. Terra's "preserve ONE source of truth" constraint is met in the sense that matters:
one file is authored and reviewed; the eight copies are mechanically derived and cannot drift
(`test_shipped_reference_is_byte_identical_to_canonical`), and a hand-edited copy fails the
suite. The alternative — inlining 349 lines of posture into eight SKILL.md files — is the
eight-way duplication WI-A explicitly forbids.

**Proof is against the installed layout, not the source tree**, as required:
`test_single_skill_install_can_read_the_reference` copies each skill directory **alone** into a
tmpdir (no repo around it, no `docs/`), then asserts the reference exists there, is readable,
carries the posture, and contains all five closed fields.

## Finding 2 (High) — analyze-guidance contradicted its own thin-client boundary

**The finding was correct.** The skill said local economics "shapes *how much* to propose"
while the same file is lint-enforced as a thin client that defers decisions to the service, and
WI-C (the service that would author a budget) does not exist yet. The original report noted the
tension and shipped it anyway; that was the wrong call — a skill that both defers to a service
and shapes the number locally will invent a number when the service is silent.

**Repair.** The economics block now reads: collect and relay, never compute.

- Collect the characterization, pass it to the service, present **only the budget the service
  returns**, with the service's why. Budget authorship belongs to the service, exactly as the
  run-plan and next-step decision do.
- "**Do not compute, adjust, or recommend a budget locally**" — no budget arithmetic, no
  scaling the returned number, no "roughly $X/day" of its own.
- **No service economics result → say so and stop, or fall back to Mode C with no budget
  number at all.** Explicitly: "Diagnosis without a budget is a valid answer; an invented
  budget is not. There is no local fallback calculator."

**Regression lint** (`test_economics_reference.py`): a narrow pattern set rejects
budget-authorship phrasings, a second test requires the boundary sentences, and a third rejects
budget arithmetic (`B_day =`, `clamp(`, `0.10 ×`) in the skill. I verified the lint **fires on
the exact pre-repair wording** and does not self-trip on the negated forms it requires — a lint
that cannot fail is not a lint.

**The repo's existing lint caught me mid-repair.** My first draft said "the reference's
formulas document what the service computes";
`test_next_run_skill_stays_service_decided_thin_client` bans `formula` in this skill and failed.
I reworded to "the reference describes what the service computes" rather than touch the gate
(workspace Rule 9: never relax a gate to make a change pass). The gate was right.

## Finding 3 (Medium) — 3-option cap vs. five closed enum values

**The finding was correct.** "Present the nearest one or two alternatives, full list on
request" defined page 1 and left the rest undefined: what the *remaining* options look like,
whether the recommendation survives into them, and whether the cap still holds.

**Repair — a concrete paging rule** in the canonical doc §4, retitled "Reconciling with the
interaction policy's three-option cap — the paging rule":

| | Contents | Recommended |
|---|---|---|
| **Page 1** | recommendation + up to 2 most plausible alternatives | the recommendation |
| **Page 2+** | the **same** carried recommendation + up to 2 values not yet shown | the same one |

Invariants stated in the doc and enforced by tests: ≤3 options per page; exactly one
**Recommended** per page; the recommendation is the agent's standing answer for the whole field
and only changes if the user says something new (and if it changes, the agent says so); no value
is ever dropped for not fitting; five values need at most two pages; the user may pick any of
the five at any time, including one not yet shown. The submitted value is still one of the five
closed values — **presentation narrows, the contract does not.** A worked example for
`error_cost_band` shows both pages. Options + one recommendation + WHY remains mandatory for
every question and confirmation — the paging rule constrains *layout*, never the explanation
duty.

**Tests:** enum values are parsed **from the doc itself** (not restated in the test), then the
paging rule is simulated for every field **and every possible choice of recommendation**,
asserting full reachability, the cap, exactly one Recommended per page, and ≤2 pages. The doc's
own worked example is parsed and checked against the same rule, so an example that contradicts
its rule fails.

## Files changed

| File | Change |
|---|---|
| `tools/contract/sync_economics_reference.py` | **new** — generator + `--check` gate |
| `tests/contract/test_economics_reference.py` | **new** — 43 tests (install reachability, budget lint, paging property) |
| `docs/shared/economics-characterization.v0.md` | header rewritten (sync mechanism, generated artifacts); §4 paging rule + worked example |
| `skills/{8}/SKILL.md` | pointer → `references/economics-characterization.v0.md`; version bump; analyze-guidance economics block rewritten |
| `skills/{8}/references/economics-characterization.v0.md` | **new (generated)** — byte-identical to canonical |
| `skills/{8}/provenance.json` | appended repair record; `doc_hash` + `reference_hashes` refreshed |
| `README.md` | new "Optimization economics" section |
| `tests/contract/test_skill_names.py` | one ALLOWLIST entry + justification |

The eight skills: `traigent-setup-quickstart`, `traigent-boost-agent`, `traigent-optimize-run`,
`traigent-setup-decorator`, `traigent-analyze-guidance`, `traigent-analyze-results`,
`traigent-dataset-curate`, `traigent-eval-audit`.

**The one test-file edit is an allowlist, not a relaxed gate.** `test_prose_skill_references_exist`
asserts every `traigent-*` token in skill prose is a real skill dir. The reference's local draft
record carries `"schema": "traigent-economics-survey/v0"` — a schema identifier from the
session-4 design, not a skill reference. It was already in the repo (in `docs/`, out of the
test's scan scope); shipping the doc inside skills brought it into scope. Allowlisted with a
justification comment, per the file's own documented convention. No assertion was weakened.

### Provenance / version discipline

SKILL.md bytes changed, so all 8 skills bumped a patch version and appended **one new**
`manual_edit` record (`edit_id: economics-reference-install-reachability-2026-07-17`). The
original `economics-bounded-investment-posture-2026-07-17` record is untouched — hashes chain
`before → after → after'`, and nothing was rewritten or backdated. `analyze-guidance` carries an
extended note covering the thin-client repair. Versions: quickstart 1.0.19→**1.0.20**,
boost-agent 2.1.7→**2.1.8**, optimize-run 1.0.14→**1.0.15**, setup-decorator 1.0.10→**1.0.11**,
analyze-guidance 1.1.1→**1.1.2**, analyze-results 1.1.14→**1.1.15**, dataset-curate 1.1.3→**1.1.4**,
eval-audit 1.1.5→**1.1.6**. `docs/shared/` and the generated references are not SKILL.md bytes
and carry no version of their own; the generated copies are pinned by `reference_hashes`
(refreshed via `tools/contract/update_reference_hashes.py`) and by byte-identity to the canonical.

## Commands run and results

Existing SDK environment (`.venv`, `traigent==0.23.0` per `sync_map.yml`).

```
# Baseline BEFORE any repair edit — establishes the control
.venv/bin/python -m pytest tests/contract -q
→ 806 passed, 451 skipped, 1 warning in 74.57s   (0 failed)

# Generator
.venv/bin/python tools/contract/sync_economics_reference.py
→ Updated 8 skill reference copy(ies)
.venv/bin/python tools/contract/sync_economics_reference.py --check
→ All 8 economics skill(s) carry the current reference.   (exit 0)
.venv/bin/python tools/contract/update_reference_hashes.py
→ Updated 8 provenance file(s).

# New focused suite
.venv/bin/python -m pytest tests/contract/test_economics_reference.py -q
→ 43 passed in 0.35s

# Full contract suite AFTER repair
.venv/bin/python -m pytest tests/contract -q
→ 849 passed, 451 skipped, 1 warning in 74.72s   (0 failed)

# Repo-forensics suite (unchanged by this work)
.venv/bin/python -m pytest tests/repo_forensics tests/test_repo_forensics_ioc_manager.py -q
→ 14 passed
```

849 = 806 baseline + 43 new. **Zero pre-existing failures, zero new failures**; no test was
skipped, weakened, or deleted to get there.

**Two real failures surfaced mid-repair and were fixed at the source, not the gate:**
`test_next_run_skill_stays_service_decided_thin_client` (banned `formula` in analyze-guidance —
reworded), and `test_prose_skill_references_exist` (the schema identifier, allowlisted above).
Both are the packaging change doing its job: moving the reference into `skills/` deliberately
puts it under every skill-text lint, which is a feature — the reference is now held to the same
bar as the skills that ship it.

**Guard-the-guards checks** (each new gate proved able to fail):

| Gate | Proof it bites |
|---|---|
| byte-identity of generated copies | `test_sync_tool_detects_a_tampered_copy` copies the repo, hand-edits one copy, asserts `--check` exits 1 |
| analyze-guidance budget lint | verified it fires on the **exact pre-repair wording** (2 patterns matched, 3/3 required sentences missing) and on probe phrasings (`compute the budget yourself`, `derive a budget from the bands`, `estimate a daily budget locally`); clean on current text |
| paging reachability | a deliberately cap-violating pager (all 5 on one page) fails the property |
| economics-skill discovery | `test_economics_skills_are_discovered` fails loudly if a pointer rename empties the set, instead of passing vacuously over zero skills |

## Residual risks

1. **`npx skills add` is verified by inference, not execution.** The tests prove the
   directory-copy layout (`cp -r skills/<one> ...`, the README's manual path). `npx skills`
   documents itself as copying each skill into the agent's folder, which is the same shape, but
   I did not run it — it needs network access I don't have here. If the captain wants the
   stronger evidence, one real `npx skills add --skill traigent-setup-quickstart` and an `ls`
   of `references/` closes it.
2. **The paging rule is markdown, enforced against markdown.** The tests prove the *rule* is
   coherent, complete, and matched by the doc's own example. They cannot prove a coding agent
   obeys it at runtime — that is a behavioral property no doc-contract test reaches. It would
   need an eval; the Track-R2-style simulation harness is where that belongs.
3. **The economics reference is now under every skill-text lint.** Correct, but it means future
   edits to the canonical doc can fail the contract suite for reasons that look unrelated (as
   `traigent-economics-survey` did). The sync tool prints the `update_reference_hashes.py`
   reminder; the failure modes are legible; but it is a new coupling worth knowing about.
4. **`sync_economics_reference.py --check` is not yet wired into CI.** The suite covers the same
   ground via `test_economics_reference.py`, so the gate holds through pytest. If the repo wants
   the tool itself in a workflow step alongside `sync_interaction_policy.py --check`, that is a
   one-line addition — I left the workflows untouched as out of scope.
5. **Finding 2's repair describes a service that does not exist yet (WI-C).** Today the honest
   path is the one now written: no service economics result → no budget number. This makes the
   skill *correct* and *less useful* until WI-C ships — the deliberate trade Terra asked for
   (a missing number beats an invented one). Worth the owner knowing the eight skills now teach
   the bounded-investment posture while `analyze-guidance` specifically cannot yet hand over a
   budget.
6. **The generated copies add ~8 × 349 lines to the repo.** Real weight, but they are
   mechanically derived, never hand-reviewed, and the alternative was either eight-way authored
   duplication or a dangling pointer for single-skill users.

## Owner decisions

None required. All three findings are repaired within the assignment's stated bounds; no
pricing, product, or scope choice arose that needs a call. The residual risks above are
disclosures, not open questions.
