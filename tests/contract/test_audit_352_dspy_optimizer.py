"""DSPyPromptOptimizer teaching must match the installed adapter (traigent-skills#352).

The reference used to document a keyword pass-through the constructor does not
have (any extra argument raises ``TypeError``) and omitted the real knobs. The
parameter tables in ``references/dspy.md`` must equal ``inspect.signature`` of the
installed adapter, and no example may pass an argument the signature rejects.
On ``traigent<=0.27.0`` ``method="mipro"`` crashes inside ``optimize_prompt``,
so every runnable example uses ``method="bootstrap"``; the last test runs them
with DSPy's ``DummyLM`` (no keys, no network) when DSPy is installed.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest
from traigent.integrations.dspy_adapter import DSPyPromptOptimizer

SKILL = "skills/traigent-setup-integrations"
PAGES = (f"{SKILL}/SKILL.md", f"{SKILL}/references/dspy.md")
PYTHON_BLOCK_RE = re.compile(r"^```python\n(.*?)^```", re.S | re.M)
REQUIRED = "(required)"


def _documented_table(text: str, heading: str) -> dict[str, str]:
    section = re.search(rf"^### {re.escape(heading)}\n(.*?)(?=^#)", text, re.S | re.M)
    assert section, f"dspy.md lost its '### {heading}' section"
    table = re.search(r"^\| Parameter \|.*?\n((?:\|.*\n)+)", section.group(1), re.M)
    assert table, f"no '| Parameter |' table under '### {heading}'"
    rows = re.findall(
        r"^\| `(\w+)` \|[^\n]*?\| ([^|\n]+?) \|[^|\n]*\|$", table.group(1), re.M
    )
    return dict(rows)


def _signature_table(func) -> dict[str, str]:
    table = {}
    for name, param in inspect.signature(func).parameters.items():
        if name == "self":
            continue
        table[name] = (
            REQUIRED if param.default is inspect.Parameter.empty else param.default
        )
    return table


def _parse_default(cell: str):
    cell = cell.strip()
    if cell == REQUIRED:
        return REQUIRED
    return ast.literal_eval(cell.strip("`"))


def _compare(text: str, heading: str, func) -> list[str]:
    documented = {
        k: _parse_default(v) for k, v in _documented_table(text, heading).items()
    }
    actual = _signature_table(func)
    if documented == actual:
        return []
    return [f"### {heading}: documents {documented}, installed SDK has {actual}"]


def _call_kwarg_violations(rel: str, text: str) -> list[str]:
    accepted = {
        "DSPyPromptOptimizer": set(_signature_table(DSPyPromptOptimizer)),
        "optimize_prompt": set(_signature_table(DSPyPromptOptimizer.optimize_prompt)),
    }
    violations = []
    for match in PYTHON_BLOCK_RE.finditer(text):
        try:
            tree = ast.parse(match.group(1))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            )
            if name not in accepted:
                continue
            for kw in node.keywords:
                if kw.arg is None or kw.arg not in accepted[name]:
                    line = text.count("\n", 0, match.start(1)) + node.lineno
                    violations.append(
                        f"{rel}:{line}: {name}(...) passes `{kw.arg or '**'}`, "
                        f"which the installed signature rejects"
                    )
    return violations


def test_dspy_parameter_tables_match_installed_signatures(repo_root: Path) -> None:
    text = (repo_root / PAGES[1]).read_text(encoding="utf-8")
    mismatches = _compare(text, "Constructor", DSPyPromptOptimizer)
    mismatches += _compare(
        text, "optimize_prompt()", DSPyPromptOptimizer.optimize_prompt
    )
    assert not mismatches, "\n".join(mismatches)


def test_dspy_examples_pass_only_accepted_arguments(repo_root: Path) -> None:
    violations: list[str] = []
    for rel in PAGES:
        text = (repo_root / rel).read_text(encoding="utf-8")
        violations.extend(_call_kwarg_violations(rel, text))
    assert not violations, "\n".join(violations)


def test_dspy_lints_have_teeth() -> None:
    table = (
        "### Constructor\n\n| Parameter | Type | Default | Description |\n|---|---|---|---|\n"
        '| `method` | `"mipro" \\| "bootstrap"` | `"mipro"` | x |\n'
        "| `teacher_model` | `str` | `None` | x |\n\n## Next\n"
    )
    assert _compare(table, "Constructor", DSPyPromptOptimizer), "missed auto_setting"
    bad = '```python\nDSPyPromptOptimizer(method="mipro", max_bootstrapped_demos=2)\n```\n'
    assert _call_kwarg_violations("bad.md", bad)
    good = bad.replace("DSPyPromptOptimizer(", "o.optimize_prompt(m, t, f, ")
    assert not _call_kwarg_violations("good.md", good.replace('method="mipro", ', ""))


def test_dspy_optimizer_examples_run_with_dummy_lm(repo_root: Path) -> None:
    dspy = pytest.importorskip("dspy")
    from dspy.utils import DummyLM

    def fake_lm(*_args, **_kwargs):
        return DummyLM([{"answer": "4"}] * 400)

    class QAModule(dspy.Module):
        def __init__(self):
            super().__init__()
            self.predict = dspy.Predict("question -> answer")

        def forward(self, question):
            return self.predict(question=question)

    def exact_match(example, prediction, trace=None):
        return example.answer.strip().lower() == prediction.answer.strip().lower()

    trainset = [
        dspy.Example(question=f"What is {i}+{4 - i}?", answer="4").with_inputs(
            "question"
        )
        for i in range(5)
    ]
    ran = 0
    dspy.configure(lm=fake_lm())
    for rel in PAGES:
        text = (repo_root / rel).read_text(encoding="utf-8")
        ns = {
            "DSPyPromptOptimizer": DSPyPromptOptimizer,  # the page's Import block
            "QAModule": QAModule,
            "trainset": trainset,
            "exact_match": exact_match,
            "my_dspy_module": QAModule(),
            "train_examples": trainset,
            "accuracy_metric": exact_match,
            "accuracy_fn": exact_match,
            "best_model": "model-under-test",
            "best_temp": 0.0,
        }
        for match in PYTHON_BLOCK_RE.finditer(text):
            block = match.group(1)
            if "@traigent.optimize" in block or not (
                "DSPyPromptOptimizer(" in block or "optimize_prompt(" in block
            ):
                continue
            if "# Stage 2" in block:  # stage 1 is a Traigent run, not a DSPy example
                block = block.split("# Stage 2", 1)[1].split("\n", 1)[1]
            block = block.replace("dspy.LM(", "fake_lm(")
            ns["fake_lm"] = fake_lm
            exec(compile(block, f"{rel}:{match.start(1)}", "exec"), ns)
            ran += 1
    assert ran >= 4, f"expected the documented optimizer examples, ran {ran}"
