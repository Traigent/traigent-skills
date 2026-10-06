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

Review round 3: the SDK returns on an evaluator timeout while the evaluator thread
keeps running, and the evaluators read the budget from a module global, so a
leftover thread of one run spent the next run's budget and made a correctly sized
run raise. The global and the one-run-per-process lock are gone: the wrapper takes
the evaluator, binds this run's budget into the evaluator it hands the SDK, and
refuses a ``custom_evaluator`` passed through it.
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

# Each template's decorated function and evaluator, as its usage example names them.
USAGE = {
    "judge": ("answer", "llm_judge_evaluator"),
    "hybrid": ("extract", "hybrid_evaluator"),
}

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
    # Records each dispatch; scores a row only through the evaluator it is handed.
    def __init__(self, action=None):
        self.calls, self.budgets, self.action = [], [], action
    def optimize_sync(self, custom_evaluator=None, **kwargs):
        self.calls.append({{"max_trials": kwargs.get("max_trials"), "bound": callable(custom_evaluator)}})
        self.budgets.append(budgets[-1])  # the budget this run built just before dispatch
        if self.action:
            self.action(lambda: custom_evaluator(agent, {{}}, example), budgets[-1])
        return "optimized"

PRICE = ns["JUDGE_COST_PER_CALL_USD"]

def attempt(rows=50, max_trials=8, cap_usd=1.0, price=PRICE, action=None, evaluator=evaluator, **optimize_kwargs):
    ns["JUDGE_COST_PER_CALL_USD"] = price
    fake, first = FakeOptimized(action), len(budgets)
    try:
        returned = ns["run_with_judge_budget"](
            fake, evaluator, rows=rows, max_trials=max_trials, cap_usd=cap_usd, **optimize_kwargs)
        raised = None
    except Exception as exc:
        returned, raised = None, f"{{type(exc).__name__}}: {{exc}}"
    finally:
        ns["JUDGE_COST_PER_CALL_USD"] = PRICE
    return {{"raised": raised, "returned": returned, "calls": fake.calls,
            "built": len(budgets) - first,
            "budgets": [[b.cap, b.calls, b.refused] for b in fake.budgets]}}

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

def boom(evaluate, budget):
    raise KeyError("optimizer failed")

def scores(times):
    def action(evaluate, budget):
        for _ in range(times):
            evaluate()
    return action

overspend = scores(3)

