# Quickstart Text2SQL Recipe

This reference preserves the complete runnable recipe as markdown-only skill
content. Materialize the fenced block as `quickstart_text2sql.py` outside the
scanned `skills/` payload when you want to run it.

```python
"""Turnkey text2SQL optimization example — SELF-CONTAINED, no external data.

Creates its own tiny SQLite database in a temp dir, defines a handful of
NL->SQL questions with gold SQL, instruments a minimal agent with Traigent
(SDK v0.17-compatible API), scores by EXECUTION MATCH, and runs a mock dry-run then a real
cloud-tracked optimization. This is the ice-breaker example for the QuickStart:
it runs end-to-end with only a Traigent key + an LLM key, in minutes.

    python quickstart_text2sql.py --mock     # free; validates the whole pipeline
    python quickstart_text2sql.py --real      # cost-capped, portal-tracked

Env (from .env): TRAIGENT_API_KEY, and an LLM key (OPENROUTER_API_KEY is easiest).
Requires: pip install -U "traigent>=0.19" litellm  (Python 3.12).

To scale up: swap the embedded DB + questions for the real SPIDER dev set (each
example carries a db_id; resolve schema/connection per db_id) — the wiring below
is identical.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import litellm

import traigent
from traigent.api.decorators import EvaluationOptions, ExecutionOptions
from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema
from traigent.evaluators.base import ExampleResult

WORK = Path(tempfile.gettempdir()) / "traigent_text2sql_quickstart"
WORK.mkdir(exist_ok=True)
DB_PATH = WORK / "store.sqlite"
DATA_PATH = WORK / "testbed.jsonl"
# The SDK sandboxes dataset paths: the eval_dataset must reside under the CWD or
# under TRAIGENT_DATASET_ROOT. Point that root at our temp work dir.
os.environ.setdefault("TRAIGENT_DATASET_ROOT", str(WORK))

# --------------------------------------------------------------------------- #
# 1. Build a tiny self-contained database (the "store" schema)
# --------------------------------------------------------------------------- #
def build_db() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city TEXT);
        CREATE TABLE products  (id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL);
        CREATE TABLE orders    (id INTEGER PRIMARY KEY, customer_id INTEGER, product_id INTEGER,
                                quantity INTEGER, FOREIGN KEY(customer_id) REFERENCES customers(id),
                                FOREIGN KEY(product_id) REFERENCES products(id));
        INSERT INTO customers VALUES (1,'Alice','Boston'),(2,'Bob','Denver'),
            (3,'Carol','Boston'),(4,'Dan','Seattle');
        INSERT INTO products VALUES (1,'Widget','hardware',9.99),(2,'Gadget','hardware',19.50),
            (3,'Manual','books',4.25),(4,'Novel','books',12.00);
        INSERT INTO orders VALUES (1,1,1,3),(2,1,2,1),(3,2,1,5),(4,3,4,2),(5,1,3,1);
        """
    )
    con.commit()
    con.close()


# The testbed: questions + GOLD SQL. Few-shot exemplars (below) are drawn from
# OUTSIDE this set, so there's no leakage.
TESTBED = [
    ("How many products are there?", "SELECT COUNT(*) FROM products"),
    ("List the names of all customers in Boston.", "SELECT name FROM customers WHERE city='Boston'"),
    ("What is the name of the most expensive product?", "SELECT name FROM products ORDER BY price DESC LIMIT 1"),
    ("How many orders did each customer place? Give customer_id and the count.",
     "SELECT customer_id, COUNT(*) FROM orders GROUP BY customer_id"),
    ("What is the total quantity ordered of the product named Widget?",
     "SELECT SUM(quantity) FROM orders o JOIN products p ON o.product_id=p.id WHERE p.name='Widget'"),
    ("Which customers have not placed any orders? Give their names.",
     "SELECT name FROM customers WHERE id NOT IN (SELECT customer_id FROM orders)"),
    ("For each product category, what is the average price?",
     "SELECT category, AVG(price) FROM products GROUP BY category"),
    ("What is the name of the customer who placed the most orders?",
     "SELECT c.name FROM customers c JOIN orders o ON c.id=o.customer_id GROUP BY c.id ORDER BY COUNT(*) DESC LIMIT 1"),
]
FEWSHOT = [  # fixed in-domain exemplars, NOT in the testbed (no leakage)
    ("How many customers are there?", "SELECT COUNT(*) FROM customers"),
    ("List all product names.", "SELECT name FROM products"),
]


def write_dataset() -> None:
    with DATA_PATH.open("w", encoding="utf-8") as f:
        for q, gold in TESTBED:
            f.write(json.dumps({"input": q, "output": gold, "db_id": "store"}) + "\n")


# --------------------------------------------------------------------------- #
# 2. Schema + execution-match helpers
# --------------------------------------------------------------------------- #
def schema_ddl() -> str:
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall()
    con.close()
    return "\n".join(r[0] for r in rows if r[0])


def _run(sql: str):
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(sql).fetchall()
        con.close()
        return True, sorted(map(str, rows))   # order-insensitive compare
    except Exception:
        return False, None


def exec_match(pred_sql: str, gold_sql: str) -> float:
    p_ok, p = _run(pred_sql)
    g_ok, g = _run(gold_sql)
    return 1.0 if (p_ok and g_ok and p == g) else 0.0


# --------------------------------------------------------------------------- #
# 3. The agent — every knob is READ at the call site (no silent no-ops)
# --------------------------------------------------------------------------- #
_SYSTEM = ("You are an expert SQLite analyst. Given a schema and a question, write "
           "ONE valid SQLite query that answers it. Output only the SQL.")
_COST = {"cost": 0.0, "latency": 0.0}


def _complete(model: str, temperature: float, messages: list[dict]) -> str:
    t0 = time.time()
    resp = litellm.completion(model=model, messages=messages, temperature=temperature)
    _COST["latency"] += time.time() - t0
    try:
        _COST["cost"] += float(litellm.completion_cost(completion_response=resp) or 0.0)
    except Exception:
        pass
    text = str(resp.choices[0].message.content or "")
    # strip markdown fences / prose; keep the first statement
    import re
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    if m:
        text = m.group(1)
    kw = re.search(r"\b(SELECT|WITH)\b", text, re.I)
    return (text[kw.start():] if kw else text).split(";")[0].strip()


def run_agent(question: str, db_id: str = "store") -> str:
    cfg = traigent.get_config()
    model = cfg["model"]
    temperature = float(cfg.get("temperature", 0.0))
    fewshot_k = int(cfg.get("fewshot_k", "0"))               # string-encoded knob
    generation_path = cfg.get("generation_path", "direct")

    parts = [f"Database schema:\n{schema_ddl()}"]
    for q, sql in FEWSHOT[:fewshot_k]:
        parts.append(f"Question: {q}\nSQL: {sql}")
    if generation_path == "plan_then_sql":
        parts.append(f"Question: {question}\nFirst write a one-line plan as a `--` SQL "
                     "comment, then the final SQLite query.")
    else:  # direct
        parts.append(f"Question: {question}\nReturn ONLY the SQLite query.\nSQL:")
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": "\n\n".join(parts)}]
    return _complete(model, temperature, messages)


# --------------------------------------------------------------------------- #
# 4. Custom evaluator: real execution-match accuracy + real cost/latency
# --------------------------------------------------------------------------- #
def exec_eval(func, config, example) -> ExampleResult:
    inp = example.input_data
    question = inp["input"] if isinstance(inp, dict) else inp
    gold = example.expected_output
    _COST["cost"] = 0.0
    _COST["latency"] = 0.0
    t0 = time.time()
    try:
        pred = func(question, "store")
        accuracy = exec_match(pred, gold)
        success, err = True, None
    except Exception as e:
        pred, accuracy, success, err = "", 0.0, False, str(e)
    latency = _COST["latency"] or (time.time() - t0)
    return ExampleResult(
        example_id="store",
        input_data=inp if isinstance(inp, dict) else {"input": question},
        expected_output=gold,
        actual_output=pred,
        metrics={"accuracy": accuracy, "cost": _COST["cost"], "latency": latency,
                 "exec_accuracy": accuracy},
        execution_time=latency,
        success=success,
        error_message=err,
    )


# --------------------------------------------------------------------------- #
# 5. Configure + run: ExecutionOptions(offline=...) + algorithm arg
# --------------------------------------------------------------------------- #
CONFIG_SPACE = {
    "model": ["openrouter/openai/gpt-4o-mini", "openrouter/deepseek/deepseek-chat"],
    "temperature": [0.0, 0.2],
    "fewshot_k": ["0", "2"],                       # string-encoded; int()'d at call site
    "generation_path": ["direct", "plan_then_sql"],
}
OBJECTIVES = ObjectiveSchema(
    objectives=[
        ObjectiveDefinition(name="accuracy", weight=0.80, orientation="maximize"),
        ObjectiveDefinition(name="cost",     weight=0.15, orientation="minimize"),
        ObjectiveDefinition(name="latency",  weight=0.05, orientation="minimize"),
    ],
    weights_sum=1.0,
    weights_normalized={"accuracy": 0.80, "cost": 0.15, "latency": 0.05},
)
BASELINE = {k: v[0] for k, v in CONFIG_SPACE.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="free dry-run (no spend)")
    ap.add_argument("--real", action="store_true", help="cost-capped, portal-tracked")
    ap.add_argument("--trials", type=int, default=12)
    ap.add_argument("--budget", type=float, default=1.0, help="USD cost cap for --real")
    args = ap.parse_args()
    if not (args.mock or args.real):
        print("Pick one: --mock (free) or --real (cost-capped).")
        return 2

    build_db()
    write_dataset()

    if args.mock:
        os.environ["TRAIGENT_OFFLINE_MODE"] = "true"
        from traigent.testing import enable_mock_mode_for_quickstart
        enable_mock_mode_for_quickstart()
        offline, algorithm = True, "grid"          # named smart algorithms are not yet executable
    else:
        if not os.environ.get("TRAIGENT_API_KEY"):
            print("ERROR: TRAIGENT_API_KEY not set (.env).")
            return 2
        os.environ["TRAIGENT_RUN_COST_LIMIT"] = str(args.budget)
        # --real IS the user's approval: the human chose the flag and the budget.
        # An agent must never invoke --real on the user's behalf without first
        # showing the permutation count + budget and getting an explicit go.
        os.environ["TRAIGENT_COST_APPROVED"] = "true"
        os.environ["TRAIGENT_OFFLINE_MODE"] = "false"
        # offline=False -> online/cloud, portal-tracked. "bayesian"/"tpe"/"optuna"
        # validate as known names but fail before any trial runs (clear SDK
        # error, verified against SDK 0.18.x) — use "random".
        offline, algorithm = False, "random"

    decorated = traigent.optimize(
        configuration_space=CONFIG_SPACE,
        objectives=OBJECTIVES,
        default_config=BASELINE,
        evaluation=EvaluationOptions(eval_dataset=str(DATA_PATH), custom_evaluator=exec_eval),
        execution=ExecutionOptions(offline=offline),
        experiment_name="quickstart_text2sql_store",
    )(run_agent)

    print(f"mode={'MOCK' if args.mock else 'REAL'}  offline={offline}  algorithm={algorithm}  "
          f"trials={args.trials}  testbed={len(TESTBED)}")
    # optimize_sync() = the convenience wrapper (manages the event loop); the async
    # form is `await decorated.optimize(...)`.
    result = decorated.optimize_sync(max_trials=args.trials, algorithm=algorithm)
    print("best_config:", getattr(result, "best_config", None) or getattr(result, "best_configuration", None))
    print("successful_trials:", getattr(result, "successful_trials", None),
          "/", getattr(result, "trials", None))
    if args.real:
        print("Open the View link above to see your experiment in the portal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
