# Skill Evaluation Artifacts

This directory holds public gate artifacts only: manifests, baseline metadata, and provenance conventions. The evaluation harness, task corpus, and held-out splits live in a private harness repository.

`baselines.json` carries hashes and scores only. Do not include task prompts, examples, traces, datasets, private corpus references beyond opaque identifiers, secrets, or user content in public baseline artifacts.

When a CI check is added for these files, it is advisory hash-consistency only. It is explicitly not a trust gate. An enforcing gate requires a signed-report trust root; owner decision pending.

## Protected Regions

`SKILL.md` frontmatter is implicitly protected because YAML must remain the first block in each skill file. Do not wrap frontmatter in HTML markers.

Use `<!-- PROTECTED -->` and `<!-- /PROTECTED -->` only for invariant claim-scope, caveat, and safety constraints. Use the reserved `<!-- SLOW_UPDATE -->` region for epoch-level longitudinal guidance only; step-level edits must not write there.

## Provenance v1

Each skill has `skills/<name>/provenance.json`:

- `schema`: currently `skill-provenance/v1`.
- `doc_hash`: first 16 hex characters of the SHA-256 hash of the corresponding `SKILL.md` bytes.
- `entries`: applied, gate-rejected, or skipped edit records.

The genesis entry records the baseline snapshot at adoption. Future optimizer entries use this field contract, aligned one-to-one with the trainer's edit-apply records (text fields are replaced by hashes — raw anchor or edit text never appears in this public file):

- `edit_id`; `op` (`append`, `insert_after`, `replace`, or `delete`)
- `target_hash`, `content_hash`: 16-char SHA-256 prefixes of the private anchor/content text
- `source_type` (`failure`, `success`, `slow_update`, or `human`); `support_count`
- `status` (`applied`, `rejected_gate`, `skipped_target_not_found`, `skipped_protected_region`, `skipped_invalid`, or `skipped_duplicate`)
- `epoch`, `step`, `selection_score_before`, `selection_score_after`
- `run_id`, `timestamp`, and record-level `doc_before_hash` / `doc_after_hash`

Only `applied` entries on an accepted candidate change the deployed document; `rejected_gate` and `skipped_*` entries are negative-evidence records.

Never put task or example content in `provenance.json`. Store only hashes, scores, identifiers, statuses, and timestamps.

## Version Discipline

Any future `SKILL.md` instructional content change must bump that skill's `metadata.version`. The marker and provenance adoption keeps existing `metadata.version: "1.0"` values; this version-bump rule starts with the next content change.

Baselines are keyed by document hash, so stale baselines are mechanically detectable when skill content changes.
