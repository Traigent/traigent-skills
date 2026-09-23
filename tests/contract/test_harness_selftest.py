from __future__ import annotations

from pathlib import Path

import pytest

from .extract import collect_file, collect_runnable_file
from .facts import ContractFact
from .verifier import verify_python_fact


def test_extractor_detects_imports_symbols_and_kwargs(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        """# Demo

```python
import traigent as tg
from traigent.api.decorators import EvaluationOptions

@tg.optimize(eval_dataset="eval.jsonl", objectives=["accuracy"])
def f(x):
    return x

opts = EvaluationOptions(eval_dataset="eval.jsonl")
```
""",
        encoding="utf-8",
    )

    facts = collect_file("demo", path)
    assert (
        ContractFact(kind="import", skill="demo", path=path, line=4, module="traigent")
        in facts
    )
    assert (
        ContractFact(
            kind="symbol",
            skill="demo",
            path=path,
            line=5,
            module="traigent.api.decorators",
            symbol="EvaluationOptions",
        )
        in facts
    )
    assert any(
        fact.kind == "call_kwargs" and fact.target == "traigent.optimize"
        for fact in facts
    )
    assert any(
        fact.kind == "call_kwargs"
        and fact.target == "traigent.api.decorators.EvaluationOptions"
        for fact in facts
    )


def test_extractor_detects_opt_in_runnable_python_blocks(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        """# Demo

```python runnable
print("runs")
```

```python
print("static only")
```
""",
        encoding="utf-8",
    )

    snippets = collect_runnable_file("demo", path)
    assert len(snippets) == 1
    assert snippets[0].language == "python"
    assert snippets[0].start_line == 4
    assert snippets[0].text == 'print("runs")'


def test_extractor_detects_backend_url_facts(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        """# Demo

Use `POST /api/v1/datasets/generate` to generate a dataset.

```text
GET /sessions/123/results
```
""",
        encoding="utf-8",
    )

    facts = collect_file("demo", path)
    assert (
        ContractFact(
            kind="url",
            skill="demo",
            path=path,
            line=3,
            url="/api/v1/datasets/generate",
            method="POST",
        )
        in facts
    )
    assert (
        ContractFact(
            kind="url",
            skill="demo",
            path=path,
            line=6,
            url="/sessions/123/results",
            method="GET",
        )
        in facts
    )


def test_extractor_detects_newer_backend_url_families(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        """# Demo

Use `GET /api/v1/experiment-groups/42` and `POST /api/v1/optimization/plan`.

```text
GET /api/v1/keys
GET /api/v1/best-configs/7
POST /api/v1/auth/login
GET /api/v1beta/projects/p1/prompts
```

The `/authoring/page` path is not a backend route family.
""",
        encoding="utf-8",
    )

    facts = collect_file("demo", path)
    urls = {(fact.method, fact.url) for fact in facts if fact.kind == "url"}
    assert ("GET", "/api/v1/experiment-groups/42") in urls
    assert ("POST", "/api/v1/optimization/plan") in urls
    assert ("GET", "/api/v1/keys") in urls
    assert ("GET", "/api/v1/best-configs/7") in urls
    assert ("POST", "/api/v1/auth/login") in urls
    assert ("GET", "/api/v1beta/projects/p1/prompts") in urls
    assert not any(url.startswith("/authoring") for _, url in urls)


def test_extractor_honors_contract_skip(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        """```python
# contract: skip
from traigent.nope import Missing
```
""",
        encoding="utf-8",
    )
    assert collect_file("demo", path) == []


def test_extractor_regex_fallback_on_syntax_error(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        """```python
from traigent.future import Thing
this is not valid python [
```
""",
        encoding="utf-8",
    )
    facts = collect_file("demo", path)
    assert (
        ContractFact(
            kind="import", skill="demo", path=path, line=2, module="traigent.future"
        )
        in facts
    )
    assert (
        ContractFact(
            kind="symbol",
            skill="demo",
            path=path,
            line=2,
            module="traigent.future",
            symbol="Thing",
        )
        in facts
    )


def test_dead_teaching_message_contains_location_and_fix_menu() -> None:
    fact = ContractFact(
        kind="import",
        skill="demo",
        path=Path("skills/demo/SKILL.md"),
        line=7,
        module="traigent.nope",
    )
    with pytest.raises(AssertionError) as exc_info:
        verify_python_fact(fact, repo_root=None, sdk_version="0.12.0")

    message = str(exc_info.value)
    assert "DEAD TEACHING  skills/demo/SKILL.md:7" in message
    assert (
        "fix one : (a) raise this skill's min_sdk_version in sync_map.yml AND add"
        in message
    )
    assert (
        "(b) replace the taught API with one available at the declared floor" in message
    )
    assert (
        "(c) mark the block `# contract: skip` ONLY if it is illustrative pseudo-code"
        in message
    )


