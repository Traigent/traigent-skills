"""Issue #333: the gold-slice agreement bar must be cleared with confidence.

The protocol let a judge pass the 85% agreement bar "by 5+ points" on a 20-50
example slice, where 90% agreement has a 95% Wilson interval reaching ~70%, and
it chose the judge threshold on the same rows it then reported the bars on. The
fixed text states the pass rule as a Wilson lower bound with worked minimum
counts, a slice floor at which the bar is reachable, and disjoint rows (or
cross-validation) for threshold choice versus bar reporting. The worked counts
in the prose are recomputed here from the skill's own ``wilson_interval``.

Review round 2: the minimums apply to the rows the bars are *reported* on. A
30-row slice split in half leaves 15 reporting rows, where no count clears 85%,
so below about 60 rows the threshold must be calibrated with k-fold
cross-validation (every row scored out-of-fold). Those numbers are recomputed too.
"""

from __future__ import annotations

import re
from pathlib import Path

from .test_audit_326_comparator_case import _python_block, _run_driver

EVAL_AUDIT = (
    Path(__file__).resolve().parents[2] / "skills" / "traigent-eval-audit" / "SKILL.md"
)
TEXT = EVAL_AUDIT.read_text(encoding="utf-8")


def test_margin_rule_is_gone_and_floor_reaches_the_bar() -> None:
    assert "5+ points" not in TEXT
    assert "20-50 example" not in TEXT
    floor = re.search(r"gold slice of at least (\d+) examples", TEXT)
    assert floor and int(floor.group(1)) >= 30, (
        "slice floor must make the 85% bar reachable"
    )
    assert "Wilson lower bound" in TEXT


def test_threshold_choice_and_bar_reporting_use_disjoint_rows() -> None:
    calibration = TEXT.split("## Threshold Calibration", 1)[1].split("\n## ", 1)[0]
    assert "cross-validation" in calibration
    assert "optimistic" in calibration


def test_worked_minimum_counts_match_the_wilson_bound(tmp_path: Path) -> None:
    claims = re.findall(r"(\d+)/(\d+) at n=(\d+)", TEXT)
    assert claims, "the pass rule needs worked minimum-count examples"
    body = f"""
    ns = load_block(sys.argv[1])
    wilson = ns["wilson_interval"]
    minimums = {{}}
    for n in (20, 30, 50, 100):
        passing = [k for k in range(n + 1) if wilson(k, n)[0] >= 0.85]
        minimums[n] = passing[0] if passing else None
    emit({{"minimums": minimums, "claims": {[list(map(int, c)) for c in claims]!r}}})
    """
    result = _run_driver(
        tmp_path, _python_block(EVAL_AUDIT, "def wilson_interval"), body
    )
    minimums = {int(n): k for n, k in result["minimums"].items()}
    assert minimums[20] is None, minimums
    for k, n, n_again in result["claims"]:
        assert n == n_again
        assert minimums[n] == k, (k, n, minimums)


def test_minimums_apply_to_reporting_rows_and_kfold_below_sixty(
    tmp_path: Path,
) -> None:
    assert "computed on the **reporting rows**" in TEXT
    kfold = re.search(r"Below about (\d+) gold rows, use k-fold cross-validation", TEXT)
    assert kfold, "k-fold must be the rule below a stated slice size"
    split_floor = re.search(r"keeping at least (\d+) reporting rows", TEXT)
    assert split_floor, "a split must keep a stated number of reporting rows"
    unreachable = re.search(r"Below (\d+) reporting rows it cannot be cleared", TEXT)
    assert unreachable
    lower_claims = re.findall(r"(\d+)/(\d+) has a lower bound of ([\d.]+)%", TEXT)
    split_claims = re.findall(
        r"(\d+)-row slice split in half leaves (\d+) reporting rows, where even (\d+)/(\d+) cannot clear",
        TEXT,
    )
    assert lower_claims and split_claims
    body = f"""
    ns = load_block(sys.argv[1])
    wilson = ns["wilson_interval"]
    emit({{
        "smallest_clearing_n": next(n for n in range(1, 500) if wilson(n, n)[0] >= 0.85),
        "lower": {{f"{{k}}/{{n}}": round(100 * wilson(int(k), int(n))[0], 1) for k, n, _ in {lower_claims!r}}},
        "split_clears": [wilson(int(k), int(n))[0] >= 0.85 for *_, k, n in {split_claims!r}],
    }})
    """
    result = _run_driver(
        tmp_path, _python_block(EVAL_AUDIT, "def wilson_interval"), body
    )
    assert int(unreachable.group(1)) == result["smallest_clearing_n"], result
    for k, n, stated in lower_claims:
        assert result["lower"][f"{k}/{n}"] == float(stated), (k, n, stated, result)
    for size, rows, k, n in split_claims:
        assert int(size) // 2 == int(rows) == int(k) == int(n)
    assert result["split_clears"] == [False] * len(split_claims), result
    # A 50/50 split below the k-fold threshold would leave fewer reporting rows
    # than the split rule's own floor, so the two rules cannot contradict.
    assert int(kfold.group(1)) // 2 >= int(split_floor.group(1)), (
        kfold.group(0),
        split_floor.group(0),
    )
    assert int(split_floor.group(1)) >= result["smallest_clearing_n"]
