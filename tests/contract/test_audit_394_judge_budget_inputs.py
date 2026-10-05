"""Issue #394: the judge spend cap must reject inputs that disable it.

Both budget checks in the judge and hybrid templates have the form
``cap < needed -> refuse``. A ``NaN`` cap makes every such comparison false, so
the up-front coverage check passed and ``try_spend()`` never refused: judge spend
was uncapped with no error. An infinite cap, a zero or ``NaN`` per-call price, and
non-integer row or trial counts open the same hole.

The templates are executed here offline (agent and judge replies come from
litellm's own ``mock_response``) and must: reject a non-finite or non-positive
cap or price in ``JudgeBudget`` itself; reject bad caps, prices, row counts and
trial counts in ``run_with_judge_budget`` before ``optimize_sync`` is called; make
no judge call on a real run started with a ``NaN`` or infinite cap; and leave no
spendable budget behind once a run ends, however it ends.

Review round 1: accepted inputs still mis-bound through float accumulation with an
absolute tolerance (a $50 cap at $0.002 granted 24,999 calls; a cap one dollar
under a huge price granted a call; a tiny cap and price granted 100x), and two
overlapping runs spent from, and cleared, each other's budget. The allowance is
now ``floor(cap / price)`` whole calls computed exactly once, the coverage check
compares integers, and a second budgeted run in the same process is refused.

Review round 2: ``Fraction(str(x))`` read the string, not the value. A float
subclass with a lying ``__str__`` sized the allowance from the lie, a huge float
cap mixed with an exact int price granted a call costing more than the cap, an
int subclass whose ``*`` returns NaN passed the coverage check, and ``spent``
could exceed the cap by rounding or overflow on a valid counter. Amounts are now
exact built-in ``int`` or ``float`` up to $1e15, counts exact built-in ``int``,
money is the decimal of the float's shortest repr, and ``spent`` is computed exactly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from .test_audit_326_comparator_case import _python_block
from .test_audit_327_judge_objectives_budget import (
    HYBRID_MARKER,
    JUDGE_MARKER,
    TEMPLATE_CASES,
    TEMPLATES,
    _run_template,
)

# Labels are Python expressions, evaluated inside the driver.
BAD_AMOUNTS = {
    "cap_usd": [
        'float("nan")',
        'float("inf")',
        'float("-inf")',
        "0",
        "-1",
        "True",
        "False",
        '"1.0"',
        "None",
        "10**400",
    ],
    "per_call_usd": [
        'float("nan")',
        'float("inf")',
        'float("-inf")',
        "0",
        "-0.002",
        "True",
        "False",
        "None",
    ],
}
BAD_COUNTS = [
    'float("nan")',
    'float("inf")',
    "0",
    "-1",
    "True",
    "False",
    "0.5",
    "50.0",
    '"50"',
    "None",
]

MATRIX_BODY = """
BAD_AMOUNTS = {bad_amounts}
BAD_COUNTS = {bad_counts}

def outcome(call):
    try:
        call()
        return None
    except Exception as exc:
        return f"{{type(exc).__name__}}: {{exc}}"

# JudgeBudget on its own: every bad cap or price must be refused at construction.
constructor = {{
    name: {{label: outcome(lambda: ns["JudgeBudget"](**{{"cap_usd": 1.0, "per_call_usd": 0.002, name: eval(label)}}))
            for label in labels}}
    for name, labels in BAD_AMOUNTS.items()
}}
control = ns["JudgeBudget"](cap_usd=1.0, per_call_usd=0.002)
granted = sum(control.try_spend() for _ in range(600))

class FakeOptimized:
    # Records each dispatch and the budget installed for it; never calls a model.
    def __init__(self, action=None):
        self.calls, self.action = [], action
    def optimize_sync(self, **kwargs):
        budget = ns["JUDGE_BUDGET"]
        self.calls.append({{"max_trials": kwargs.get("max_trials"),
                           "budget_cap": None if budget is None else budget.cap}})
        if self.action:
            self.action(budget)
        return "optimized"