lifecycle = {{
    "success": attempt(rows=1, max_trials=1, cap_usd=PRICE, action=scores(1)),
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
    def action(evaluate, budget):
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
    # A second budgeted run starts and scores while the first is inside optimize_sync().
    def action(evaluate, outer_budget):
        evaluate()
        def second_run():
            record["second"] = attempt(rows=2, max_trials=1, cap_usd=2 * PRICE, action=scores(2))
        start(second_run)
        evaluate()  # the first run's second row, after the second run spent all of its budget
    return action

def same_thread(run):
    run()

def other_thread(run):
    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

overlap = {{}}
for name, start in (("nested", same_thread), ("other_thread", other_thread)):
    record = {{}}
    record["first"] = attempt(rows=2, max_trials=1, cap_usd=2 * PRICE, action=overlapping(record, start))
    overlap[name] = record

bypass = {{
    "custom_evaluator": attempt(rows=1, max_trials=1, cap_usd=PRICE, custom_evaluator=evaluator),
    "evaluator None": attempt(rows=1, max_trials=1, cap_usd=PRICE, evaluator=None),
    "evaluator name": attempt(rows=1, max_trials=1, cap_usd=PRICE, evaluator="llm_judge_evaluator"),
}}

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
       "exact": exact, "hostile": hostile, "overlap": overlap, "bypass": bypass, "division": division,
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


# Run A's evaluator thread outlives run A, as on an SDK evaluator timeout, and
# scores while run B is running. Run B is sized for exactly its own rows.
STALE_WORKER_BODY = """
import inspect
import threading

PRICE = ns["JUDGE_COST_PER_CALL_USD"]
release, entered, stale, b_rows = threading.Event(), threading.Event(), {}, []

def scorer(custom_evaluator):
    # The SDK's choice: an optimize()-time custom_evaluator, else the decorator's.
    return custom_evaluator or evaluator

def blocking_agent(**kwargs):
    entered.set()
    release.wait(60)
    return agent(**kwargs)

class TimedOutRun:
    # Gives up on a row and raises while its evaluator thread lives on.
    def optimize_sync(self, custom_evaluator=None, **kwargs):
        score = scorer(custom_evaluator)
        def worker():
            if stage == "queued":  # not yet inside the evaluator when the run gives up
                release.wait(60)
            try:
                stale["error_message"] = score(blocking_agent, {}, example).error_message
            except Exception as exc:
                stale["raised"] = f"{type(exc).__name__}: {exc}"
        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()
        if stage == "in_agent":
            entered.wait(60)
        raise TimeoutError("evaluator timed out")

class NextRun:
    def optimize_sync(self, custom_evaluator=None, **kwargs):
        score = scorer(custom_evaluator)
        release.set()
        timed_out.worker.join(60)  # run A's thread finishes while run B is in progress
        b_rows.extend(score(agent, {}, example).error_message for _ in range(2))
        return "optimized"

takes_evaluator = "evaluator" in inspect.signature(ns["run_with_judge_budget"]).parameters

def start(optimized, **kwargs):
    args = (evaluator,) if takes_evaluator else ()
    try:
        return {"returned": ns["run_with_judge_budget"](optimized, *args, **kwargs), "raised": None}
    except Exception as exc:
        return {"returned": None, "raised": f"{type(exc).__name__}: {exc}"}

timed_out, first = TimedOutRun(), len(budgets)
run_a = start(timed_out, rows=1, max_trials=1, cap_usd=PRICE)
run_b = start(NextRun(), rows=2, max_trials=1, cap_usd=2 * PRICE)
emit({"a": run_a, "b": run_b, "stale": stale, "b_rows": b_rows,
      "worker_alive": timed_out.worker.is_alive(),
      "budgets": [[b.calls, b.refused] for b in budgets[first:]]})
"""


@pytest.mark.parametrize("stage", ["queued", "in_agent"])
@pytest.mark.parametrize("case", sorted(TEMPLATE_CASES))
def test_a_leftover_evaluator_thread_spends_only_its_own_runs_budget(
    case: str, stage: str, tmp_path: Path
) -> None:
    """A timed-out run's evaluator thread read the next run's budget, so that run raised."""
    result = _run_template(tmp_path, case, f"stage = {stage!r}\n" + STALE_WORKER_BODY)
    assert result["a"]["raised"] == "TimeoutError: evaluator timed out", result
    assert result["worker_alive"] is False, result
    assert result["stale"] == {"error_message": None}, result
    assert result["b"] == {"returned": "optimized", "raised": None}, result
    assert result["b_rows"] == [None, None], result
    # Run A's budget paid for its own row; run B kept its full allowance.
    assert result["budgets"] == [[1, 0], [2, 0]], result


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
            if not (named and is_value_error) or run["calls"]:
                wrong[f"{name}={label}"] = run
    assert wrong == {}, wrong
    control = matrix["wrapper_control"]
    assert control["raised"] is None, control
    assert control["returned"] == "optimized", control
    assert control["calls"] == [{"max_trials": 8, "bound": True}], control
    assert control["budgets"] == [[1.0, 0, 0]], control


def test_the_sdk_scores_with_the_evaluator_bound_to_the_run(matrix: dict) -> None:
    """The evaluator handed to optimize_sync() spends this run's budget, however the run ends."""
    lifecycle = matrix["lifecycle"]
    price = 0.002
    assert lifecycle["success"]["raised"] is None, lifecycle
    assert lifecycle["success"]["budgets"] == [[price, 1, 0]], lifecycle
    assert lifecycle["optimizer_raises"]["raised"].startswith("KeyError"), lifecycle
    refused = lifecycle["judge_call_refused"]["raised"]
    assert refused and refused.startswith("RuntimeError"), lifecycle
    assert "2 judge call(s) refused" in refused, lifecycle
    assert lifecycle["judge_call_refused"]["budgets"] == [[price, 1, 2]], lifecycle
    for name, run in lifecycle.items():
        assert run["calls"] == [{"max_trials": 1, "bound": True}], (name, run)


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
    assert run["budgets"] == [[50.0, 25_000, 0]], run


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
def test_overlapping_runs_each_spend_only_their_own_budget(
    matrix: dict, overlap: str
) -> None:
    """Each run is sized for exactly its own rows, so any cross-spend refuses a call."""
    price = 0.002
    first, second = (
        matrix["overlap"][overlap]["first"],
        matrix["overlap"][overlap]["second"],
    )
    for run in (first, second):
        assert run["raised"] is None and run["returned"] == "optimized", (first, second)
        assert run["calls"] == [{"max_trials": 1, "bound": True}], (first, second)
        assert run["budgets"] == [[2 * price, 2, 0]], (first, second)


@pytest.mark.parametrize(
    ("label", "name"),
    [
        ("custom_evaluator", "custom_evaluator"),
        ("evaluator None", "evaluator"),
        ("evaluator name", "evaluator"),
    ],
)
def test_run_refuses_an_evaluator_that_would_bypass_the_budget(
    matrix: dict, label: str, name: str
) -> None:
    """A custom_evaluator in the optimize kwargs would replace the budgeted evaluator."""
    run = matrix["bypass"][label]
    assert _names(run["raised"], name), run
    assert run["calls"] == [] and run["built"] == 0, run


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
    assert rows["calls"] == [], rows


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
        assert run["calls"] == [], (name, run)


def test_spent_never_overflows_on_a_valid_counter(matrix: dict) -> None:
    """calls * price as int * float overflowed at 10**309 calls of a 1e-320 price."""
    assert matrix["huge_count"] == {
        "value": [True, "float", True, True],
        "raised": None,
    }, matrix["huge_count"]


def test_prose_does_not_size_the_cap_as_a_float_product() -> None:
    """11 * 0.015 is 0.16499999999999998, which buys 10 calls, not 11."""
    text = TEMPLATES.read_text(encoding="utf-8")
    assert repr(11 * 0.015) == "0.16499999999999998"
    assert text.count("Write the cap as a decimal literal") == 2
    assert text.count("`11 * 0.015`, which is `0.16499999999999998` and buys 10") == 2
    # The cost caveat tells users to multiply calls by price; it must point the
    # judge cap at the decimal-literal rule instead of at that float product.
    caveat = text.split("## Cost metering caveat", 1)[1].split("\n## ", 1)[0]
    assert "calls_per_row" in caveat and "decimal literal" in caveat, caveat


def test_prose_bounds_the_exact_allowance_to_fifteen_digits() -> None:
    """Python rounds a longer float literal before the template sees it."""
    text = TEMPLATES.read_text(encoding="utf-8")
    assert float("999999999999999.99") == 1e15
    assert "decimal values as written" not in text
    assert text.count("up to 15 significant digits") == 2


def _shared_budget_code(block: str) -> str:
    start = block.index("class JudgeBudget:")
    wrapper = block.index("\ndef run_with_judge_budget", start)
    end = re.compile(r"^\S", re.M).search(block, block.index("\n", wrapper + 1) + 1)
    assert end, "run_with_judge_budget runs to the end of the block"
    return block[start : end.start()]


def test_both_templates_carry_the_same_budget_code() -> None:
    judge = _python_block(TEMPLATES, JUDGE_MARKER)
    hybrid = _python_block(TEMPLATES, HYBRID_MARKER)
    for case, block in (("judge", judge), ("hybrid", hybrid)):
        assert re.search(r"^import math$", block, re.M), block[:200]
        assert re.search(r"^from fractions import Fraction$", block, re.M), block[:200]
        shared = _shared_budget_code(block)
        assert "custom_evaluator=budgeted_evaluator" in shared, shared
        # No module-level budget: a leftover evaluator thread must not see another run's.
        assert "JUDGE_BUDGET" not in block and "global " not in block, case
        fn, evaluator = USAGE[case]
        assert f"# results = run_with_judge_budget({fn}, {evaluator}, rows=" in block, (
            case
        )
        assert (
            f"def {evaluator}(func, config, example, budget: JudgeBudget | None = None)"
            in block
        )
    assert _shared_budget_code(judge) == _shared_budget_code(hybrid)
