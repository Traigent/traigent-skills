"""Dataset rows shown in traigent-setup-decorator must validate (traigent-skills#354).

``references/evaluation-options.md`` taught rows without an ``input`` object, which
the SDK rejects at decoration (``Missing 'input' or 'input_data' field``). Every
fenced ``json``/``jsonl`` block made of JSON-object lines is treated as dataset
rows and run through the installed ``traigent validate`` CLI.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKILL = "skills/traigent-setup-decorator"
JSON_BLOCK_RE = re.compile(r"^```(?:json|jsonl)\n(.*?)^```", re.S | re.M)


def _jsonl_blocks(text: str) -> list[tuple[int, str]]:
    blocks = []
    for match in JSON_BLOCK_RE.finditer(text):
        lines = [line for line in match.group(1).splitlines() if line.strip()]
        try:
            rows = [json.loads(line) for line in lines]
        except json.JSONDecodeError:
            continue  # a pretty-printed JSON document, not dataset rows
        if len(rows) > 1 or (rows and "input" in rows[0]):
            if all(isinstance(row, dict) for row in rows):
                line = text.count("\n", 0, match.start(1)) + 1
                blocks.append((line, "\n".join(lines) + "\n"))
    return blocks


def _validate(rows: str, workdir: Path) -> subprocess.CompletedProcess[str]:
    dataset = workdir / "rows.jsonl"
    dataset.write_text(rows, encoding="utf-8")
    cli = Path(sys.executable).with_name("traigent")
    assert cli.exists(), f"traigent CLI not installed next to {sys.executable}"
    env = {k: v for k, v in os.environ.items() if k != "TRAIGENT_API_KEY"}
    return subprocess.run(
        [str(cli), "validate", dataset.name],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_decorator_dataset_rows_pass_traigent_validate(
    repo_root: Path, tmp_path: Path
) -> None:
    failures = []
    checked = 0
    for path in [
        repo_root / SKILL / "SKILL.md",
        *sorted((repo_root / SKILL).glob("references/*.md")),
    ]:
        rel = path.relative_to(repo_root).as_posix()
        for line, rows in _jsonl_blocks(path.read_text(encoding="utf-8")):
            checked += 1
            result = _validate(rows, tmp_path)
            if result.returncode != 0:
                failures.append(f"{rel}:{line}\n{result.stdout}{result.stderr}")
    assert checked, "no dataset-row blocks found; the scan lost its target"
    assert not failures, "\n".join(failures)


def test_dataset_row_scan_has_teeth(tmp_path: Path) -> None:
    doc = (
        '```json\n{"question": "q1", "expected": "a"}\n{"question": "q2", "expected": "b"}\n```\n'
        '```json\n{\n  "not": "rows"\n}\n```\n'
    )
    blocks = _jsonl_blocks(doc)
    assert len(blocks) == 1
    assert _validate(blocks[0][1], tmp_path).returncode != 0
    good = '{"input": {"question": "q1"}, "output": "a"}\n'
    assert _validate(good, tmp_path).returncode == 0
