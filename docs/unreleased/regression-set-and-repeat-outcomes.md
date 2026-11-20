# Repeat outcomes and the regression set (unreleased)

Status: not in any released SDK. Requires SDK `<RELEASE>` or newer. Written for the skills
named in each `Move into:` line; see `README.md` in this directory for how to activate it.
Do not teach these commands from a skill before `<RELEASE>` is on PyPI.

Everything below runs locally. No command here calls the Traigent backend. `confirm` and
`check` run your own `@traigent.optimize` function, so your own model provider is called and
costs money unless the function is mocked.

---

## Move into: traigent-analyze-results

Place after "Per-Example Diagnostics: Your Eval Set Is Also Under Test".

### Repeat outcomes: which examples are stable

Requires SDK `<RELEASE>` or newer.

When the winning configuration is evaluated more than once on the same examples, each example
gets a label from its per-attempt outcomes:

- `all_pass`: every scored attempt passed.
- `all_fail`: every scored attempt failed.
- `mixed`: both outcomes occurred.

Where the data comes from:

- A run with `winner_stability_reps >= 2` records it for the winner. Read it with
  `result.example_consistency()`.
- A comparison with `repeats >= 2` (`function.compare([...], repeats=3)`) holds it per
  configuration: `comparison.example_consistency(config_index)` (default `0`). With
  `repeats=1` no example has two evaluations and `examples` is empty. This one is computed from
  the in-memory result and is not saved.
- `traigent results show RESULT_NAME` prints one line when a report was stored:
  `Repeat outcomes (winner, N reps): A all_pass, B all_fail, C mixed, D errored; all_pass at N/N means a 95% interval of low-high on the pass rate`.
  If the stored report cannot be read, the line says it was skipped; the command still exits normally.

The report is a dict: `counts` (per label plus `errored`), `examples` (per example id:
`label`, `attempted`, `passes`, `fails`, `errored`, `pass_rate_low`, `pass_rate_high`), `reps`,
`config_hash`, `metric`, `threshold`.

How to read it:

- Pass or fail is the per-example `score` (else `accuracy`) against `threshold` (0.5).
  That is only meaningful for a higher-is-better score in `[0, 1]`. For a lower-is-better or
  differently scaled metric the labels are not meaningful; check `metric` and `threshold`
  first and say which rule applied.
- An attempt that errored (an error on the cell, `success=False`, or no finite score) is
  neither a pass nor a fail. An example whose errored attempts are at least half of its
  attempts gets `label: None` and is counted under `errored`, never reported as a clean pass.
  An example attempted fewer than twice gets nothing.
- The interval is a 95% Wilson score interval on the pass rate over the scored attempts. With
  few repeats it is wide even when every attempt passed: `all_pass` at 3/3 is about 0.44 to
  1.00, at 5/5 about 0.57 to 1.00, at 10/10 about 0.72 to 1.00. Say "passed all 3 attempts",
  never "always passes". The labels describe what was observed, not a guarantee.
- It covers only the winning configuration (or the one `config_index` you asked for), and
  only the examples that were rerun. It says nothing about the configurations that lost.

Where it is stored: in a dedicated field on the local result (`example_consistency_report`),
saved only to the local result store, and not in `metadata`, so the SDK's uploads, trackers
and exports never read it. It carries example ids, which can carry customer-chosen text.
It is not a privacy boundary against your own code: a completion callback receives the whole
result object. Do not paste it into a hosted service.

What to do with it: `mixed` examples are the unstable ones; look at the example and the
evaluator before blaming the model. `all_fail` examples are candidates for the regression set
(see `traigent-dataset-curate`).

---

## Move into: traigent-dataset-curate

Place after "Check the rows before you spend on them (local, free)" or as its own section
before "The improve loop".

### Keep the failures: a committed regression set

Requires SDK `<RELEASE>` or newer.

A regression set is the examples a run got wrong, kept in a file next to your code so a later
change cannot quietly break an example that used to work. The workflow is
add, confirm, fix, confirm.

