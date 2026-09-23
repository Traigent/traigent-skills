"""Issue #325: the deterministic schema metrics must score JSON objects correctly.

``exact_normalized_metric`` compared the model's JSON text with ``str(expected)``
(Python's single-quoted repr), so a perfect reply to a dict gold scored 0.0.
``valid_schema_metric`` had no object check, so ``42``/``null`` raised
``TypeError`` (the SDK then fails every trial) and a JSON list of field names
passed. Both copies (eval-build template, eval-choose-metric SKILL.md) are
executed here with those replies, then the template runs end to end offline.
"""

from __future__ import annotations

from pathlib import Path

from .test_audit_326_comparator_case import _python_block, _run_driver

SKILLS = Path(__file__).resolve().parents[2] / "skills"
TEMPLATES = SKILLS / "traigent-eval-build" / "references" / "evaluator-templates.md"
CHOOSE_METRIC = SKILLS / "traigent-eval-choose-metric" / "SKILL.md"

NON_OBJECT_REPLIES = [
    "42",
    "null",
    '"text"',
    '["label"]',
    '["invoice_id", "amount_due", "due_date"]',
]


def test_template_metrics_score_json_objects(tmp_path: Path) -> None:
    body = f"""
    install_replies(lambda model, messages: "unused")
    write_rows("extraction.jsonl", [{{"input": {{"text": "t", "required_fields": ["label"]}}, "output": {{"label": "billing"}}}}])
    ns = load_block(sys.argv[1])
    exact, schema = ns["exact_normalized_metric"], ns["valid_schema_metric"]
    gold = {{"label": "billing", "days_overdue": 12}}
    fields = {{"required_fields": ["label", "days_overdue"]}}
    out = {{"exact": {{}}, "schema": {{}}, "errors": []}}
    for reply in ['{{"label": "billing", "days_overdue": 12}}', '{{ "days_overdue" : 12,  "label":"billing" }}']:
        out["exact"][reply] = exact(reply, gold, fields)
        out["schema"][reply] = schema(reply, gold, fields)
    out["exact_wrong"] = exact('{{"label": "refund", "days_overdue": 12}}', gold, fields)
    out["exact_text_gold"] = exact("  Billing  ", "billing", {{}})
    for reply in {NON_OBJECT_REPLIES!r}:
        try:
            out["schema"][reply] = schema(reply, gold, fields)
            out["exact"][reply] = exact(reply, gold, fields)
        except Exception as exc:
            out["errors"].append(f"{{reply}}: {{type(exc).__name__}}: {{exc}}")
    emit(out)
    """
    result = _run_driver(
        tmp_path, _python_block(TEMPLATES, "def exact_normalized_metric"), body
    )
    assert result["errors"] == [], result
    for reply in [
        '{"label": "billing", "days_overdue": 12}',
        '{ "days_overdue" : 12,  "label":"billing" }',
    ]:
        assert result["exact"][reply] == 1.0, (reply, result)
        assert result["schema"][reply] == 1.0, (reply, result)
    assert result["exact_wrong"] == 0.0
    assert result["exact_text_gold"] == 1.0
    for reply in NON_OBJECT_REPLIES:
        assert result["schema"][reply] == 0.0, (reply, result)
        assert result["exact"][reply] == 0.0, (reply, result)


def test_choose_metric_valid_schema_rejects_non_objects(tmp_path: Path) -> None:
    body = f"""
    write_rows("invoices.jsonl", [{{"input": {{"text": "t"}}, "output": "x"}}])
    ns = load_block(sys.argv[1])
    schema = ns["valid_schema_metric"]
    out = {{"scores": {{}}, "errors": []}}
    good = '{{"invoice_id": "INV-1", "amount_due": 3, "due_date": "2026-01-01"}}'
    for reply in [good] + {NON_OBJECT_REPLIES!r}:
        try:
            out["scores"][reply] = schema(reply, None, {{}})
        except Exception as exc:
            out["errors"].append(f"{{reply}}: {{type(exc).__name__}}: {{exc}}")
    emit(out)
    """
    result = _run_driver(
        tmp_path, _python_block(CHOOSE_METRIC, "def valid_schema_metric"), body
    )
    assert result["errors"] == [], result
    assert (
        result["scores"][
            '{"invoice_id": "INV-1", "amount_due": 3, "due_date": "2026-01-01"}'
        ]
        == 1.0
    )
    for reply in NON_OBJECT_REPLIES:
        assert result["scores"][reply] == 0.0, (reply, result)


def test_template_runs_every_trial_on_mixed_replies(tmp_path: Path) -> None:
    """A null/number reply from a small model must not abort the whole run."""
    body = """
    replies = iter(['{"label": "billing"}', "42", "null", '["label"]'] * 8)
    install_replies(lambda model, messages: next(replies))
    write_rows("extraction.jsonl", [{"input": {"text": f"Invoice {i}", "required_fields": ["label"]}, "output": {"label": "billing"}} for i in range(4)])
    ns = load_block(sys.argv[1])
    result = ns["extract"].optimize_sync(algorithm="grid", max_trials=2)
    emit({"trials": [{"status": str(t.status), "metrics": t.metrics} for t in result.trials], "best": result.best_config})
    """
    result = _run_driver(
        tmp_path, _python_block(TEMPLATES, "def exact_normalized_metric"), body
    )
    assert len(result["trials"]) == 2, result
    for trial in result["trials"]:
        assert trial["status"].endswith("completed"), result
        assert trial["metrics"]["valid_schema"] == 0.25, result
        assert trial["metrics"]["exact_normalized"] == 0.25, result
    assert result["best"] is not None, result
