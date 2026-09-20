from __future__ import annotations

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
    # The extracted recipe uses setdefault at import time; contain that
    # process-wide environment change so other runnable-snippet cases inherit
    # their own dataset-root setup.
    monkeypatch.setenv("TRAIGENT_DATASET_ROOT", str(tmp_path))
    blocks = _iter_fenced_blocks(RECIPE.read_text(encoding="utf-8").splitlines())
    python_blocks = [block for block in blocks if block.language == "python"]
    assert len(python_blocks) == 1
    namespace: dict[str, object] = {"__name__": "quickstart_text2sql_under_test"}
    exec(compile(python_blocks[0].text, str(RECIPE), "exec"), namespace)
    return SimpleNamespace(**namespace)


def test_extracted_run_helper_allows_reads_and_rejects_sqlite_escape_hatches(
    recipe: SimpleNamespace, tmp_path: Path
) -> None:
    recipe._run.__globals__["DB_PATH"] = tmp_path / "store.sqlite"
    recipe.build_db()

    assert recipe._run("SELECT COUNT(*) FROM products") == (True, [(4,)])
    assert recipe._run("SELECT SUM(quantity) FROM orders") == (True, [(12,)])

    attached = tmp_path / "attached.sqlite"
    forbidden = [
        f"ATTACH DATABASE '{attached}' AS escaped",
        "UPDATE products SET price = 0",
        "PRAGMA writable_schema=ON",
        "SELECT load_extension('missing-extension')",
    ]
    for sql in forbidden:
        assert recipe._run(sql) == (False, None), sql

    assert not attached.exists()
    assert recipe._run("SELECT MIN(price) FROM products") == (True, [(4.25,)])


def test_extracted_run_helper_closes_the_connection_after_execution_failure(
    recipe: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recipe._run.__globals__["DB_PATH"] = tmp_path / "store.sqlite"
    recipe.build_db()
    sqlite3_module = recipe._run.__globals__["sqlite3"]
    real_connect = sqlite3_module.connect
    connections = []

    class TrackingConnection:
        def __init__(self, connection):
            self.connection = connection
            self.closed = False

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def close(self):
            self.closed = True
            return self.connection.close()

    def tracking_connect(*args, **kwargs):
        connection = TrackingConnection(real_connect(*args, **kwargs))
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3_module, "connect", tracking_connect)

    assert recipe._run("SELECT * FROM missing_table") == (False, None)
    assert len(connections) == 1
    assert connections[0].closed is True
