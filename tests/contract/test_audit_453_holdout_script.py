"""Issue #453: the reference holdout script must run on the inputs the page prescribes.

``references/gate-workflow.md`` says ``configs/candidate.json`` is the
``export_config(...)`` artifact, and the datasets the other skills teach key the
label ``output``. The script read the artifact as if it were a flat config
(``KeyError`` on the first knob) and read ``example["expected_output"]``
(``KeyError`` on the first row). The PR job ran ``--mode mock``, which returned
canned values without touching either -- green PR, crashing nightly gate.

This test extracts the script from the page and runs it, so the page stays
executable rather than merely plausible. It is text + stdlib only: no SDK, no
provider, no network.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from .test_audit_349_fenced_blocks import skip_unless_current_released_sdk

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "skills" / "traigent-ci-safety-gate" / "references" / "gate-workflow.md"

# The real export_config(...) wrapper on SDK 0.30.0 (core/config_state_manager.py,
# _create_slim_export): the knobs live under "config", never at the top level.
EXPORT_ARTIFACT = {
    "config": {"style": "upper", "temperature": 0.0},
    "function_name": "agent",
    "exported_at": "2026-10-21T00:00:00+00:00",
    "traigent_version": "0.30.0",
    "metrics": {"accuracy": 0.9},
}
# include_metadata=False writes a bare wrapper with no "exported_at".
BARE_ARTIFACT = {"config": {"style": "upper"}}


def _script_source() -> str:
    text = PAGE.read_text(encoding="utf-8")
    marker = "Save this as `scripts/run_holdout_eval.py`"
    assert marker in text, "gate-workflow.md lost its holdout-script section"
    after = text.split(marker, 1)[1]
    opened = after.split("```python", 1)
    assert len(opened) == 2, "the holdout script is no longer a ```python block"
    return opened[1].split("```", 1)[0]


def _write_script(tmp_path: Path, agent_returns: object = "HELLO") -> Path:
    source = _script_source()
    assert "run_my_agent(" in source, "the script no longer calls the user's adapter"
    # Supply the one project-specific hook the page tells the reader to adapt.
    stub = (
        "\n\ndef run_my_agent(value, config):\n"
        "    assert isinstance(config, dict) and 'style' in config, config\n"
        f"    return {agent_returns!r}, 0.001\n\n"
    )
    script = tmp_path / "run_holdout_eval.py"
    script.write_text(source.replace("\ndef main()", stub + "\ndef main()", 1), encoding="utf-8")
    return script


def _run(script: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=120,
    )


def _holdout(tmp_path: Path, rows: list[dict], name: str = "holdout.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _config(tmp_path: Path, doc: object, name: str = "candidate.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_real_mode_runs_on_an_unmodified_export_artifact_and_output_rows(
    tmp_path: Path,
) -> None:
    script = _write_script(tmp_path)
    config = _config(tmp_path, EXPORT_ARTIFACT)
    holdout = _holdout(tmp_path, [{"input": "hello", "output": "HELLO"}])
    out = tmp_path / "result.json"
    proc = _run(
        script,
        tmp_path,
        "--config", str(config),
        "--holdout", str(holdout),
        "--output", str(out),
        "--mode", "real",
    )
    assert proc.returncode == 0, proc.stderr
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["metrics"]["accuracy"] == [1.0]
    assert written["total_cost"] > 0


def test_real_mode_accepts_a_flat_config_and_the_bare_wrapper(tmp_path: Path) -> None:
    script = _write_script(tmp_path)
    holdout = _holdout(tmp_path, [{"input": "hello", "output": "HELLO"}])
    for label, doc in (("bare-wrapper", BARE_ARTIFACT), ("flat", {"style": "upper"})):
        out = tmp_path / f"{label}.json"
        proc = _run(
            script,
            tmp_path,
            "--config", str(_config(tmp_path, doc, f"{label}.json")),
            "--holdout", str(holdout),
            "--output", str(out),
            "--mode", "real",
        )
        assert proc.returncode == 0, f"{label}: {proc.stderr}"


@pytest.mark.parametrize(
    "label",
    ["expected_output", "expected", "answer", "target", "label"],
)
def test_other_sdk_label_keys_keep_working(tmp_path: Path, label: str) -> None:
    script = _write_script(tmp_path)
    out = tmp_path / f"{label}.json"
    proc = _run(
        script,
        tmp_path,
        "--config", str(_config(tmp_path, EXPORT_ARTIFACT)),
        "--holdout", str(_holdout(tmp_path, [{"input": "hello", label: "HELLO"}], f"{label}.jsonl")),
        "--output", str(out),
        "--mode", "real",
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["metrics"]["accuracy"] == [1.0]


def test_mock_mode_fails_on_a_config_that_is_not_an_object(tmp_path: Path) -> None:
    script = _write_script(tmp_path)
    proc = _run(
        script,
        tmp_path,
        "--config", str(_config(tmp_path, ["style"], "list.json")),
        "--holdout", str(_holdout(tmp_path, [{"input": "hello", "output": "HELLO"}])),
        "--output", str(tmp_path / "list-out.json"),
        "--mode", "mock",
    )
    assert proc.returncode != 0, (
        "mock mode passed on a non-object config -- the PR wiring job cannot catch "
        "a bad config shape"
    )


@pytest.mark.parametrize("doc", [{}, {"config": {}}], ids=["empty-flat", "empty-wrapper"])
def test_an_empty_config_is_accepted(tmp_path: Path, doc: object) -> None:
    """A pinned incumbent may legitimately mean "the agent's own defaults".

    tests/contract/test_gate_workflow.py passes `{}` for exactly this reason;
    refusing it here would break the repo's existing contract for this script.
    """
    script = _write_script(tmp_path)
    proc = _run(
        script,
        tmp_path,
        "--config", str(_config(tmp_path, doc, "empty.json")),
        "--holdout", str(_holdout(tmp_path, [{"input": "hello", "output": "HELLO"}])),
        "--output", str(tmp_path / "empty-out.json"),
        "--mode", "mock",
    )
    assert proc.returncode == 0, proc.stderr


def test_mock_mode_fails_on_a_row_with_no_recognised_label(tmp_path: Path) -> None:
    script = _write_script(tmp_path)
    proc = _run(
        script,
        tmp_path,
        "--config", str(_config(tmp_path, EXPORT_ARTIFACT)),
        "--holdout", str(_holdout(tmp_path, [{"input": "hello", "gold": "HELLO"}])),
        "--output", str(tmp_path / "out.json"),
        "--mode", "mock",
    )
    assert proc.returncode != 0, (
        "mock mode passed on an unlabelled holdout row -- the PR wiring job cannot "
        "catch a bad label key"
    )


@pytest.mark.parametrize(
    ("returns", "label", "score"),
    [
        ("{'a': 1}", {"a": 1}, 0.0),   # a string output never equals a dict label
        ("MATCH", {"a": 1}, 0.0),
        (None, None, 1.0),             # equal non-strings score 1.0
        # Both sides strings: the case-folding/trimming branch. Without this the
        # whole suite stays green if `matches()` degrades to `output == expected`
        # -- every other string case here is already an exact match.
        (" hello ", "HELLO", 1.0),
        ("goodbye", "HELLO", 0.0),
    ],
    ids=[
        "dict-label-string-output",
        "dict-label-mismatch",
        "equal-non-strings",
        "string-case-and-whitespace-folded",
        "string-mismatch",
    ],
)
def test_non_string_labels_compare_by_equality(
    tmp_path: Path, returns: object, label: object, score: float
) -> None:
    """A dict/list label must not crash on ``.strip()`` -- and the positive case
    must be reachable, or the test would pass on a matcher that always returns 0."""
    script = _write_script(tmp_path, agent_returns=returns)
    out = tmp_path / f"{score}-out.json"
    proc = _run(
        script,
        tmp_path,
        "--config", str(_config(tmp_path, EXPORT_ARTIFACT)),
        "--holdout", str(_holdout(tmp_path, [{"input": "hello", "output": label}], f"{score}.jsonl")),
        "--output", str(out),
        "--mode", "real",
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["metrics"]["accuracy"] == [score]


def _documented_tuple(name: str) -> tuple[str, ...]:
    """Parse a module-level tuple literal out of the extracted script.

    Reading it from the page is the point: comparing the SDK against a literal
    re-typed in this file would let the page drift while the test stayed green.
    """
    match = re.search(rf"^{re.escape(name)} = \(([^)]*)\)", _script_source(), re.M)
    assert match, f"the reference script no longer defines {name}"
    return tuple(ast.literal_eval(f"({match.group(1)})"))


def test_the_sdk_label_precedence_matches_the_script(
    sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(
        sync_map, sdk_version_label, "the holdout script's label precedence"
    )
    base = pytest.importorskip("traigent.evaluators.base")
    assert _documented_tuple("_EXPECTED_OUTPUT_FIELDS") == base._EXPECTED_OUTPUT_FIELDS, (
        "the reference script's label precedence no longer matches the SDK's "
        f"_EXPECTED_OUTPUT_FIELDS; update {PAGE.relative_to(ROOT)}"
    )


def test_the_script_input_precedence_matches_the_sdk(
    tmp_path: Path, sync_map: dict, sdk_version_label: str
) -> None:
    """The SDK takes `input`, else `input_data` -- asserted by loading rows.

    Comparing the page's tuple to a literal retyped here would be the test
    agreeing with itself; the SDK has to be the other side of the comparison.
    """
    skip_unless_current_released_sdk(
        sync_map, sdk_version_label, "the holdout script's input precedence"
    )
    base = pytest.importorskip("traigent.evaluators.base")
    documented = _documented_tuple("_INPUT_FIELDS")

    previous = os.environ.get("TRAIGENT_DATASET_ROOT")
    os.environ["TRAIGENT_DATASET_ROOT"] = str(tmp_path)
    try:
        # Every key the script claims to read must load; the first must win.
        for key in documented:
            path = tmp_path / f"{key}.jsonl"
            path.write_text(json.dumps({key: "q", "output": "a"}) + "\n", encoding="utf-8")
            example = base.Dataset.from_jsonl(str(path)).examples[0]
            assert example.input_data == "q", f"the SDK no longer reads {key!r}"
        both = tmp_path / "both.jsonl"
        both.write_text(
            json.dumps({documented[0]: "first", documented[1]: "second", "output": "a"}) + "\n",
            encoding="utf-8",
        )
        winner = base.Dataset.from_jsonl(str(both)).examples[0].input_data
    finally:
        if previous is None:
            os.environ.pop("TRAIGENT_DATASET_ROOT", None)
        else:
            os.environ["TRAIGENT_DATASET_ROOT"] = previous
    assert winner == "first", (
        f"the SDK's input precedence changed: with both keys present it read "
        f"{winner!r}, so the script's {documented} order is wrong"
    )


def test_a_full_format_export_is_not_silently_passed_through(tmp_path: Path) -> None:
    """`export_config(format="full")` adds keys the slim wrapper does not have.

    Treating it as a flat config hands the agent the envelope and applies none
    of the tuned knobs, while the gate still emits a promotion decision -- the
    original #453 defect in a new shape.
    """
    script = _write_script(tmp_path)
    full = dict(EXPORT_ARTIFACT, trials=[], optimization={}, configuration_space={})
    proc = _run(
        script,
        tmp_path,
        "--config", str(_config(tmp_path, full, "full.json")),
        "--holdout", str(_holdout(tmp_path, [{"input": "hello", "output": "HELLO"}])),
        "--output", str(tmp_path / "full-out.json"),
        "--mode", "real",
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads((tmp_path / "full-out.json").read_text(encoding="utf-8"))[
        "metrics"
    ]["accuracy"] == [1.0], "the full-format wrapper was not unwrapped"


@pytest.mark.parametrize(
    ("label", "doc"),
    [
        ("unrecognised-key", dict(EXPORT_ARTIFACT, some_future_key=1)),
        ("config-absent", {k: v for k, v in EXPORT_ARTIFACT.items() if k != "config"}),
        ("config-null", dict(EXPORT_ARTIFACT, config=None)),
        ("config-not-a-mapping", dict(EXPORT_ARTIFACT, config=[1, 2])),
        (
            "config-renamed",
            {
                **{k: v for k, v in EXPORT_ARTIFACT.items() if k != "config"},
                "best_config": {"style": "upper"},
            },
        ),
    ],
)
def test_a_wrapper_the_script_cannot_read_fails_closed(
    tmp_path: Path, label: str, doc: dict
) -> None:
    """Deciding wrapper-ness by a marker, not by a readable `config`.

    Keying the unwrap on `config` alone let a wrapper whose config key was
    absent, null or renamed fall through as a flat config: the agent was handed
    the envelope, applied no knob, and the gate still emitted a decision.
    """
    script = _write_script(tmp_path)
    proc = _run(
        script,
        tmp_path,
        "--config", str(_config(tmp_path, doc, f"{label}.json")),
        "--holdout", str(_holdout(tmp_path, [{"input": "hello", "output": "HELLO"}])),
        "--output", str(tmp_path / f"{label}-out.json"),
        "--mode", "mock",
    )
    assert proc.returncode != 0, (
        f"a {label} wrapper was guessed at instead of refused; the agent would "
        "have received the envelope"
    )
    assert not (tmp_path / f"{label}-out.json").exists()


def test_input_data_rows_are_accepted(tmp_path: Path) -> None:
    """`traigent-dataset-curate` tells readers `input` or `input_data`."""
    script = _write_script(tmp_path)
    for mode in ("mock", "real"):
        out = tmp_path / f"{mode}-input-data.json"
        proc = _run(
            script,
            tmp_path,
            "--config", str(_config(tmp_path, EXPORT_ARTIFACT)),
            "--holdout", str(_holdout(tmp_path, [{"input_data": "hello", "output": "HELLO"}], f"{mode}-id.jsonl")),
            "--output", str(out),
            "--mode", mode,
        )
        assert proc.returncode == 0, f"{mode}: {proc.stderr}"
