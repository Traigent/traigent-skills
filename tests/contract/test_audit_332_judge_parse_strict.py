"""Issue #332: the fail-closed judge parser must reject malformed scores.

``parse_judge_output`` in ``traigent-eval-audit`` (the reference for its
protected FAIL-CLOSED rule) accepted NaN, Infinity, wrong-scale scores such as
``7`` and booleans as successful parses, and those scores then cleared every
threshold in the calibration sweep. The eval-build judge and hybrid templates
range-checked but still read ``true`` as 1.0. All three parsers are executed
here against those payloads.
"""

from __future__ import annotations

from pathlib import Path

from .test_audit_326_comparator_case import _python_block, _run_driver

SKILLS = Path(__file__).resolve().parents[2] / "skills"
EVAL_AUDIT = SKILLS / "traigent-eval-audit" / "SKILL.md"
TEMPLATES = SKILLS / "traigent-eval-build" / "references" / "evaluator-templates.md"

MALFORMED = [
    '{"score": NaN, "decision": "pass", "reason": "x"}',
    '{"score": Infinity, "decision": "pass", "reason": "x"}',
    '{"score": -3, "decision": "fail", "reason": "x"}',
    '{"score": 7, "decision": "fail", "reason": "7/10"}',
    '{"score": true, "decision": "pass", "reason": "x"}',
    '[{"score": 0.9, "decision": "pass", "reason": "x"}]',
    '"just text"',
    "null",
]
VALID = '{"score": 0.9, "decision": "pass", "reason": "grounded"}'


def test_eval_audit_parser_fails_closed_on_malformed_scores(tmp_path: Path) -> None:
    body = f"""
    ns = load_block(sys.argv[1])
    parse = ns["parse_judge_output"]
    emit({{raw: [parse(raw)["parse_failed"], parse(raw)["score"], parse(raw)["decision"]]
          for raw in {MALFORMED + [VALID]!r}}})
    """
    result = _run_driver(
        tmp_path, _python_block(EVAL_AUDIT, "def parse_judge_output"), body
    )
    for raw in MALFORMED:
        assert result[raw] == [True, 0.0, "abstain"], (raw, result[raw])
    assert result[VALID] == [False, 0.9, "pass"], result[VALID]


def test_eval_build_judge_parsers_reject_boolean_scores(tmp_path: Path) -> None:
    judge_body = """
    write_rows("qa.jsonl", [{"input": {"question": "q"}, "output": "a"}])
    ns = load_block(sys.argv[1])
    parse = ns["parse_judge_response"]
    emit({raw: list(parse(raw)) for raw in [
        '{"score": true, "reason": "x"}', '{"score": NaN, "reason": "x"}',
        '{"score": 7, "reason": "x"}', '{"score": 0.9, "reason": "ok"}']})
    """
    (tmp_path / "judge").mkdir()
    (tmp_path / "hybrid").mkdir()
    judge = _run_driver(
        tmp_path / "judge",
        _python_block(TEMPLATES, "def llm_judge_evaluator"),
        judge_body,
    )
    assert judge['{"score": true, "reason": "x"}'] == [
        0.0,
        "judge_parse_failure",
        False,
    ]
    assert judge['{"score": NaN, "reason": "x"}'][2] is False
    assert judge['{"score": 7, "reason": "x"}'][2] is False
    assert judge['{"score": 0.9, "reason": "ok"}'] == [0.9, "ok", True]

    hybrid_body = """
    install_replies(lambda model, messages: '{"score": true, "reason": "x"}')
    write_rows("extraction.jsonl", [{"input": {"text": "t"}, "output": {"label": "a"}}])
    ns = load_block(sys.argv[1])
    emit(list(ns["judge_json_quality"]({"label": "a"}, {"label": "a"}, {"text": "t"})))
    """
    hybrid = _run_driver(
        tmp_path / "hybrid",
        _python_block(TEMPLATES, "def hybrid_evaluator"),
        hybrid_body,
    )
    assert hybrid == [0.0, "judge_parse_failure", False], hybrid
