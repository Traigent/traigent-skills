#!/usr/bin/env python3
"""Local helper for the scorer-equivalence check (frozen judge protocol p3b-v1).

Pure and offline: it builds the frozen judge prompt, parses judge replies
strictly, and assembles the closed result object that is reported back.
It never calls a model and never reads the network. Customer text enters only
through the prompt builder and is never written to the result.

Subcommands (see SKILL.md / references/scorer-equivalence-check.md):
  messages     read {"question","reference","candidate","order"} on stdin, print judge messages
  result       build the closed result from recorded one-word judge replies
  self-check   verify the frozen prompt hashes
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Any, Mapping, Sequence

# The operation name the service recommends. Kept in one place on purpose.
OPERATION = "check_scorer_equivalence"

PROTOCOL = "p3b-v1"
VALIDATED_JUDGE = "gemini-2.5-pro"
VALIDATED_THINKING_BUDGET = 1024
VALIDATED_TEMPERATURE = 0.0

SYSTEM_PROMPT = (
    "You compare a candidate answer with a reference answer for a question. Decide whether the "
    "candidate gives the same answer as the reference: the same entity, number, date or fact, "
    "allowing for different spellings, aliases, abbreviations, units or formatting, and for extra "
    "or missing wording that does not change what is being claimed. Reply with exactly one word: "
    "equivalent, not-equivalent, or unsure. Use not-equivalent when the candidate names a "
    "different entity or value, is more or less specific in a way that changes the answer, or "
    "contradicts the reference. Use unsure only when you cannot decide from the question, the "
    "reference and the candidate alone."
)
USER_TEMPLATE = (
    "Question: {question}\nReference answer: {reference}\nCandidate answer: {candidate}\n\nVerdict:"
)

SYSTEM_PROMPT_SHA256 = "a0f97d502515f3c80cf2c65c7724c86fb95dec04ac28492850b1cdb79d310d01"
USER_TEMPLATE_SHA256 = "90694fa8faf741007f4100bb2319ede5c2ff22c1a14637031a327f8a56543102"

# Judge reply words, and the closed result words they map to.
JUDGE_WORDS = ("equivalent", "not-equivalent", "unsure")
RESULT_VERDICTS = ("equivalent", "not_equivalent", "unsure", "not_judged")
ORDERS = ("candidate_first", "reference_first")
RESULT_KEYS = ("protocol", "judge", "orders", "verdicts")
VERDICT_KEYS = ("example_id", "verdict")

_CLEAN = re.compile(r"\A\s*[\"']?\s*([A-Za-z-]+)\s*[\"']?\.?\s*\Z")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def prompt_hashes_ok() -> bool:
    return (
        _sha256(SYSTEM_PROMPT) == SYSTEM_PROMPT_SHA256
        and _sha256(USER_TEMPLATE) == USER_TEMPLATE_SHA256
    )


def _one_line(text: Any) -> str:
    return " ".join(str(text).split())


def build_messages(
    question: str, reference: str, candidate: str, order: str = "candidate_first"
) -> list[dict[str, str]]:
    """The complete judge request. Every field is collapsed to one line.

    `reference_first` swaps which text sits in the reference and candidate slots,
    so the judge sees the pair in the opposite order.
    """
    if order not in ORDERS:
        raise ValueError(f"order must be one of {ORDERS}")
    first, second = (reference, candidate) if order == "candidate_first" else (candidate, reference)
    user = USER_TEMPLATE.format(
        question=_one_line(question), reference=_one_line(first), candidate=_one_line(second)
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def parse_verdict(reply: str | None) -> str | None:
    """Strict: exactly one judge word, optional quotes, one final period, whitespace.

    Prose, 'not equivalent' with a space, or anything extra returns None.
    """
    if not isinstance(reply, str):
        return None
    match = _CLEAN.match(reply)
    if not match:
        return None
    word = match.group(1).lower()
    return word if word in JUDGE_WORDS else None


def resolve_side(replies: Sequence[str | None] | None) -> str:
    """One order's replies (first attempt, optional single retry) -> a judge word.

    The first parseable reply wins; at most one retry is honored. Unresolved
    (nothing parseable) is `not-equivalent`.
    """
    for reply in list(replies or [])[:2]:
        word = parse_verdict(reply)
        if word is not None:
            return word
    return "not-equivalent"


def answer_outcome(forward: str, reverse: str | None) -> str:
    """Per-answer outcome. Equivalent only if every order that ran says equivalent."""
    words = [forward] + ([reverse] if reverse is not None else [])
    if all(w == "equivalent" for w in words):
        return "equivalent"
    if "not-equivalent" not in words and "unsure" in words:
        return "unsure"
    return "not_equivalent"


def example_verdict(outcomes: Sequence[str]) -> str:
    """Example verdict from its distinct failing answers' outcomes.

    equivalent      >= 50% of answers equivalent
    not_equivalent  judged, below 50%, and unsure answers could not reach 50%
    unsure          below 50% equivalent, but equivalent + unsure answers reach 50%
    not_judged      no answers were judged
    """
    judged = [o for o in outcomes if o != "not_judged"]
    if not judged:
        return "not_judged"
    n = len(judged)
    equivalent = sum(o == "equivalent" for o in judged)
    unsure = sum(o == "unsure" for o in judged)
    if 2 * equivalent >= n:
        return "equivalent"
    if 2 * (equivalent + unsure) >= n:
        return "unsure"
    return "not_equivalent"


def judge_tag(model: str | None, thinking_budget: int | None, temperature: float | None) -> str:
    """`gemini-2.5-pro` only for the validated configuration; anything else is `other`."""
    ok = (
        model == VALIDATED_JUDGE
        and isinstance(thinking_budget, int)
        and not isinstance(thinking_budget, bool)
        and thinking_budget == VALIDATED_THINKING_BUDGET
        and isinstance(temperature, (int, float))
        and not isinstance(temperature, bool)
        and float(temperature) == VALIDATED_TEMPERATURE
    )
    return VALIDATED_JUDGE if ok else "other"


def validate_result(result: Any, sent_ids: Sequence[Any]) -> None:
    """Raise ValueError unless `result` is exactly the closed schema for these ids."""
    if not isinstance(result, dict) or set(result) != set(RESULT_KEYS):
        raise ValueError(f"result must have exactly the keys {RESULT_KEYS}")
    if result["protocol"] != PROTOCOL:
        raise ValueError("protocol must be the frozen protocol id")
    if result["judge"] not in (VALIDATED_JUDGE, "other"):
        raise ValueError("judge must be 'gemini-2.5-pro' or 'other'")
    if result["orders"] not in ("both", "single"):
        raise ValueError("orders must be 'both' or 'single'")
    verdicts = result["verdicts"]
    if not isinstance(verdicts, list):
        raise ValueError("verdicts must be a list")
    allowed = {json.dumps(i, sort_keys=True) for i in sent_ids}
    seen: set[str] = set()
    for entry in verdicts:
        if not isinstance(entry, dict) or set(entry) != set(VERDICT_KEYS):
            raise ValueError(f"each verdict must have exactly the keys {VERDICT_KEYS}")
        if entry["verdict"] not in RESULT_VERDICTS:
            raise ValueError(f"verdict must be one of {RESULT_VERDICTS}")
        key = json.dumps(entry["example_id"], sort_keys=True)
        if key not in allowed:
            raise ValueError("example_id was not among the ids the instruction sent")
        if key in seen:
            raise ValueError("duplicate example_id")
        seen.add(key)


def build_result(
    judgments: Sequence[Mapping[str, Any]],
    sent_ids: Sequence[Any],
    judge: str,
) -> dict[str, Any]:
    """Assemble the closed result.

    `judgments`: one item per example, {"example_id": id, "answers": [
    {"forward": [reply, retry?], "reverse": [reply, retry?] | null}, ...]}.
    Only the strictly parsed judge word survives; reply text is discarded.
    `reverse` null (or missing) means that order was not run (orders: single).
    Examples sent but absent from `judgments` are reported `not_judged`.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    for item in judgments:
        key = json.dumps(item["example_id"], sort_keys=True)
        if key in by_id:
            raise ValueError("duplicate example_id in judgments")
        by_id[key] = item

    all_both = True
    any_judged = False
    verdicts: list[dict[str, Any]] = []
    for example_id in sent_ids:
        item = by_id.get(json.dumps(example_id, sort_keys=True))
        outcomes: list[str] = []
        for answer in (item or {}).get("answers", []):
            forward = resolve_side(answer.get("forward"))
            reverse_replies = answer.get("reverse")
            reverse = resolve_side(reverse_replies) if reverse_replies is not None else None
            if reverse is None:
                all_both = False
            outcomes.append(answer_outcome(forward, reverse))
            any_judged = True
        verdicts.append({"example_id": example_id, "verdict": example_verdict(outcomes)})

    result = {
        "protocol": PROTOCOL,
        "judge": judge,
        "orders": "both" if (all_both and any_judged) else "single",
        "verdicts": verdicts,
    }
    validate_result(result, sent_ids)
    return result


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-check")
    sub.add_parser("messages")
    res = sub.add_parser("result")
    res.add_argument("--judgments", required=True, help="JSON file of recorded one-word replies")
    res.add_argument("--sent-ids", required=True, help="JSON list of the example ids sent")
    res.add_argument("--model", required=True)
    res.add_argument("--thinking-budget", type=int)
    res.add_argument("--temperature", type=float)
    args = parser.parse_args(argv)

    if args.command == "self-check":
        print(json.dumps({"prompt_hashes_ok": prompt_hashes_ok()}))
        return 0 if prompt_hashes_ok() else 1
    if args.command == "messages":
        spec = json.load(sys.stdin)
        messages = build_messages(
            spec["question"], spec["reference"], spec["candidate"], spec.get("order", "candidate_first")
        )
        json.dump(messages, sys.stdout)
        return 0
    judgments = _load_json(args.judgments)
    if isinstance(judgments, dict):
        judgments = judgments.get("examples", [])
    result = build_result(
        judgments,
        _load_json(args.sent_ids),
        judge_tag(args.model, args.thinking_budget, args.temperature),
    )
    json.dump(result, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
