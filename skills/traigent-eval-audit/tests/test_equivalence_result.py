from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS_DIR / "equivalence_result.py"
sys.path.insert(0, str(SCRIPTS_DIR))
import equivalence_result as mod  # noqa: E402

EQ, NE, UN = "equivalent", "not-equivalent", "unsure"


def test_frozen_prompt_hashes():
    assert mod.prompt_hashes_ok()
    assert mod.SYSTEM_PROMPT_SHA256.startswith("a0f97d50") and mod.SYSTEM_PROMPT_SHA256.endswith("0d01")
    assert mod.USER_TEMPLATE_SHA256.startswith("90694fa8") and mod.USER_TEMPLATE_SHA256.endswith("3102")


def test_messages_collapse_to_one_line_and_swap_order():
    fwd = mod.build_messages("Who\nwas  he?", "Bob", "Robert", "candidate_first")
    rev = mod.build_messages("Who\nwas  he?", "Bob", "Robert", "reference_first")
    assert fwd[1]["content"] == "Question: Who was he?\nReference answer: Bob\nCandidate answer: Robert\n\nVerdict:"
    assert rev[1]["content"] == "Question: Who was he?\nReference answer: Robert\nCandidate answer: Bob\n\nVerdict:"
    assert fwd[0]["role"] == "system" and fwd[0]["content"] == mod.SYSTEM_PROMPT
    with pytest.raises(ValueError):
        mod.build_messages("q", "r", "c", "sideways")


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("equivalent", EQ),
        (' "Not-Equivalent". ', NE),
        ("unsure", UN),
        ("not equivalent", None),
        ("equivalent because they match", None),
        ("equivalent\nnot-equivalent", None),
        ("", None),
        (None, None),
        (7, None),
    ],
)
def test_strict_parse(reply, expected):
    assert mod.parse_verdict(reply) == expected


def test_resolve_side_retry_and_unresolved():
    assert mod.resolve_side(["garbage", "equivalent"]) == EQ
    assert mod.resolve_side(["equivalent", "not-equivalent"]) == EQ
    assert mod.resolve_side(["garbage", "more garbage"]) == UN
    assert mod.resolve_side(["garbage", "garbage", "equivalent"]) == UN  # only one retry
    assert mod.resolve_side(None) == UN


def test_answer_abstains_on_disagreement():
    assert mod.answer_outcome(EQ, EQ) == "equivalent"
    assert mod.answer_outcome(NE, NE) == "not_equivalent"
    assert mod.answer_outcome(EQ, NE) == "unsure"  # was not_equivalent before
    assert mod.answer_outcome(NE, EQ) == "unsure"
    assert mod.answer_outcome(EQ, UN) == "unsure"
    assert mod.answer_outcome(UN, NE) == "unsure"
    assert mod.answer_outcome(UN, UN) == "unsure"
    assert mod.answer_outcome(EQ, None) == "not_judged"
    assert mod.answer_outcome(None, EQ) == "not_judged"


def test_example_verdict_over_decided_answers():
    e, n, u = "equivalent", "not_equivalent", "unsure"
    assert mod.example_verdict([e, n]) == "equivalent"  # exactly 50% of decided
    assert mod.example_verdict([e, n, n]) == "not_equivalent"
    assert mod.example_verdict([n, n]) == "not_equivalent"
    assert mod.example_verdict([e, u, n, n]) == "not_equivalent"  # unsure leaves the denominator
    assert mod.example_verdict([e, u, u, u]) == "equivalent"
    assert mod.example_verdict([u, u]) == "unsure"
    assert mod.example_verdict([u, "not_judged"]) == "unsure"
    assert mod.example_verdict([]) == "not_judged"
    assert mod.example_verdict(["not_judged"]) == "not_judged"


