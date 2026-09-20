from __future__ import annotations

import sys
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


def _run_main(
    recipe: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    result: SimpleNamespace,
    mode: str,
) -> int:
    globals_ = recipe.main.__globals__
    monkeypatch.setitem(globals_, "build_db", lambda: None)
    monkeypatch.setitem(globals_, "check_golds", lambda: None)
    monkeypatch.setitem(globals_, "write_dataset", lambda: None)

    class Decorated:
        def optimize_sync(self, **kwargs):
            return result

    def optimize(**kwargs):
        return lambda function: Decorated()

    monkeypatch.setattr(recipe.traigent, "optimize", optimize)
    monkeypatch.setenv("TRAIGENT_API_KEY", "test-only-key")
    monkeypatch.setattr(sys, "argv", ["quickstart_text2sql.py", mode])
    if mode == "--mock":
        import traigent.testing

        monkeypatch.setattr(
            traigent.testing, "enable_mock_mode_for_quickstart", lambda: None
        )
    return recipe.main()


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


def test_extracted_real_recipe_missing_credentials_stops_before_optimization(
    recipe: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    globals_ = recipe.main.__globals__
    monkeypatch.setitem(globals_, "DB_PATH", tmp_path / "store.sqlite")
    monkeypatch.setitem(globals_, "DATA_PATH", tmp_path / "eval.jsonl")
    monkeypatch.delenv("TRAIGENT_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["quickstart_text2sql.py", "--real"])

    def unexpected_optimization(*args, **kwargs):
        pytest.fail("missing credentials reached optimization")

    monkeypatch.setattr(recipe.traigent, "optimize", unexpected_optimization)
    assert recipe.main() == 2
    assert "TRAIGENT_API_KEY not set" in capsys.readouterr().out


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


@pytest.mark.parametrize(
    ("metadata", "diagnostic"),
    [
        (
            {"persistence_rejection_reason": "duplicate example", "source": "api"},
            "REJECTED the submission",
        ),
        (
            {"fallback_reason": "unreachable", "source": "local_fallback"},
            "fell back to local-only",
        ),
        ({"source": "unknown"}, "was NOT synced to the portal"),
    ],
)
def test_extracted_real_recipe_returns_nonzero_for_every_missing_link_diagnostic(
    recipe: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    metadata: dict[str, str],
    diagnostic: str,
) -> None:
    result = SimpleNamespace(
        cloud_url=None,
        metadata=metadata,
        best_config={},
        best_configuration={},
        successful_trials=1,
        trials=1,
    )

    assert _run_main(recipe, monkeypatch, result, "--real") != 0
    assert diagnostic in capsys.readouterr().out


def test_extracted_real_recipe_keeps_cloud_link_success_path(
    recipe: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = SimpleNamespace(
        cloud_url="https://portal.traigent.ai/runs/test",
        metadata={},
        best_config={"model": "test"},
        successful_trials=1,
        trials=1,
    )

    assert _run_main(recipe, monkeypatch, result, "--real") == 0
    assert result.cloud_url in capsys.readouterr().out


def test_extracted_recipe_keeps_mock_success_path(
    recipe: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(
        cloud_url=None,
        metadata={},
        best_config={},
        best_configuration={},
        successful_trials=1,
        trials=1,
    )

    assert _run_main(recipe, monkeypatch, result, "--mock") == 0