1. Add the failing examples from a saved run.

   ```bash
   traigent regression add RUN_NAME --dataset eval.jsonl
   ```

   `RUN_NAME` is a saved result name (as in `traigent results show`). `--dataset` is the
   original JSONL or JSON the run evaluated. Options: `--dir` (default `tests/regression`),
   `--mode best_config|all_configs` (default `best_config`: failed in the winner's trials;
   `all_configs`: failed in every trial), `--threshold` (default `0.5`; a score equal to it
   passes), `--storage-dir/-d` (default `.traigent`), `--on-id-conflict refuse|replace|keep-both`
   (default `refuse`).

   The file is `tests/regression/regression.jsonl`, one JSON object per line: `input`,
   `output`, and `metadata` with `example_id`, `content_digest` and a `regression` block
   (status, provenance of which run, mode, threshold and configuration digest decided the
   failure). A new example becomes a row that starts out unconfirmed; one already stored gains a
   provenance entry instead of a duplicate row. Adding the same saved run again adds nothing.
   With no failing examples the command prints `No failing examples; regression set unchanged`.

   Ids can be positional (`example_<i>`), so the same id can name different content in
   different runs. `--on-id-conflict` says what to do when a stored id now names different
   content: `refuse` writes nothing, `replace` overwrites the stored row (its earlier
   provenance is kept, marked with the digest of the content it described), `keep-both` stores
   the new content under a distinct id. A stored row that was edited by hand so its content no
   longer matches its `content_digest` makes `add` refuse and write nothing.

2. Review the file before you commit it. It holds the example content exactly as it is in your
   dataset, unredacted, plus the examples' metadata, so a test can rerun the exact example.
   Nothing is uploaded. Do not commit it to a public repository unless the examples are
   public. `add` prints a note saying so.

   `add` also writes a sibling lock file, `.regression.jsonl.lock`, while it works, and adds that
   file name to `tests/regression/.gitignore` (and no other `.gitignore`). Commit
   `regression.jsonl` and that `.gitignore`; never commit the lock file.

3. Confirm: find out which rows really fail under the configuration you will ship.

   ```bash
   traigent regression confirm --module agent.py:answer --config config.json
   ```

   `--module PATH_OR_MODULE:FUNCTION` names the `@traigent.optimize` function to run;
   `--config` is a JSON file holding one flat object of parameter values (not the wrapper
   `export_config` writes). Options: `--repeats N` (default 5, at least 2), `--max-cost USD`
   (stops before more repeats start; finished repeats are still written; exit 4), `--only-id ID`
   (repeatable), `--dir`. Each row runs `--repeats` times and gets one status:

   | status | meaning |
   |---|---|
   | `unconfirmed` | not measured yet, or every attempt errored |
   | `known_failure` | never seen passing (every scored attempt failed) |
   | `intermittent` | both outcomes occurred |
   | `armed` | passed every repeat in one confirm run; from then on a failure is a regression |

   Rows are marked, never deleted. `armed` is sticky: a later failing confirm run does not
   un-arm a row. If you edit a row's content, its earlier observations stop counting for it.
   `confirm` writes the file in one atomic rewrite at the end. Review the diff before commit.

4. Fix the agent (prompt, model, parameters, or the example if the example is wrong), then
   run `confirm` again. A `known_failure` row that now passes every repeat becomes `armed`.
   Commit the updated file.

5. If an armed row should stop gating, disarm it with a closed reason. This runs nothing.

   ```bash
   traigent regression confirm --disarm ROW_ID --reason expected_behavior_change
   ```

   Reasons: `expected_behavior_change`, `example_is_wrong`, `known_flaky`, `other`. Only armed
   rows can be disarmed; the row returns to `known_failure`. An unknown or non-armed id writes
   nothing. Do not combine `--disarm` with `--module`, `--config` or `--only-id`.

`confirm` exit codes: 0 done; 1 other failure; 2 bad function, config or options; 3 the file is
missing, corrupt, or edited by hand (nothing written); 4 stopped early by `--max-cost`.
Output has counts and ids, never example content. Anything your code or the SDK prints while it
runs is suppressed and counted on stderr; `--show-output` prints it on stderr and it may
contain example content.

