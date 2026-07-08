# Dataset Recipes

Use these recipes when shaping an evaluation dataset for a specific agent pattern. Keep all rows in JSONL, keep `metadata.split` explicit, and keep holdout examples isolated from tuning. Record the partition (tuning slice, optional exemplar/few-shot bank, holdout slice) before the first optimization run.

## RAG question answering

Example shape:

```json
{"input": {"question": "Which SLA applies to enterprise support?", "documents": [{"id": "policy-7", "text": "Enterprise support has a 4 hour response SLA."}]}, "expected_output": "Enterprise support has a 4 hour response SLA.", "metadata": {"task": "rag_qa", "split": "tune", "source_doc_ids": ["policy-7"]}}
```

Gold-label sourcing:

- Pull accepted answers from policy docs, support macros, reviewed customer responses, or SME-labeled traces.
- Store source document ids and answer spans in metadata when available.
- Include unanswerable questions with expected refusal behavior.

Leakage traps:

- Do not put the exact expected answer in retrieval context unless production retrieval would expose it.
- Split by source document or customer when near-duplicate questions exist.
- Keep generated paraphrases in the same split as their seed.

Holdout sizing:

- Start with 30-50 reviewed questions.
- Stratify by answerable, unanswerable, multi-hop, stale-document, and citation-required cases.

## Code generation

Example shape:

```json
{"input": {"task": "Add a Python function that normalizes email addresses.", "files": {"utils.py": ""}, "tests": "assert normalize_email(' A@EXAMPLE.COM ') == 'a@example.com'"}, "expected_output": {"test_status": "pass"}, "metadata": {"task": "code_gen", "split": "tune", "language": "python"}}
```

Gold-label sourcing:

- Prefer existing issue fixes, kata tests, accepted patches, and regression suites.
- Store exact test commands, changed-file expectations, and forbidden-file rules.
- Label success by deterministic tests where possible.

Leakage traps:

- Do not include the final patch in the prompt-side input.
- Split by repository, issue family, or fixture family so near-duplicate tests do not cross slices.
- Avoid judging generated code only by textual similarity to one patch when many correct solutions exist.

Holdout sizing:

- Start with 20-40 tasks if each task runs tests.
- Add more examples for broad language or framework coverage.

## Tool use

Example shape:

```json
{"input": {"user_request": "Find unpaid invoices for Acme and draft a reminder.", "available_tools": ["search_invoices", "draft_email"]}, "expected_output": {"required_tools": ["search_invoices", "draft_email"], "forbidden_tools": []}, "metadata": {"task": "tool_use", "split": "holdout", "risk": "billing"}}
```

Gold-label sourcing:

- Use reviewed traces, workflow specs, and task-owner approvals.
- Label required tools, forbidden tools, argument constraints, and stop conditions.
- Include negative examples where the correct action is no tool call.

Leakage traps:

- Do not include hidden tool results that production would not have yet.
- Split by customer/workspace for tenant-sensitive flows.
- Keep high-risk tool examples reviewed by the domain owner.

Holdout sizing:

- Start with 30+ examples across no-tool, single-tool, multi-tool, and forbidden-tool cases.
- Add extra holdout coverage for irreversible or external side-effect tools.

## Classification and extraction

Example shape:

```json
{"input": {"text": "Invoice INV-193 is overdue by 12 days."}, "expected_output": {"label": "billing_followup", "invoice_id": "INV-193", "days_overdue": 12}, "metadata": {"task": "classification_extraction", "split": "tune", "schema_version": "v1"}}
```

Gold-label sourcing:

- Use labeled production samples, annotation reviews, and schema-owner examples.
- Store schema version and annotator/reviewer status in metadata.
- Include ambiguous, out-of-scope, and empty-field cases.

Leakage traps:

- Do not let file names, folder names, or metadata reveal the label unless production input includes them.
- Split by entity/customer/time window when the same record appears in multiple forms.
- Keep schema migration examples grouped by schema version.

Holdout sizing:

- Use at least 30 examples per major class where feasible.
- For rare but important labels, keep a targeted holdout stratum and report it separately.
