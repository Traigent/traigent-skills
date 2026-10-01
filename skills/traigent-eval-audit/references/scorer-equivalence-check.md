# Scorer-Equivalence Check (frozen judge protocol p3b-v1)

Run this when the Traigent service recommends the operation `check_scorer_equivalence`.
It asks one question: **for examples the scorer marked wrong, are the failing answers actually
equivalent to the reference?** If many are, the scorer may be too strict on those examples.

The check runs **entirely on the customer's machine**, with the customer's own model key. The
service sends only ids and a protocol name, and receives only a closed list of enums back. No
question, reference or answer text ever leaves the machine toward Traigent.

> **Report ONLY the closed result below. NEVER include question, reference or answer text, judge
> rationale, prompts, or any free text in the report.** The service rejects any other field, any
> id it did not send, and any value outside the lists below. There is no field for text.

## Input (from the recommended instruction)

- the run id,
- a list of example ids (the examples to check),
- the protocol id: `p3b-v1`. If it is any other value, stop and report that this plugin version
  does not know that protocol; do not improvise a judge prompt.

## Before any model call

This step makes paid model calls with the user's key and sends the user's own text to the user's
model provider. Per the interaction policy, **ask for explicit approval first**, name the number
of judge calls (examples x distinct failing answers x 2 orders, plus retries), and stop if the
user declines. In one validation run the validated judge cost about USD 0.75 for 99 answer groups;
that figure is unverified for any other model or dataset.

## Procedure (all local)

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
   with the same prompt. If it still fails, that order counts as `not-equivalent`.
5. **Per answer:** it counts as equivalent **only if both orders say equivalent**. An answer
   with a missing order is not judged and is left out of the example's count.
6. **Per example:** `equivalent` if at least 50% of its failing answers are equivalent;
   `unsure` if below 50% but equivalent plus unsure answers reach 50%; `not_equivalent`
   otherwise when judged; `not_judged` when no answer was judged.
7. **Build the result** with the helper (keeps only the parsed word, discards reply text, and
   validates the closed schema). Record, per answer and order, the raw replies (first and optional
   retry) in a temporary local JSON file, then:

```bash
python3 <skill-dir>/scripts/equivalence_result.py result \
  --judgments judgments.json --sent-ids sent_ids.json \
  --model gemini-2.5-pro --thinking-budget 1024 --temperature 0
```

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
reported on, with the instruction's own id and status. Nothing else is attached.

## Scope and limits (carry these into what you tell the user)

- Validated on HotpotQA-style question answering only. Do not present it as validated elsewhere.
- Model raters, not humans. The judge misses about 8% of valid answers, so some too-strict
  scoring will go unflagged.
- **Advice only.** Never rescore a run, edit the dataset, or change the scorer because of this
  result. If the service reports the scorer may be too strict, the next step is the user's review
  (see "Task-Fit Calibration" in the skill), not an automatic fix.