Keep the claim small: a regression set holds the examples you chose to keep. It shows that those
examples did not get worse under the repeats you ran, not that the agent is safe. Gate it in CI
with `traigent-ci-safety-gate`.

---

## Move into: traigent-ci-safety-gate

Place in `SKILL.md` under "The Two CI Checks" as a third check, and put the workflow step in
`references/gate-workflow.md` after the GitHub Actions workflow.

### Check: regression set (`traigent regression check`)

Requires SDK `<RELEASE>` or newer.

REGRESSION SET: re-run the armed rows of the committed regression set and fail the job when
one of them now fails.

```bash
traigent regression check --module agent.py:answer --config configs/baseline.json --json
```

Options: `--module` and `--config` (both required; `--config` is a flat JSON object of
parameter values, not the `export_config` wrapper, which this command does not unwrap),
`--dir` (default `tests/regression`), `--repeats N` (default 1, at least 1),
`--fail-on-intermittent`, `--json`, `--show-output`. There is no `--max-cost`: the command
makes about (armed rows x `--repeats`) calls of your function through your own model provider,
so keep the armed set and `--repeats` small, or mock the model in the PR job as the check above
does. Whether `TRAIGENT_RUN_COST_LIMIT` bounds this command is unverified.

What it gates. Only `armed` rows: rows that passed every repeat in a confirm run, so a failure now
is a change, not an old problem. Known failures, unconfirmed rows and (unless
`--fail-on-intermittent`) intermittent rows are listed as not gated. Gating a known failure
would turn the job red on day one and on every later run for a defect you already know about.
A row whose content changed since it was confirmed is also listed as not gated, with its own
`content_changed` entry in the output.

How a row is judged over its `--repeats` attempts: it passes only when more scored attempts
pass than fail; it regresses when more fail than pass; a tie (as many passes as fails) is
inconclusive, listed with reason `tie`. Errored attempts are not scored. With the default
`--repeats 1` a tie cannot happen; a row whose only attempt errored is inconclusive.

Exit codes:

| code | meaning | what the workflow does |
|---|---|---|
| 0 | every armed row passed, or none are armed | step passes |
| 1 | an armed row regressed | fail the job; this is a real finding |
| 2 | inconclusive: an armed row has no scored attempt or tied, the run stopped before every repeat finished, or the function or config could not be used | fail the job, but report it as "could not verify", not as a regression |
| 3 | regression file missing, corrupt, or edited by hand | fail the job; fix the file |

Exit 1 wins: when one row regressed and another is inconclusive, the code is 1. Never write
`|| true` after the step, and never map exit 2 to success: an inconclusive check verified
nothing. Exit 2 is reasonable to retry once, since a tie or an errored attempt can come from
a transient provider failure; if it persists, read the `--json` `inconclusive` list, then
`traigent-debugging`. Exit 3 is never retried.

`--json` prints one object on stdout, schema `traigent.regression_check/1`: `verdict`
(`pass`, `regression`, `inconclusive`, or `error`), `exit_code`, `repeats`, `armed`, `passed`,
`run_complete`, `regressions` and `inconclusive` (each row: `id`, `attempts`, `passes`,
`fails`, `errored`, `pass_rate_low`, `pass_rate_high`, plus `reason` where one applies), and
`not_gated` (ids per status plus `content_changed`). When the command cannot run,
`verdict` is `error`, with a closed `error` reason, and the message is on stderr. Output never
contains example content. `--show-output` prints what your code and the SDK wrote while
running, on stderr, and that may contain example content: leave it off in shared CI logs.

`check` writes nothing: not the regression file, its lock file, nor the directory, and it keeps
Python from writing `__pycache__` while it imports your module. CI never changes your
repository. Arming and disarming happen only through `traigent regression confirm`, locally,
and the result goes through a normal pull request.