PRICE = ns["JUDGE_COST_PER_CALL_USD"]

def attempt(rows=50, max_trials=8, cap_usd=1.0, price=PRICE, action=None):
    ns["JUDGE_BUDGET"] = None
    ns["JUDGE_COST_PER_CALL_USD"] = price
    fake = FakeOptimized(action)
    try:
        returned = ns["run_with_judge_budget"](fake, rows=rows, max_trials=max_trials, cap_usd=cap_usd)
        raised = None
    except Exception as exc:
        returned, raised = None, f"{{type(exc).__name__}}: {{exc}}"
    finally:
        ns["JUDGE_COST_PER_CALL_USD"] = PRICE
    return {{"raised": raised, "returned": returned, "calls": fake.calls,
            "budget_cleared": ns["JUDGE_BUDGET"] is None}}

wrapper = {{
    "cap_usd": {{label: attempt(cap_usd=eval(label)) for label in BAD_AMOUNTS["cap_usd"]}},
    "per_call_usd": {{label: attempt(price=eval(label)) for label in BAD_AMOUNTS["per_call_usd"]}},
    "rows": {{label: attempt(rows=eval(label)) for label in BAD_COUNTS}},
    "max_trials": {{label: attempt(max_trials=eval(label)) for label in BAD_COUNTS}},
    "derived_total": {{
        "rows*max_trials too large for a float": attempt(rows=10**300, max_trials=10**300),
        "rows too large for a float": attempt(rows=10**400, max_trials=1),
        "rows*max_trials*price too large for a float, price at the ceiling": attempt(
            rows=10**300, max_trials=10**300, price=1e15, cap_usd=1e15),
        "rows*max_trials*price too large for a float, int price": attempt(
            rows=10**300, max_trials=10**300, price=1, cap_usd=1),
    }},
}}
wrapper_control = attempt(rows=50, max_trials=8, cap_usd=1.0)

def boom(budget):
    raise KeyError("optimizer failed")

def overspend(budget):
    for _ in range(3):
        budget.try_spend()

lifecycle = {{
    "success": attempt(rows=1, max_trials=1, cap_usd=PRICE),
    "optimizer_raises": attempt(rows=1, max_trials=1, cap_usd=PRICE, action=boom),
    "judge_call_refused": attempt(rows=1, max_trials=1, cap_usd=PRICE, action=overspend),
}}

def probe(call):
    # A missing attribute on an older template is an outcome, not a driver crash.
    try:
        return {{"value": call(), "raised": None}}
    except Exception as exc:
        return {{"value": None, "raised": f"{{type(exc).__name__}}: {{exc}}"}}

def grants(cap, price, tries):
    budget = ns["JudgeBudget"](cap_usd=cap, per_call_usd=price)
    return [sum(budget.try_spend() for _ in range(tries)), budget.refused]

def spend(times):
    def action(budget):
        for _ in range(times):
            budget.try_spend()
    return action

# Exact allowance: a realistic cap grants every call it pays for, then refuses.
exact = {{
    "cap 50 at 0.002": grants(50, 0.002, 25_001),
    "cap 200 at 0.002": grants(200, 0.002, 100_001),
    "500 rows x 50 trials at cap 50.0": attempt(
        rows=500, max_trials=50, cap_usd=50.0, price=0.002, action=spend(25_000)),
}}

def huge_amounts():
    budget = ns["JudgeBudget"](cap_usd=10**15 - 1, per_call_usd=10**15)
    return [budget.max_calls, budget.try_spend(), budget.refused]

def tiny_price():
    budget = ns["JudgeBudget"](cap_usd=1.0, per_call_usd=2.0**-100)
    max_calls = budget.max_calls
    budget.calls = max_calls  # as if every paid-for call had been made
    return [type(max_calls).__name__, max_calls > 0, budget.try_spend(), budget.refused,
            budget.calls == max_calls]

