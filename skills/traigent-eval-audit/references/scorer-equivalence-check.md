# Scorer-Equivalence Check (frozen judge protocol p3b-v1)

Run this when the Traigent service recommends the operation `check_scorer_equivalence`.
It asks one question: **for examples the scorer marked wrong, are the failing answers actually
equivalent to the reference?** If many are, the scorer may be too strict on those examples.

The check runs **entirely on the customer's machine**, with the customer's own model key. The
service sends only a protocol name and a selection digest (the ids are fetched separately), and receives only a closed list of enums back. No
question, reference or answer text ever leaves the machine toward Traigent.

> **Report ONLY the closed result below. NEVER include question, reference or answer text, judge
> rationale, prompts, or any free text in the report.** The service rejects any other field, any
> id it did not send, and any value outside the lists below. There is no field for text.

## Input (from the recommended instruction)

The instruction carries no example ids. It carries a `check` block:

```json
{"protocol": "p3b-v1", "run_id": "<run id>", "selection_rule": "sel-v1", "count": 12,
 "digest": "sha256:<hex>"}
```

If `protocol` is not `p3b-v1`, or `selection_rule` is not `sel-v1`, stop and report that this
plugin version does not know it; do not improvise a judge prompt or a selection.

## Step 1: fetch the example ids

With the service's normal authenticated access (the same one used to read the session state), call:

`GET /api/v1/director/sessions/{session_id}/instructions/{instruction_id}/check-examples`

where `instruction_id` is the id of the instruction that issued the check. No query parameters.
A 200 returns `protocol`, `run_id`, `selection_rule`, `count`, `digest` and `example_ids`
(strings, in selection order; use them exactly as returned). A 404 means the session, tenant or
instruction is unknown, it is not a check, or the feature is off: stop and report that.

## Step 2: verify the selection

Save the response and the instruction's `check` block as local JSON files and run:

```bash
python3 <skill-dir>/scripts/equivalence_result.py verify-selection \
  --selection selection.json --check check.json
```

It recomputes `sha256:` over `json.dumps(example_ids, separators=(",", ":"))`, and checks the id
list length against `count`, and the response against the `check` block. It prints
`{"ok": true, ...}` or `{"ok": false, "error": ...}` and exits non-zero. If it does not pass,
**stop and report; do not judge anything.**

## Before any model call

This step makes paid model calls with the user's key and sends the user's own text to the user's
model provider. Per the interaction policy, **ask for explicit approval first**, name the number
of judge calls (examples x distinct failing answers x 2 orders, plus retries), and stop if the
user declines. In one validation run the validated judge cost about USD 0.75 for 99 answer groups;
that figure is unverified for any other model or dataset.

## Procedure (all local), after Steps 1 and 2

1. **Collect.** For each example id sent, find that example's question and reference answer in
   the local dataset, and its **distinct** failing answers (the answers the scorer marked wrong,
   across the run's trials/configurations, de-duplicated after whitespace collapse) in the local
   run artifacts. If an id cannot be found locally, give it no answers; it will report
   `not_judged`.
2. **Build prompts.** Use the frozen prompt from `scripts/equivalence_result.py` (`messages`
   subcommand or `build_messages`): the system prompt and user template are fixed text with
   protocol id `p3b-v1`; each field is collapsed to one line. Do not reword, add examples,
   or add instructions. Run `python3 <skill-dir>/scripts/equivalence_result.py self-check`
   first; it must print `"prompt_hashes_ok": true`.
   - system prompt sha256 `a0f97d502515f3c80cf2c65c7724c86fb95dec04ac28492850b1cdb79d310d01`
   - user template sha256 `90694fa8faf741007f4100bb2319ede5c2ff22c1a14637031a327f8a56543102`
3. **Judge each answer in BOTH orders.** Order 1 (`candidate_first`) puts the reference in the
   reference slot and the failing answer in the candidate slot. Order 2 (`reference_first`) swaps
   the two. Validated judge settings: `gemini-2.5-pro`, thinking budget 1024, temperature 0.0.
   Any other model or settings is allowed but must be reported as judge `other`.
4. **Strict parse, one retry.** A reply must be exactly one word: `equivalent`,
   `not-equivalent`, or `unsure` (case, quotes and one final period tolerated; anything else,
   including prose or "not equivalent", is a parse failure). On a parse failure, ask once more
   with the same prompt. If it still fails, that order counts as `unsure`.
5. **Per answer (abstain on disagreement):** `equivalent` only if **both orders say equivalent**;
   `not_equivalent` only if both say not-equivalent; any disagreement, any `unsure`, or an
   unresolved parse in either order makes the answer `unsure`. An answer with a missing order is
   not judged. Unsure and not-judged answers are left out of the example's count.
6. **Per example**, over its decided answers (equivalent plus not_equivalent): `equivalent` if at
   least 50% are equivalent; `not_equivalent` if decided answers exist and fewer than 50% are
   equivalent; `unsure` if answers were judged in both orders but none was decided; `not_judged`
   if no answer was judged in both orders.
7. **Build the result** with the helper (keeps only the parsed word, discards reply text, and
   validates the closed schema). Record, per answer and order, the raw replies (first and optional
   retry) in a temporary local JSON file, then:

```bash
python3 <skill-dir>/scripts/equivalence_result.py result \
  --judgments judgments.json --sent-ids sent_ids.json \
  --model gemini-2.5-pro --thinking-budget 1024 --temperature 0
```

`sent_ids.json` is the verified `example_ids` list from Step 2.
`judgments.json` is `{"examples": [{"example_id": <id>, "answers": [{"forward": [<reply>, <retry?>],
"reverse": [<reply>, <retry?>]}]}]}`. Use `"reverse": null` (or `"forward": null`) if an order was not run;
such an answer is not judged and is left out, and an example with no answer judged in both orders
reports `not_judged`. Delete the temporary files afterwards.

## The closed result (the only thing reported)

```json
{
  "protocol": "p3b-v1",
  "judge": "gemini-2.5-pro",
  "orders": "both",
  "verdicts": [{"example_id": "<an id that was sent>", "verdict": "equivalent"}]
}
```

- `protocol`: `p3b-v1`.
- `judge`: `gemini-2.5-pro` only for the validated settings above, otherwise `other`.
- `orders`: always `both`: only answers judged in both orders count. `single` is reserved in the
  enum and is never emitted by this procedure.
- `verdicts[].verdict`: one of `equivalent`, `not_equivalent`, `unsure`, `not_judged`.
- One entry per id that was sent, at most; never an id that was not sent.

Send it through the existing report-progress path, as the `result` of the instruction being
reported on, with the instruction's own id and status. Nothing else is attached. Use each
`example_id` exactly as returned in Step 1. If the report is answered with 409
`check_selection_changed`, the selection moved: re-run Steps 1 and 2 to get the new ids, then redo
the check and report again.

## Scope and limits (carry these into what you tell the user)

- Validated on HotpotQA-style question answering only. Do not present it as validated elsewhere.
- Model raters, not humans. The judge misses about 8% of valid answers, so some too-strict
  scoring will go unflagged.
- **Advice only.** Never rescore a run, edit the dataset, or change the scorer because of this
  result. If the service reports the scorer may be too strict, the next step is the user's review
  (see "Task-Fit Calibration" in the skill), not an automatic fix.