Trust: the regression file is edited by people and is not authenticated evidence. A hand edit
that stays internally consistent can arm or disarm a row. Treat changes to
`tests/regression/regression.jsonl` like changes to the test suite: they need review.

Workflow step (add after the checkout and SDK install steps; the job needs your provider key
or a mocked model, as the other checks do):

```yaml
      - name: Regression set (armed rows only)
        run: |
          set +e
          traigent regression check --module agent.py:answer \
            --config configs/baseline.json --json > regression-check.json
          code=$?
          cat regression-check.json
          case "$code" in
            0) ;;
            1) echo "::error::regression: an armed row now fails"; exit 1 ;;
            2) echo "::error::regression check inconclusive (not a pass)"; exit 2 ;;
            *) echo "::error::regression check failed to run (exit $code)"; exit "$code" ;;
          esac
```

---

## Move into: traigent-debugging

Place as new `###` entries under "Common Errors", after "EvaluationError".

### Regression set: "refused: the evaluator sets example ids"

Requires SDK `<RELEASE>` or newer.

Seen with `traigent regression confirm` or `check` (both exit 2; with `check --json` the
`error` reason is `ids_not_assignable`):

```
The function's evaluator assigns its own example ids and ignores the ones this command sets
... Run the rows through a function that uses the built-in local evaluator. Nothing was written.
```

Cause: the command gives every row an id of its own for the run and ties results back to rows
only through those ids. An external-service evaluator reads ids from each input's `example_id`
or `input_id`; a custom evaluator or a content-identity grant sets its own. None of them hands
the command's ids back, so no result can be matched to a row, and the command refuses rather than
guess. Fix: point `--module` at a function that uses the built-in local evaluator over the
same task. Do not edit ids in the regression file to make it match.

A single row can also be left out: `results could not be tied to the row (id_missing |
id_duplicated | id_mismatch)`. In `check` that row is inconclusive; in `confirm` it records no
observation.

### Regression check: inconclusive results and ties (exit 2)

Requires SDK `<RELEASE>` or newer.

`traigent regression check` exits 2 when it could not verify, which is different from a
regression (exit 1). Read the line per row:

- `INCONCLUSIVE <id>: tie: attempts=N passes=P fails=F ...(as many passes as fails)`: a tie.
  The rule is strict: a row passes only if passes are greater than fails, and a tie is not a
  pass. A tie means the row is unstable under this configuration, not that it failed. Raise
  `--repeats` so a majority can emerge, then look at why the row is flaky. If the row should
  not gate, disarm it with a reason (`traigent regression confirm --disarm ID --reason
  known_flaky`) through a reviewed change.
- `INCONCLUSIVE <id>: ... (no scored attempt)`: every attempt errored. Fix the function
  error (provider key, rate limit, parsing) first; an errored attempt is neither a pass nor a fail.
- `The run stopped before every repeat finished.`: the run was cut short; the result is not
  complete and cannot pass.
- With `--json`, `verdict: "error"` and an `error` reason: `module_load_failed` (`--module`
  must look like `PATH_OR_MODULE:FUNCTION` and name an `@traigent.optimize` function; a module
  that exits at import counts as unusable), `config_invalid` (the config file is not one JSON
  object, or it is incomplete or outside the function's configuration space), `run_failed`,
  `file_invalid` (exit 3), `internal_error`. The message is on stderr.

Exit 3 from `check` or `confirm`: the regression file is missing, corrupt, or a row was edited so
its content no longer matches its `content_digest`. Nothing was written. Either undo the hand
edit, or keep it by setting the row's `content_digest` to
`traigent.utils.regression_set.content_digest(row["input"], row["output"])`.

### Regression commands print "N lines of output ... were suppressed"

Requires SDK `<RELEASE>` or newer.

`confirm` and `check` suppress everything your code and the SDK print while they run (stdout,
stderr, logs, warnings) and print one counts-only line on stderr. Rerun with `--show-output`
to see the text, on stderr, after the run. It can contain example content, so do not paste it
into a ticket or a shared CI log. Stdout is never used for it, so `--json` output stays one
parseable object.