# Accepted but hostile amounts: the allowance still binds.
hostile = {{
    "huge cap one under the price": probe(huge_amounts),
    "huge cap one under the price, run": attempt(rows=1, max_trials=1, cap_usd=10**15 - 1, price=10**15),
    "cap = price = 1e-15, 100 rows": attempt(rows=100, max_trials=1, cap_usd=1e-15, price=1e-15),
    "price 2**-100 at its allowance": probe(tiny_price),
}}

import threading

def overlapping(record, start):
    # Starts a second budgeted run while the first one is inside optimize_sync().
    def action(outer_budget):
        inner = FakeOptimized()
        def second_run():
            try:
                ns["run_with_judge_budget"](inner, rows=1, max_trials=1, cap_usd=PRICE)
                record["raised"] = None
            except Exception as exc:
                record["raised"] = f"{{type(exc).__name__}}: {{exc}}"
        start(second_run)
        record["inner_calls"] = inner.calls
        record["outer_still_installed"] = ns["JUDGE_BUDGET"] is outer_budget
        record["outer_spends"] = outer_budget.try_spend()
    return action

def same_thread(run):
    run()

def other_thread(run):
    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

run_lock = {{}}
for name, start in (("nested", same_thread), ("other_thread", other_thread)):
    record = {{}}
    run_lock[name] = {{"outer": attempt(rows=1, max_trials=1, cap_usd=PRICE, action=overlapping(record, start)),
                      "second": record,
                      "next_run": attempt(rows=1, max_trials=1, cap_usd=PRICE)}}
for name, first in (("value_error", attempt(rows=0)),
                    ("optimizer_raises", attempt(rows=1, max_trials=1, cap_usd=PRICE, action=boom)),
                    ("judge_call_refused", attempt(rows=1, max_trials=1, cap_usd=PRICE, action=overspend))):
    run_lock[f"after_{{name}}"] = {{"first": first, "next_run": attempt(rows=1, max_trials=1, cap_usd=PRICE)}}

import math
from fractions import Fraction

def construct(cap, price):
    try:
        return {{"max_calls": ns["JudgeBudget"](cap_usd=cap, per_call_usd=price).max_calls, "raised": None}}
    except Exception as exc:
        return {{"max_calls": None, "raised": f"{{type(exc).__name__}}: {{exc}}"}}

def exact_division(cap, price):
    # Float division floors 0.3 / 0.1 to 2; the decimals as written buy 3.
    budget = ns["JudgeBudget"](cap_usd=cap, per_call_usd=price)
    granted = sum(budget.try_spend() for _ in range(100))
    return [granted, budget.refused, budget.spent <= budget.cap,
            budget.spent == float(granted * Fraction(repr(price)))]

division = {{f"{{cap}} at {{price}}": exact_division(cap, price)
            for cap, price in ((0.3, 0.1), (0.7, 0.1), (2.3, 0.1), (4.35, 0.05))}}

class UnderquotedPrice(float):
    def __str__(self):
        return "0.001"

class OverstatedCap(float):
    def __str__(self):
        return "1e999"

class IntCap(int):
    pass

class NanRows(int):
    def __mul__(self, other):
        return float("nan")

subclasses = {{
    "per_call_usd": construct(1.0, UnderquotedPrice(1.0)),
    "cap_usd": construct(OverstatedCap(0.5), 0.002),
    "int cap_usd": construct(IntCap(1), 0.002),
    "rows": attempt(rows=NanRows(500), max_trials=50, cap_usd=PRICE),
}}

# Above 2**53 a float and its shortest decimal can straddle an int; the ceiling closes it.
ceiling = {{
    "float 2**60 cap, int 2**60 + 1 price": construct(float(2**60), 2**60 + 1),
    "int 2**60 cap, float 2**60 price": construct(2**60, float(2**60)),
    "int 2**53 + 3 cap, int 2**53 + 4 price": construct(2**53 + 3, 2**53 + 4),
    "int cap 10**15 + 1": construct(10**15 + 1, 1.0),
    "int price 10**15 + 1": construct(10**15, 10**15 + 1),
    "1e15 at 1e15": construct(1e15, 1e15),
    "10**15 at 1e15": construct(10**15, 1e15),
}}

