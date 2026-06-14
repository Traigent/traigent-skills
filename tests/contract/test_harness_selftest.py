from __future__ import annotations

from pathlib import Path

import pytest

from .extract import collect_file
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
    assert ContractFact(kind="import", skill="demo", path=path, line=4, module="traigent") in facts
    assert ContractFact(
        kind="symbol",
        skill="demo",
        path=path,
        line=5,
        module="traigent.api.decorators",
        symbol="EvaluationOptions",
    ) in facts
    assert any(fact.kind == "call_kwargs" and fact.target == "traigent.optimize" for fact in facts)
    assert any(
        fact.kind == "call_kwargs" and fact.target == "traigent.api.decorators.EvaluationOptions" for fact in facts
    )


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
    assert ContractFact(
        kind="url",
        skill="demo",
        path=path,
        line=3,
        url="/api/v1/datasets/generate",
        method="POST",
    ) in facts
    assert ContractFact(
        kind="url",
        skill="demo",
        path=path,
        line=6,
        url="/sessions/123/results",
        method="GET",
    ) in facts


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
    assert ContractFact(kind="import", skill="demo", path=path, line=2, module="traigent.future") in facts
    assert ContractFact(
        kind="symbol",
        skill="demo",
        path=path,
        line=2,
        module="traigent.future",
        symbol="Thing",
    ) in facts


def test_dead_teaching_message_contains_location_and_fix_menu() -> None:
    fact = ContractFact(kind="import", skill="demo", path=Path("skills/demo/SKILL.md"), line=7, module="traigent.nope")
    with pytest.raises(AssertionError) as exc_info:
        verify_python_fact(fact, repo_root=None, sdk_version="0.12.0")

    message = str(exc_info.value)
    assert "DEAD TEACHING  skills/demo/SKILL.md:7" in message
    assert "fix one : (a) raise this skill's min_sdk_version in sync_map.yml AND add" in message
    assert "(b) replace the taught API with one available at the declared floor" in message
    assert "(c) mark the block `# contract: skip` ONLY if it is illustrative pseudo-code" in message


def test_cli_flag_regex_extracts_long_options() -> None:
    from .test_env_and_cli import _FLAG_RE

    cmd = "traigent validate --dataset eval.jsonl -v --objectives accuracy --help"
    assert _FLAG_RE.findall(cmd) == ["--dataset", "--objectives", "--help"]


def test_env_and_cli_dedupe_is_per_skill(tmp_path) -> None:
    from .facts import collect_contract_facts

    for skill in ("skill-a", "skill-b"):
        d = tmp_path / "skills" / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("Set `TRAIGENT_DEBUG=1`.\n```bash\ntraigent validate x.jsonl\n```\n")
    facts = collect_contract_facts(str(tmp_path))
    env_facts = [f for f in facts if f.kind == "env"]
    cli_facts = [f for f in facts if f.kind == "cli"]
    assert {f.skill for f in env_facts} == {"skill-a", "skill-b"}
    assert {f.skill for f in cli_facts} == {"skill-a", "skill-b"}
