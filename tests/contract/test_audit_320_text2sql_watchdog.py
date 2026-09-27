"""text2SQL reference: the query watchdog must not score correct SQL on real-size tables 0.

Traigent/traigent-skills#320. A 100k-VM-step watchdog interrupted a GROUP BY on
10k rows and a COUNT on 50k rows, and ``_run`` mapped the interrupt to the
same ``(False, None)`` as wrong SQL, so a correct prediction silently scored 0.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from .extract import _iter_fenced_blocks

RECIPE = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "traigent-recipe-text2sql"
    / "references"
    / "quickstart_text2sql.md"
)


@pytest.fixture()
def recipe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    pytest.importorskip("traigent")
    monkeypatch.setenv("TRAIGENT_DATASET_ROOT", str(tmp_path))
    blocks = _iter_fenced_blocks(RECIPE.read_text(encoding="utf-8").splitlines())
    python_blocks = [block for block in blocks if block.language == "python"]
    assert len(python_blocks) == 1
    namespace: dict[str, object] = {"__name__": "quickstart_text2sql_under_test"}
    exec(compile(python_blocks[0].text, str(RECIPE), "exec"), namespace)
    return SimpleNamespace(**namespace)


def _big_db(path: Path, rows: int) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, x INTEGER)")
    con.executemany("INSERT INTO t VALUES (?, ?)", [(i, i % 97) for i in range(rows)])
    con.commit()
    con.close()


@pytest.mark.parametrize("rows", [10_000, 50_000])
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM t WHERE x > 50",
        "SELECT x, COUNT(*) FROM t GROUP BY x ORDER BY COUNT(*) DESC LIMIT 3",
    ],
)
def test_correct_sql_on_a_real_size_table_is_not_interrupted(
    recipe: SimpleNamespace, tmp_path: Path, rows: int, sql: str
) -> None:
    db = tmp_path / "big.sqlite"
    _big_db(db, rows)
    recipe._run.__globals__["DB_PATH"] = db
    ok, result = recipe._run(sql)
    assert ok and result, f"{rows}-row table: {sql!r} was aborted and would score 0"


def test_runaway_query_is_stopped_within_the_budget_and_reported(
    recipe: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    globals_ = recipe._run.__globals__
    assert "_QUERY_BUDGET_S" in globals_, "the watchdog is not bounded by a time budget"
    globals_["DB_PATH"] = tmp_path / "store.sqlite"
    recipe.build_db()
    globals_["_QUERY_BUDGET_S"] = 0.5
    before = recipe._RUN["timeouts"]

    started = time.monotonic()
    assert recipe._run(
        "WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM c) SELECT max(n) FROM c"
    ) == (False, None)
    assert time.monotonic() - started < 5.0

    # A timeout is reported distinctly from an SQL error ...
    assert recipe._RUN["timeouts"] == before + 1
    assert "exceeded" in capsys.readouterr().out
    # ... and plain wrong SQL is not counted as a timeout.
    assert recipe._run("SELECT * FROM missing_table") == (False, None)
    assert recipe._RUN["timeouts"] == before + 1
    assert "exceeded" not in capsys.readouterr().out
