"""The tie-band Pareto recipe in traigent-analyze-results must not chain-fold.

A pairwise "within the band and cheaper" test is not transitive: B folds A,
C folds B, and A disappears although it beats every survivor by more than the
band (#311). These tests execute the ``pareto_front`` helper taken verbatim
from the SKILL's fenced block and pin three properties:

* the three-row repro keeps both ``cheap`` and ``strong``;
* every dropped row is within ``TIE_BAND`` of a kept row that costs no more;
* with ``TIE_BAND = 0`` the frontier is the strict Pareto set.

The harness has no pandas, so the helper runs against a minimal frame that
implements exactly the pandas surface the recipe uses. When pandas is
installed the same checks also run against a real ``DataFrame``.
"""

from __future__ import annotations

import ast
import random
import re
from pathlib import Path
from typing import Any, Callable

import pytest

SKILL = Path("skills/traigent-analyze-results/SKILL.md")
FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)
EPS = 1e-9


# --- a minimal pandas stand-in: only what the recipe calls -----------------
class _Series:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def _op(self, other: Any, fn: Callable[[Any, Any], bool]) -> _Series:
        if isinstance(other, _Series):
            return _Series([fn(a, b) for a, b in zip(self.values, other.values)])
        return _Series([fn(a, other) for a in self.values])

    def __ge__(self, other: Any) -> _Series:  # type: ignore[override]
        return self._op(other, lambda a, b: a >= b)

    def __le__(self, other: Any) -> _Series:  # type: ignore[override]
        return self._op(other, lambda a, b: a <= b)

    def __gt__(self, other: Any) -> _Series:  # type: ignore[override]
        return self._op(other, lambda a, b: a > b)

    def __lt__(self, other: Any) -> _Series:  # type: ignore[override]
        return self._op(other, lambda a, b: a < b)

    def __and__(self, other: _Series) -> _Series:
        return self._op(other, lambda a, b: bool(a) and bool(b))

    def __or__(self, other: _Series) -> _Series:
        return self._op(other, lambda a, b: bool(a) or bool(b))

    def any(self) -> bool:
        return any(self.values)


class _Loc:
    def __init__(self, frame: _Frame) -> None:
        self.frame = frame

    def __getitem__(self, labels: list[Any]) -> _Frame:
        by_label = dict(zip(self.frame.index, self.frame.rows))
        return _Frame([by_label[label] for label in labels], list(labels))


class _Frame:
    def __init__(
        self, rows: list[dict[str, Any]], index: list[Any] | None = None
    ) -> None:
        self.rows = rows
        self.index = list(range(len(rows))) if index is None else index

    def __getitem__(self, column: str) -> _Series:
        return _Series([row[column] for row in self.rows])

    def iterrows(self):
        return iter(zip(self.index, self.rows))

    @property
    def loc(self) -> _Loc:
        return _Loc(self)

    def sort_values(
        self, by: str | list[str], ascending: bool | list[bool] = True
    ) -> _Frame:
        keys = [by] if isinstance(by, str) else list(by)
        orders = (
            [ascending] * len(keys) if isinstance(ascending, bool) else list(ascending)
        )
        pairs = list(zip(self.index, self.rows))
        for key, asc in reversed(list(zip(keys, orders))):  # stable multi-key sort
            pairs.sort(key=lambda pair: pair[1][key], reverse=not asc)
        return _Frame([row for _, row in pairs], [label for label, _ in pairs])


def _make_frame(backend: str, rows: list[dict[str, Any]]):
    if backend == "pandas":
        pd = pytest.importorskip("pandas")
        return pd.DataFrame(rows)
    return _Frame(rows)


def _kept_labels(frame) -> list[Any]:
    return list(frame.index)


# --- the helper under test, taken from the SKILL ----------------------------
def _pareto_front_source(repo_root: Path) -> str:
    text = (repo_root / SKILL).read_text(encoding="utf-8")
    for block in FENCE_RE.findall(text):
        if "def pareto_front(" not in block:
            continue
        tree = ast.parse(block)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "pareto_front":
                return ast.get_source_segment(block, node) or ""
    raise AssertionError(f"{SKILL}: no fenced python block defines pareto_front()")