def test_judge_tag():
    assert mod.judge_tag("gemini-2.5-pro", 1024, 0.0) == "gemini-2.5-pro"
    assert mod.judge_tag("gemini-2.5-pro", 1024, 0) == "gemini-2.5-pro"
    assert mod.judge_tag("gemini-2.5-pro", 2048, 0.0) == "other"
    assert mod.judge_tag("gemini-2.5-pro", 1024, 0.7) == "other"
    assert mod.judge_tag("gemini-2.5-flash", 1024, 0.0) == "other"
    assert mod.judge_tag("gemini-2.5-pro", None, None) == "other"
    assert mod.judge_tag("gemini-2.5-pro", True, 0.0) == "other"


def _judgments():
    return [
        {"example_id": "a", "answers": [{"forward": [EQ], "reverse": [EQ]}]},
        {"example_id": "b", "answers": [{"forward": [EQ], "reverse": ["junk", NE]}]},
        {"example_id": "d", "answers": [{"forward": [NE], "reverse": [NE]}]},
    ]


def test_build_result_shape_and_drops_text():
    j = _judgments()
    j[0]["answers"][0]["forward"] = ["equivalent"]
    result = mod.build_result(j, ["a", "b", "c", "d"], "gemini-2.5-pro")
    assert result == {
        "protocol": "p3b-v1",
        "judge": "gemini-2.5-pro",
        "orders": "both",
        "verdicts": [
            {"example_id": "a", "verdict": "equivalent"},
            {"example_id": "b", "verdict": "unsure"},
            {"example_id": "c", "verdict": "not_judged"},
            {"example_id": "d", "verdict": "not_equivalent"},
        ],
    }


def test_free_text_replies_never_reach_result():
    secret = "the capital is Paris because the reference says so"
    j = [{"example_id": 1, "answers": [{"forward": [secret, "equivalent"], "reverse": [EQ]}]}]
    result = mod.build_result(j, [1], "other")
    assert "Paris" not in json.dumps(result)
    assert result["verdicts"] == [{"example_id": 1, "verdict": "equivalent"}]


def test_missing_order_is_never_equivalent():
    j = [{"example_id": "a", "answers": [{"forward": [EQ], "reverse": None}]}]
    result = mod.build_result(j, ["a"], "other")
    assert result["verdicts"] == [{"example_id": "a", "verdict": "not_judged"}]
    assert result["orders"] == "both"  # "single" is reserved, never emitted
    j = [{"example_id": "a", "answers": [{"forward": [EQ]}]}]
    assert mod.build_result(j, ["a"], "other")["verdicts"][0]["verdict"] == "not_judged"


def test_half_judged_answers_leave_the_denominator():
    j = [{"example_id": "a", "answers": [
        {"forward": [EQ], "reverse": [EQ]},
        {"forward": [EQ], "reverse": None},
        {"forward": [NE], "reverse": None},
    ]}]
    assert mod.build_result(j, ["a"], "other")["verdicts"][0]["verdict"] == "equivalent"
    assert mod.build_result([], ["a"], "other")["orders"] == "both"


def test_unsent_or_duplicate_ids_rejected():
    with pytest.raises(ValueError):
        mod.validate_result(
            {"protocol": "p3b-v1", "judge": "other", "orders": "both",
             "verdicts": [{"example_id": "zzz", "verdict": "equivalent"}]},
            ["a"],
        )
    with pytest.raises(ValueError, match="duplicate"):
        mod.build_result(_judgments() + _judgments()[:1], ["a", "b"], "other")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(extra="x"),
        lambda r: r["verdicts"][0].update(rationale="because"),
        lambda r: r["verdicts"][0].update(verdict="not-equivalent"),
        lambda r: r.update(protocol="p3b-v2"),
        lambda r: r.update(judge="gpt-4"),
        lambda r: r.update(orders="three"),
        lambda r: r["verdicts"].append({"example_id": "a", "verdict": "unsure"}),
        lambda r: r.pop("orders"),
    ],
)
def test_closed_schema_rejects_widening(mutate):
    result = {"protocol": "p3b-v1", "judge": "other", "orders": "both",
              "verdicts": [{"example_id": "a", "verdict": "equivalent"}]}
    mutate(result)
    with pytest.raises(ValueError):
        mod.validate_result(result, ["a"])