try:
    import numpy as np
except ImportError:
    numpy_scalars = None
else:
    numpy_scalars = {{
        "cap_usd": attempt(cap_usd=np.float64(1.0)),
        "rows": attempt(rows=np.int64(50)),
    }}

def spent_at_huge_count():
    budget = ns["JudgeBudget"](cap_usd=1.0, per_call_usd=1e-320)
    budget.calls = 10**309  # far under the 10**320 calls the cap buys
    granted = budget.try_spend()
    return [granted, type(budget.spent).__name__, math.isfinite(budget.spent), budget.spent <= budget.cap]

emit({{"constructor": constructor, "granted": granted, "refused": control.refused,
       "wrapper": wrapper, "wrapper_control": wrapper_control, "lifecycle": lifecycle,
       "exact": exact, "hostile": hostile, "run_lock": run_lock, "division": division,
       "subclasses": subclasses, "ceiling": ceiling, "numpy_scalars": numpy_scalars,
       "huge_count": probe(spent_at_huge_count)}})
"""


@pytest.fixture(scope="module", params=sorted(TEMPLATE_CASES))
def matrix(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> dict:
    """One driver run per template; every bad input is tried in the same process."""
    body = MATRIX_BODY.format(
        bad_amounts=json.dumps(BAD_AMOUNTS), bad_counts=json.dumps(BAD_COUNTS)
    )
    return _run_template(tmp_path_factory.mktemp(request.param), request.param, body)


def _names(message: str | None, name: str) -> bool:
    return (
        bool(message)
        and message.startswith("ValueError")
        and bool(re.search(rf"\b{re.escape(name)}\b", message))
    )


@pytest.mark.parametrize("cap", ['float("nan")', 'float("inf")'])
@pytest.mark.parametrize("case", sorted(TEMPLATE_CASES))
def test_non_finite_cap_makes_no_judge_call_on_a_real_run(
    case: str, cap: str, tmp_path: Path
) -> None:
    """The reported repro: 4 rows x 2 trials through the SDK grid run, cap NaN or inf."""
    result = _run_template(
        tmp_path, case, f"emit(run(rows=4, max_trials=2, cap_usd={cap}))\n"
    )
    assert _names(result["raised"], "cap_usd"), result
    assert result["judge_calls"] == 0, result


def test_judge_budget_rejects_a_cap_or_price_that_disables_it(matrix: dict) -> None:
    accepted = {
        f"{name}={label}": message
        for name, outcomes in matrix["constructor"].items()
        for label, message in outcomes.items()
        if not _names(message, name)
    }
    assert accepted == {}, accepted
    # A valid budget still grants exactly floor(cap / price) calls.
    assert (matrix["granted"], matrix["refused"]) == (500, 100), matrix


def test_run_rejects_bad_inputs_before_dispatch(matrix: dict) -> None:
    wrong = {}
    for name, outcomes in matrix["wrapper"].items():
        for label, run in outcomes.items():
            named = name == "derived_total" or _names(run["raised"], name)
            is_value_error = bool(run["raised"]) and run["raised"].startswith(
                "ValueError"
            )
            if (
                not (named and is_value_error)
                or run["calls"]
                or not run["budget_cleared"]
            ):
                wrong[f"{name}={label}"] = run
    assert wrong == {}, wrong
    control = matrix["wrapper_control"]
    assert control["raised"] is None, control
    assert control["returned"] == "optimized", control
    assert control["calls"] == [{"max_trials": 8, "budget_cap": 1.0}], control
    assert control["budget_cleared"], control


def test_budget_is_cleared_when_the_run_ends(matrix: dict) -> None:
    lifecycle = matrix["lifecycle"]
    assert lifecycle["success"]["raised"] is None, lifecycle
    assert lifecycle["optimizer_raises"]["raised"].startswith("KeyError"), lifecycle
    refused = lifecycle["judge_call_refused"]["raised"]
    assert refused and refused.startswith("RuntimeError"), lifecycle
    assert "2 judge call(s) refused" in refused, lifecycle
    for name, run in lifecycle.items():
        assert len(run["calls"]) == 1, (name, run)
        assert run["budget_cleared"], (name, run)


def _coverage_refusal(message: str | None) -> bool:
    return bool(message) and bool(
        re.match(r"ValueError: judge cap \$\S+ covers \d+ judge call\(s\) ", message)
    )


def test_derived_totals_are_refused_by_the_coverage_check(matrix: dict) -> None:
    """Huge rows x trials is an integer compare, never float overflow."""
    wrong = {
        label: run
        for label, run in matrix["wrapper"]["derived_total"].items()
        if not _coverage_refusal(run["raised"])
    }
    assert wrong == {}, wrong
    raised = matrix["wrapper"]["derived_total"][
        "rows*max_trials*price too large for a float, int price"
    ]["raised"]
    assert raised.startswith(
        "ValueError: judge cap $1.0 covers 1 judge call(s) at $1.0 each"
    ), raised
    assert f"trials need {10**600};" in raised, raised


def test_allowance_is_exact_for_realistic_caps(matrix: dict) -> None:
    """Summed float prices granted 24,999 of 25,000 paid-for calls and broke a sized run."""
    exact = matrix["exact"]
    assert exact["cap 50 at 0.002"] == [25_000, 1], exact
    assert exact["cap 200 at 0.002"] == [100_000, 1], exact
    run = exact["500 rows x 50 trials at cap 50.0"]
    assert run["raised"] is None, run
    assert run["returned"] == "optimized", run
    assert len(run["calls"]) == 1, run
    assert run["budget_cleared"], run


def test_accepted_hostile_amounts_still_bind(matrix: dict) -> None:
    hostile = matrix["hostile"]
    # A cap one dollar under a huge price buys nothing (2**53 + 3 under 2**53 + 4 used
    # to round up and grant a call; amounts that large are now refused outright).
    assert hostile["huge cap one under the price"] == {
        "value": [0, False, 1],
        "raised": None,
    }, hostile
    run = hostile["huge cap one under the price, run"]
    assert _coverage_refusal(run["raised"]), run
    assert " covers 0 judge call(s) " in run["raised"], run
    assert run["calls"] == [], run
    # An absolute tolerance let a 1e-15 cap pay for 100 calls at 1e-15.
    run = hostile["cap = price = 1e-15, 100 rows"]
    assert _coverage_refusal(run["raised"]), run
    assert " covers 1 judge call(s) " in run["raised"], run
    assert run["calls"] == [], run
    # A price below the float resolution of the running total stopped it growing.
    assert hostile["price 2**-100 at its allowance"] == {
        "value": ["int", True, False, 1, True],
        "raised": None,
    }, hostile


@pytest.mark.parametrize("overlap", ["nested", "other_thread"])
def test_overlapping_run_is_refused_and_leaves_the_first_intact(
    matrix: dict, overlap: str
) -> None:
    """The evaluator reads one global, so a second run spent from and cleared the first's budget."""
    result = matrix["run_lock"][overlap]
    second = result["second"]
    assert second["raised"] and second["raised"].startswith("RuntimeError"), result
    assert "already running" in second["raised"], result
    assert second["inner_calls"] == [], result
    assert second["outer_still_installed"] is True, result
    assert second["outer_spends"] is True, result
    outer = result["outer"]
    assert outer["raised"] is None and outer["returned"] == "optimized", result
    assert outer["budget_cleared"], result
    next_run = result["next_run"]
    assert next_run["raised"] is None and len(next_run["calls"]) == 1, result
    assert next_run["budget_cleared"], result


