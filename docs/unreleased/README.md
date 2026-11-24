# Unreleased SDK material

Skill text for SDK features that are merged to the SDK's `develop` branch but are not in any
released SDK. It lives here, **not** in `skills/`, until the release that carries the feature
exists on PyPI.

Why not in a skill: the contract harness collects every `traigent ...` command, Python symbol and
`TRAIGENT_*` variable from `skills/**/SKILL.md` and `skills/**/references/*.md` and checks it
against each released SDK bucket in `sync_map.yml`. A command that no released SDK has fails
those buckets, and the only version gates are per-skill (`min_sdk_version`, which must stay a
released version because every distinct value becomes a `pip install traigent==<version>`
bucket) or per-reference-file for Python facts (`python_version_floors`), not for CLI commands.
Teaching an unreleased command in a skill would also tell a user on the shipping SDK to run
something that does not exist. This directory is outside the harness's scanned corpus
(`tests/README.md`, "Doc-claim stamps"). The history is in `git log -- docs/unreleased`: the
cold-start reference sat here until the release shipped it (commits 95ee35a, then de56e0b).

Each file here is written in the voice of the final skill text, with one placeholder,
`<RELEASE>`, for the SDK version that first carries the feature. Do not guess it: the SDK
`develop` branch reports `0.33.0.dev0` and which release will carry these features is not
decided.

## Index

| File | SDK features | Moves into |
|---|---|---|
| `regression-set-and-repeat-outcomes.md` | Repeat outcomes (`example_consistency()`, the `traigent results show` line); `traigent regression add`, `confirm`, `check` | `traigent-analyze-results`, `traigent-dataset-curate`, `traigent-ci-safety-gate` (+ `references/gate-workflow.md`), `traigent-debugging` |

## Activating a file at release

`tests/contract/test_unreleased_material.py` fails once a released SDK bucket contains the
feature, and fails if a skill teaches it while its file is still here. When it goes red on the
bucket check, do these steps in one PR:

1. Set `current_released_sdk_version` in `sync_map.yml` to the release (the bucket that installed
   it), and, if you add a `docs/version-matrix.md` row for it, add the release to the static tag list in `tests/contract/test_version_matrix.py`
   (that test requires it).
2. Replace `<RELEASE>` with the real version in the file. Confirm each command, flag, exit code
   and message against the released SDK source, not against `develop`.
3. Move each `## Move into: <skill>` section to the place named under it. Keep the sentence
   "Requires SDK <version> or newer." at the head of each. Remove the `Move into:` lines.
4. The moved text teaches `traigent regression ...`, and CLI facts are checked in every bucket
   from the skill's `min_sdk_version` up, so older buckets would fail. Once `<RELEASE>` is on
   PyPI it is a valid `min_sdk_version`: set it for each of the four skills in `sync_map.yml`
   (cost, noted when cold-start was added in b0e4cde: that skill's older facts stop being
   checked in older buckets). If the harness has gained a per-file floor for CLI facts by then,
   use that instead. Run `python tools/contract/list_buckets.py` to confirm every bucket still
   resolves.
5. Regenerate the provenance of every edited skill (`python tools/contract/update_reference_hashes.py`
   and the per-skill `doc_hash` as the existing provenance tests require), add a provenance
   entry per skill, and bump each edited skill's `metadata.version`.
6. Delete the moved file from this directory (and this index row; delete the directory when
   empty), then run `python -m pytest tests/contract --sdk-version=<RELEASE> -q`.
7. If a coverage-ledger or interface-inventory test names the new CLI commands
   (`py:cli#regression add` and so on), teach or waive them as `coverage_ledger.yml` describes.