def test_cli_result_and_selfcheck(tmp_path):
    (tmp_path / "j.json").write_text(json.dumps({"examples": _judgments()}))
    (tmp_path / "ids.json").write_text(json.dumps(["a", "b"]))
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "result", "--judgments", str(tmp_path / "j.json"),
         "--sent-ids", str(tmp_path / "ids.json"), "--model", "gemini-2.5-pro",
         "--thinking-budget", "1024", "--temperature", "0"],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(out.stdout)["judge"] == "gemini-2.5-pro"
    check = subprocess.run([sys.executable, str(SCRIPT), "self-check"], capture_output=True, text=True)
    assert check.returncode == 0
    msg = subprocess.run(
        [sys.executable, str(SCRIPT), "messages"], input=json.dumps(
            {"question": "q", "reference": "r", "candidate": "c", "order": "reference_first"}),
        capture_output=True, text=True, check=True,
    )
    assert "Reference answer: c" in json.loads(msg.stdout)[1]["content"]


def _selection(ids=("h1", "h2")):
    ids = list(ids)
    return {"protocol": "p3b-v1", "run_id": "run-1", "selection_rule": "sel-v1",
            "count": len(ids), "digest": mod.selection_digest(ids), "example_ids": ids}


def test_selection_digest_is_compact_json_sha256():
    import hashlib
    expected = "sha256:" + hashlib.sha256(b'["a","b"]').hexdigest()
    assert mod.selection_digest(["a", "b"]) == expected
    assert mod.selection_digest(["b", "a"]) != expected  # order matters


def test_verify_selection_accepts_and_preserves_order():
    sel = _selection(("z", "a", "m"))
    check = {k: sel[k] for k in ("protocol", "run_id", "selection_rule", "count", "digest")}
    assert mod.verify_selection(sel, check) == ["z", "a", "m"]
    assert mod.verify_selection(sel) == ["z", "a", "m"]
    assert mod.verify_selection(_selection(())) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(count=3),
        lambda s: s.update(count=True),
        lambda s: s.update(digest="sha256:" + "0" * 64),
        lambda s: s.update(digest=None),
        lambda s: s["example_ids"].reverse(),
        lambda s: s["example_ids"].append("h3"),
        lambda s: s.update(example_ids=["h1", 2]),
        lambda s: s.update(example_ids="h1"),
        lambda s: s.update(protocol="p3b-v2"),
        lambda s: s.update(selection_rule="sel-v2"),
    ],
)
def test_verify_selection_rejects_tampering(mutate):
    sel = _selection()
    mutate(sel)
    with pytest.raises(ValueError):
        mod.verify_selection(sel)


def test_verify_selection_must_match_check_block():
    sel = _selection()
    check = {k: sel[k] for k in ("protocol", "run_id", "selection_rule", "count", "digest")}
    for key, value in (("run_id", "other"), ("count", 5), ("digest", "sha256:" + "1" * 64)):
        with pytest.raises(ValueError, match=key):
            mod.verify_selection(sel, {**check, key: value})
    with pytest.raises(ValueError):
        mod.verify_selection([])


def test_cli_verify_selection(tmp_path):
    sel = _selection()
    (tmp_path / "s.json").write_text(json.dumps(sel))
    ok = subprocess.run([sys.executable, str(SCRIPT), "verify-selection", "--selection", str(tmp_path / "s.json")],
                        capture_output=True, text=True)
    assert ok.returncode == 0 and json.loads(ok.stdout)["example_ids"] == ["h1", "h2"]
    sel["count"] = 9
    (tmp_path / "s.json").write_text(json.dumps(sel))
    bad = subprocess.run([sys.executable, str(SCRIPT), "verify-selection", "--selection", str(tmp_path / "s.json")],
                         capture_output=True, text=True)
    assert bad.returncode == 1 and json.loads(bad.stdout)["ok"] is False