@pytest.mark.parametrize(
    "first", ["after_value_error", "after_optimizer_raises", "after_judge_call_refused"]
)
def test_run_lock_is_released_however_a_run_ends(matrix: dict, first: str) -> None:
    result = matrix["run_lock"][first]
    assert result["first"]["raised"], result
    next_run = result["next_run"]
    assert next_run["raised"] is None, result
    assert next_run["returned"] == "optimized" and len(next_run["calls"]) == 1, result
    assert next_run["budget_cleared"], result


def test_allowance_is_the_exact_quotient_of_the_decimals(matrix: dict) -> None:
    """Float division grants one call too few here; spent never reads above the cap."""
    assert matrix["division"] == {
        "0.3 at 0.1": [3, 97, True, True],
        "0.7 at 0.1": [7, 93, True, True],
        "2.3 at 0.1": [23, 77, True, True],
        "4.35 at 0.05": [87, 13, True, True],
    }, matrix["division"]


def test_numeric_subclasses_are_rejected(matrix: dict) -> None:
    """A subclass can report one value to the checks and another to the arithmetic."""
    subclasses = matrix["subclasses"]
    for label in ("per_call_usd", "cap_usd", "int cap_usd"):
        outcome = subclasses[label]
        assert _names(outcome["raised"], label.split()[-1]), (label, outcome)
        assert outcome["max_calls"] is None, (label, outcome)
    rows = subclasses["rows"]
    assert _names(rows["raised"], "rows"), rows
    assert rows["calls"] == [] and rows["budget_cleared"], rows


