"""Issue #445: ``mode="auto"`` is sequential unless a concurrency above 1 is set."""

from __future__ import annotations

from pathlib import Path

import pytest

DOC = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "traigent-optimize-run"
    / "references"
    / "parallel-config.md"
)


def test_doc_describes_the_real_auto_rule() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "Traigent decides based on" not in text
    assert "lets Traigent decide" not in text
    assert "trial_concurrency > 1" in text and "otherwise it runs sequentially" in text
    assert "ParallelConfig(trial_concurrency=4)" in text


def test_sdk_auto_without_concurrency_is_sequential() -> None:
    parallel = pytest.importorskip("traigent.config.parallel")
    kwargs = {"default_thread_workers": 8, "config_space_size": 50, "detected_function_kind": "sync"}
    plain = parallel.resolve_parallel_config(parallel.ParallelConfig(mode="auto"), **kwargs)
    assert plain.mode == "sequential"
    assert plain.trial_concurrency == 1
    wide = parallel.resolve_parallel_config(
        parallel.ParallelConfig(mode="auto", trial_concurrency=4), **kwargs
    )
    assert wide.mode == "parallel"