def test_cli_flag_regex_extracts_long_options() -> None:
    from .test_env_and_cli import _FLAG_RE

    cmd = "traigent validate --dataset eval.jsonl -v --objectives accuracy --help"
    assert _FLAG_RE.findall(cmd) == ["--dataset", "--objectives", "--help"]


def test_env_and_cli_dedupe_is_per_skill(tmp_path) -> None:
    from .facts import collect_contract_facts

    for skill in ("skill-a", "skill-b"):
        d = tmp_path / "skills" / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            "Set `TRAIGENT_DEBUG=1`.\n```bash\ntraigent validate x.jsonl\n```\n"
        )
    facts = collect_contract_facts(str(tmp_path))
    env_facts = [f for f in facts if f.kind == "env"]
    cli_facts = [f for f in facts if f.kind == "cli"]
    assert {f.skill for f in env_facts} == {"skill-a", "skill-b"}
    assert {f.skill for f in cli_facts} == {"skill-a", "skill-b"}


_PLANTED_KWARG_TYPOS = """# Demo

```python
import traigent
from traigent import Choices, Range
from traigent.generation import DatasetGrowthOptions

RETRIES = 3

@traigent.optimize(
    objectives=["accuracy"],
    model=Choices(["gpt-4o-mini", "gpt-4o"]),
    temperature=Range.temperature(),
    top_p=traigent.Range(0.1, 1.0),
    seed_window=(0, 10),
    max_trails=10,
    retries_per_trail=RETRIES,
)
def f(x):
    return x

growth_options = DatasetGrowthOptions(
    max_rounds=3,
)
```
"""


def _planted_kwarg_facts(tmp_path: Path) -> dict[str, ContractFact]:
    path = tmp_path / "SKILL.md"
    path.write_text(_PLANTED_KWARG_TYPOS, encoding="utf-8")
    facts = [fact for fact in collect_file("demo", path) if fact.kind == "call_kwargs"]
    return {fact.target or "": fact for fact in facts}


def test_optimize_inline_tuned_variables_are_not_kwarg_facts(tmp_path: Path) -> None:
    # Inline tuned variables are free-form names, so they are not facts. A list
    # still is one: the SDK rejects `x=[1, 2]` as an unknown keyword on purpose.
    # A name bound to a plain value (RETRIES = 3) is still checked.
    facts = _planted_kwarg_facts(tmp_path)
    assert facts["traigent.optimize"].kwargs == (
        "objectives",
        "max_trails",
        "retries_per_trail",
    )


# SDK-valid tuned-variable shapes the extractor must not report: the SDK decides
# from the runtime value, so indirection through a name or an import alias must
# not turn a correct knob into "kwarg not accepted".
_MUST_ACCEPT_SHAPES = {
    "name bound to a range": (
        "from traigent import Choices\n"
        'MODELS = Choices(["gpt-4o-mini", "gpt-4o"])\n',
        "model=MODELS",
    ),
    "aliased range import": (
        "from traigent import Choices as C\n",
        'model=C(["gpt-4o-mini", "gpt-4o"])',
    ),
    "tuple of bound numbers": (
        "LO, HI = 0.0, 1.0\n",
        "temperature=(LO, HI)",
    ),
}


@pytest.mark.parametrize("shape", sorted(_MUST_ACCEPT_SHAPES))
def test_sdk_valid_inline_tuned_variable_shapes_pass_the_kwargs_gate(
    tmp_path: Path, shape: str
) -> None:
    pytest.importorskip("traigent")
    prelude, knob = _MUST_ACCEPT_SHAPES[shape]
    path = tmp_path / "SKILL.md"
    path.write_text(
        "```python\nimport traigent\n"
        + prelude
        + f'\n@traigent.optimize(objectives=["accuracy"], {knob})\n'
        + "def f(x):\n    return x\n```\n",
        encoding="utf-8",
    )
    facts = [
        fact
        for fact in collect_file("demo", path)
        if fact.kind == "call_kwargs" and fact.target == "traigent.optimize"
    ]
    assert [fact.kwargs for fact in facts] == [("objectives",)]
    verify_python_fact(facts[0], repo_root=None, sdk_version="installed")


@pytest.mark.parametrize(
    ("target", "typo"),
    [
        ("traigent.optimize", "max_trails"),
        ("traigent.generation.DatasetGrowthOptions", "max_rounds"),
    ],
)
def test_misspelled_kwarg_on_a_closed_kwargs_target_is_dead_teaching(
    tmp_path: Path, target: str, typo: str
) -> None:
    # Both targets take **kwargs yet reject unknown names at runtime, so a
    # misspelled keyword must fail the contract instead of being skipped.
    pytest.importorskip("traigent")
    fact = _planted_kwarg_facts(tmp_path)[target]
    try:
        with pytest.raises(AssertionError, match=f"kwarg not accepted: {typo}"):
            verify_python_fact(fact, repo_root=None, sdk_version="installed")
    except pytest.skip.Exception as exc:
        pytest.fail(f"the kwargs gate skipped {target} instead of checking it: {exc}")