def test_amounts_above_the_ceiling_are_rejected(matrix: dict) -> None:
    """float(2**60) read as ...847000 against an exact int price of ...846977 granted a call."""
    ceiling = matrix["ceiling"]
    for label, name in (
        ("float 2**60 cap, int 2**60 + 1 price", "cap_usd"),
        ("int 2**60 cap, float 2**60 price", "cap_usd"),
        ("int 2**53 + 3 cap, int 2**53 + 4 price", "cap_usd"),
        ("int cap 10**15 + 1", "cap_usd"),
        ("int price 10**15 + 1", "per_call_usd"),
    ):
        outcome = ceiling[label]
        assert _names(outcome["raised"], name), (label, outcome)
        assert "1e+15" in outcome["raised"], (label, outcome)
    for label in ("1e15 at 1e15", "10**15 at 1e15"):
        assert ceiling[label] == {"max_calls": 1, "raised": None}, (label, ceiling)


def test_numpy_scalars_are_rejected(matrix: dict) -> None:
    scalars = matrix["numpy_scalars"]
    if scalars is None:
        pytest.skip("numpy is not installed in this SDK environment")
    for name, run in scalars.items():
        assert _names(run["raised"], name), (name, run)
        assert run["calls"] == [] and run["budget_cleared"], (name, run)


def test_spent_never_overflows_on_a_valid_counter(matrix: dict) -> None:
    """calls * price as int * float overflowed at 10**309 calls of a 1e-320 price."""
    assert matrix["huge_count"] == {
        "value": [True, "float", True, True],
        "raised": None,
    }, matrix["huge_count"]


def test_prose_does_not_size_the_cap_as_a_float_product() -> None:
    """11 * 0.015 is 0.16499999999999998, which buys 10 calls, not 11."""
    text = TEMPLATES.read_text(encoding="utf-8")
    assert "size the cap as calls" not in text
    assert text.count("Write the cap as a decimal literal") == 2


def _shared_budget_code(block: str) -> str:
    start = block.index("class JudgeBudget:")
    wrapper = block.index("\ndef run_with_judge_budget", start)
    end = re.compile(r"^\S", re.M).search(block, block.index("\n", wrapper + 1) + 1)
    assert end, "run_with_judge_budget runs to the end of the block"
    return block[start : end.start()]


def test_both_templates_carry_the_same_budget_code() -> None:
    judge = _python_block(TEMPLATES, JUDGE_MARKER)
    hybrid = _python_block(TEMPLATES, HYBRID_MARKER)
    for block in (judge, hybrid):
        assert re.search(r"^import math$", block, re.M), block[:200]
        assert re.search(r"^from fractions import Fraction$", block, re.M), block[:200]
        assert "_JUDGE_RUN_LOCK.release()" in _shared_budget_code(block), block[:200]
    assert _shared_budget_code(judge) == _shared_budget_code(hybrid)