@pytest.fixture(scope="module")
def pareto_front(repo_root: Path) -> Callable[..., Any]:
    namespace: dict[str, Any] = {"TIE_BAND": 0.0}
    exec(compile(_pareto_front_source(repo_root), str(SKILL), "exec"), namespace)
    return namespace["pareto_front"]


BACKENDS = ["builtin", "pandas"]


@pytest.mark.parametrize("backend", BACKENDS)
def test_repro_keeps_config_beyond_the_band(pareto_front, backend: str) -> None:
    rows = [
        {"model": "strong", "samples_count": 5, "accuracy": 0.90, "cost": 3.0},
        {"model": "mid", "samples_count": 5, "accuracy": 0.86, "cost": 2.0},
        {"model": "cheap", "samples_count": 5, "accuracy": 0.82, "cost": 1.0},
    ]
    frame = _make_frame(backend, rows)
    kept = {rows[i]["model"] for i in _kept_labels(pareto_front(frame, tol=0.05))}
    assert kept == {"cheap", "strong"}, (
        f"strong beats cheap by 8 pp against a 5 pp band and must stay; got {sorted(kept)}"
    )


@pytest.mark.parametrize("backend", BACKENDS)
def test_ladder_does_not_collapse_to_cheapest(pareto_front, backend: str) -> None:
    rows = [
        {"model": f"c{i}", "accuracy": 0.50 + 0.04 * i, "cost": float(i + 1)}
        for i in range(10)
    ]
    kept = [
        rows[i]["model"]
        for i in _kept_labels(pareto_front(_make_frame(backend, rows), tol=0.05))
    ]
    assert kept == ["c0", "c2", "c4", "c6", "c8"]


def _random_rows(rng: random.Random) -> list[dict[str, Any]]:
    n = rng.randint(1, 12)
    return [
        {
            # Coarse grids force duplicate costs and accuracies, the tie cases.
            "accuracy": round(rng.choice([rng.random(), rng.randint(0, 20) / 20]), 4),
            "cost": float(rng.randint(1, 8)),
        }
        for _ in range(n)
    ]


@pytest.mark.parametrize("backend", BACKENDS)
def test_every_dropped_row_is_within_band_of_a_no_costlier_kept_row(
    pareto_front, backend: str
) -> None:
    rng = random.Random(311)
    for _ in range(500):
        rows = _random_rows(rng)
        tol = rng.choice([0.0, 0.02, 0.05, 0.1, 0.25])
        kept = set(_kept_labels(pareto_front(_make_frame(backend, rows), tol=tol)))
        assert kept, "a non-empty frame must keep at least one config"
        for i, row in enumerate(rows):
            if i in kept:
                continue
            assert any(
                rows[k]["cost"] <= row["cost"]
                and rows[k]["accuracy"] >= row["accuracy"] - tol - EPS
                for k in kept
            ), (
                f"tol={tol}: dropped {row} is not within the band of any kept no-costlier row in {rows}"
            )


@pytest.mark.parametrize("backend", BACKENDS)
def test_zero_band_is_strict_pareto(pareto_front, backend: str) -> None:
    rng = random.Random(2000)
    for _ in range(500):
        rows = _random_rows(rng)
        strict = {
            (r["accuracy"], r["cost"])
            for r in rows
            if not any(
                o["accuracy"] >= r["accuracy"]
                and o["cost"] <= r["cost"]
                and (o["accuracy"] > r["accuracy"] or o["cost"] < r["cost"])
                for o in rows
            )
        }
        kept = {
            (rows[i]["accuracy"], rows[i]["cost"])
            for i in _kept_labels(pareto_front(_make_frame(backend, rows), tol=0.0))
        }
        assert kept == strict, f"tol=0 must equal strict Pareto on {rows}"


def test_caveat_states_the_new_guarantee(repo_root: Path) -> None:
    text = " ".join((repo_root / SKILL).read_text(encoding="utf-8").split())
    assert (
        "every dropped config is within your noise of a kept config that costs no more"
        in text
    )
