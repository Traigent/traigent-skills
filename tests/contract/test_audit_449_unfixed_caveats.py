"""Issue #449: run the two unfixed facts, so a release that fixes one goes red.

``test_audit_449_unfixed_caveat_bounds.py`` already keeps the *prose* honest: no
caveat may carry a stale ``<= 0.27.0`` bound, and each must name the checked
range. What it cannot do is notice that the underlying behaviour changed -- the
exact gap that let 0.28.0, 0.29.0 and 0.30.0 ship while five sentences went on
saying the problems were bounded to 0.27.0.

This module closes that gap by executing both facts on the released bucket:

* **mock-standalone-litellm** — ``enable_mock_mode_for_quickstart()`` does not
  intercept a standalone ``litellm.completion`` call. The caveat is a spend and
  data-egress guard: a reader who believes it is fixed runs the synthesis
  snippet "in mock mode", makes real billable calls, and sends seed rows to the
  provider.
* **base-evaluator-wiring** — a ``BaseEvaluator`` instance passed as
  ``custom_evaluator=`` is still rejected.

Both probes are offline and keyless. The litellm probe is aimed at a closed
loopback port, so the assertion is "the call left the mock", never a provider
request. When a release fixes either one, the matching test fails and the
caveat has to be restated with the real version.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from .test_audit_349_fenced_blocks import skip_unless_current_released_sdk

_MOCK_PROBE = '''
import sys
import litellm
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()
try:
    litellm.completion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        # Port 9 (discard) is closed: the request cannot leave this machine, and
        # the refusal proves the call was NOT served from the mock.
        api_base="http://127.0.0.1:9/v1",
        num_retries=0,
        timeout=5,
    )
except BaseException as exc:
    print("ESCAPED_MOCK", type(exc).__name__)
    sys.exit(0)
print("INTERCEPTED")
sys.exit(0)
'''


def test_mock_mode_still_misses_a_standalone_litellm_call(
    tmp_path: Path, sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(sync_map, sdk_version_label, "the #449 caveats")
    pytest.importorskip("litellm")
    pytest.importorskip("traigent.testing")

    # A subprocess, not this one: enable_mock_mode_for_quickstart() patches
    # litellm globally and has no documented undo, so running it in-process
    # would leak mock interception into every later test in the session.
    probe = tmp_path / "mock_probe.py"
    probe.write_text(_MOCK_PROBE, encoding="utf-8")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("OPENAI_", "ANTHROPIC_", "TRAIGENT_"))
    }
    env.update(
        # Any non-empty value works; deliberately NOT `sk-`-prefixed so this line
        # is not a credential shape for a secret scanner to flag. The request
        # cannot leave the machine either way (the probe points at a closed port).
        OPENAI_API_KEY="placeholder-not-a-real-key",
        TRAIGENT_OFFLINE_MODE="true",
        LITELLM_LOCAL_MODEL_COST_MAP="True",
    )
    proc = subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "ESCAPED_MOCK" in proc.stdout, (
        "mock mode now intercepts a standalone litellm.completion call -- the "
        "skills' spend/egress caveat says it does not; restate it with the "
        f"release that fixed it. probe output: {proc.stdout!r}"
    )


def test_base_evaluator_is_still_not_wireable(
    sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(sync_map, sdk_version_label, "the #449 caveats")
    base = pytest.importorskip("traigent.evaluators.base")
    decorators = pytest.importorskip("traigent.api.decorators")

    class _Evaluator(base.BaseEvaluator):
        async def evaluate(self, func, config, dataset, **kwargs):  # pragma: no cover
            raise NotImplementedError

    with pytest.raises(Exception) as excinfo:  # noqa: PT011 - pydantic ValidationError
        decorators.EvaluationOptions(
            eval_dataset="d.jsonl", custom_evaluator=_Evaluator()
        )
    assert "callable" in str(excinfo.value).lower(), (
        "EvaluationOptions now accepts a BaseEvaluator instance — the skills say it "
        f"does not; restate the caveat with the fixing release: {excinfo.value}"
    )
