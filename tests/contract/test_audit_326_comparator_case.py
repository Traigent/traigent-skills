"""Issue #326: eval-build comparators must match the SDK's case-insensitive accuracy.

The SDK's built-in ``accuracy`` trims whitespace and ignores letter case. A
copied Tier 2 or Tier 4 comparator that only strips whitespace scores a correct
``Paris`` against gold ``paris`` as 0.0, so moving up the ladder silently
tightens the metric. Two gates:

* a lint over every file under ``skills/``: an ``==`` comparison with
  ``strip()`` on both sides must lower-case BOTH sides of the ``==`` (or say on the same line that it is
  case-sensitive on purpose);
* the Tier 2 and Tier 4 blocks of ``traigent-eval-build/SKILL.md`` are executed
  end to end in offline mode with a canned ``Paris`` reply and must report
  ``accuracy == 1.0``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from .test_runnable_snippets import _offline_mock_env

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_BUILD = REPO_ROOT / "skills" / "traigent-eval-build" / "SKILL.md"
FENCE_RE = re.compile(r"^```python[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)

# Shared driver prelude: routes every litellm.completion call to litellm's own
# offline ``mock_response`` (a real ModelResponse, no network, no key) and
# executes one fenced template block with its ``eval/`` paths rooted in cwd.
DRIVER_PRELUDE = textwrap.dedent(
    """
    import json
    import sys
    from pathlib import Path

    import litellm

    _REAL_COMPLETION = litellm.completion
    CALLS = []

    def install_replies(reply_fn):
        def fake_completion(*args, **kwargs):
            requested = kwargs.get("model")
            CALLS.append(requested)
            kwargs["model"] = "gpt-4o-mini"
            kwargs["mock_response"] = reply_fn(requested, kwargs.get("messages") or [])
            return _REAL_COMPLETION(*args, **kwargs)

        litellm.completion = fake_completion

    def load_block(path_text):
        source = Path(path_text).read_text(encoding="utf-8")
        source = source.replace('"eval/', '"' + str(Path.cwd() / "eval") + "/")
        namespace = {"__name__": "template_under_test"}
        exec(compile(source, "template_under_test", "exec"), namespace)
        return namespace

    def write_rows(name, rows):
        path = Path("eval") / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\\n" for row in rows), encoding="utf-8")

    def emit(result):
        print("RESULT " + json.dumps(result, default=str))
    """
)


def _python_block(path: Path, marker: str) -> str:
    blocks = [
        b for b in FENCE_RE.findall(path.read_text(encoding="utf-8")) if marker in b
    ]
    assert len(blocks) == 1, (
        f"{path.name}: expected one python block containing {marker!r}, found {len(blocks)}"
    )
    return blocks[0]


def _run_driver(tmp_path: Path, block: str, body: str) -> dict:
    (tmp_path / "block.py").write_text(block, encoding="utf-8")
    (tmp_path / "driver.py").write_text(
        DRIVER_PRELUDE + textwrap.dedent(body), encoding="utf-8"
    )
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = _offline_mock_env()
    env["HOME"] = str(home)
    completed = subprocess.run(
        [sys.executable, "driver.py", "block.py"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    results = [
        line[len("RESULT ") :]
        for line in completed.stdout.splitlines()
        if line.startswith("RESULT ")
    ]
    assert completed.returncode == 0 and results, (
        f"driver failed (exit {completed.returncode})\nstdout:\n{completed.stdout[-4000:]}\nstderr:\n{completed.stderr[-4000:]}"
    )
    return json.loads(results[-1])


def _case_sensitive_comparators(skills_root: Path) -> list[str]:
    """Guidance lines that compare with strip() on both sides but miss lower().

    Scans customer guidance only. A skill's own ``tests/`` tree is test data
    (fixtures may be case-sensitive on purpose) and is skipped.
    """
    offenders = []
    for path in sorted(skills_root.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".py"}:
            continue
        relative = path.relative_to(skills_root)
        if len(relative.parts) > 1 and relative.parts[1] == "tests":
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            left, _, right = line.partition("==")
            is_strip_comparator = "strip()" in left and "strip()" in right
            if not is_strip_comparator or "case-sensitive" in line:
                continue
            if "lower()" not in left or "lower()" not in right:
                offenders.append(f"{relative}:{number}: {line.strip()}")
    return offenders


def test_no_case_sensitive_strip_comparator_under_skills() -> None:
    offenders = _case_sensitive_comparators(REPO_ROOT / "skills")
    assert not offenders, (
        "comparators must match the SDK's case-insensitive accuracy "
        "(`.strip().lower()` on both sides), or say `case-sensitive` on the same line:\n"
        + "\n".join(offenders)
    )


def test_comparator_lint_scans_guidance_not_skill_tests(tmp_path: Path) -> None:
    offending = "    return 1.0 if output.strip() == expected.strip() else 0.0\n"
    skill = tmp_path / "skills" / "demo-skill"
    (skill / "references").mkdir(parents=True)
    (skill / "tests" / "fixtures").mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"```python\n{offending}```\n", encoding="utf-8")
    (skill / "references" / "guide.md").write_text(offending, encoding="utf-8")
    (skill / "tests" / "test_demo.py").write_text(offending, encoding="utf-8")
    (skill / "tests" / "fixtures" / "scorer.py").write_text(offending, encoding="utf-8")
    offenders = _case_sensitive_comparators(tmp_path / "skills")
    assert [line.split(":", 1)[0] for line in offenders] == [
        "demo-skill/SKILL.md",
        "demo-skill/references/guide.md",
    ], offenders


RUN_TIER = """
# Reply and golds differ in case on both sides, so a comparator that lower-cases
# only one side of the == still scores some rows 0.0.
install_replies(lambda model, messages: " PARIS ")
write_rows("qa.jsonl", [{"input": {"question": f"Capital of France? ({i})"}, "output": ["paris", "Paris"][i % 2]} for i in range(4)])
ns = load_block(sys.argv[1])
result = ns["answer"].optimize_sync(algorithm="grid", max_trials=2)
emit({"accuracy": [t.metrics.get("accuracy") for t in result.trials], "status": [str(t.status) for t in result.trials]})
"""


def test_tier2_scoring_function_accepts_case_variant(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path, _python_block(EVAL_BUILD, "def exact_match_score"), RUN_TIER
    )
    assert result["accuracy"] and all(value == 1.0 for value in result["accuracy"]), (
        result
    )


def test_tier4_custom_evaluator_accepts_case_variant(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path, _python_block(EVAL_BUILD, "def evaluate_answer"), RUN_TIER
    )
    assert result["accuracy"] and all(value == 1.0 for value in result["accuracy"]), (
        result
    )
