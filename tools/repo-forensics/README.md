# Vendored: repo-forensics scanner

This directory is a **pinned, vendored copy** of the `repo-forensics` scanner
(pure-stdlib Python, zero dependencies, fully offline), used only by the
[`Forensics Gate`](../../.github/workflows/forensics.yml) CI workflow.

It is **not a skill** — it lives outside `skills/`, so `npx skills add` never
installs it and the gate never scans it.

The gate runs it as: `run_forensics.sh <repo>/skills --skill-scan` — the
skill-vetting mode (9 scanners incl. skill-threat detection), with a
**zero-tolerance** policy: any finding of any severity fails the gate. The
baseline is 0 findings.

## Why vendored (not fetched)

The gate runs on pull requests, including PRs from forks. Fork PRs don't get
repository secrets, so a token-authenticated fetch from the internal
`Traigent/agents-skills` repo would silently skip exactly the PRs we most want
to scan. Vendoring keeps the gate hermetic and fork-safe.

We deliberately do **not** fetch the public upstream at CI time: it has
drifted from this snapshot, and its `--skill-scan` correlation engine
false-positives on our own SDK documentation (env-var examples + LLM calls).
This vendored snapshot is 0 findings on `--skill-scan`.

## Source & updating

- Upstream origin: [`alexgreensh/repo-forensics`](https://github.com/alexgreensh/repo-forensics)
- Maintained snapshot: `Traigent/agents-skills` → `skills/repo-forensics/skill/scripts/`

To update, re-copy `scripts/` from the agents-skills snapshot after reviewing
the diff, then confirm `run_forensics.sh <repo>/skills --ci-own` stays clean.
