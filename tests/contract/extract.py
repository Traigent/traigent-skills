from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .facts import ContractFact


ENV_RE = re.compile(r"\bTRAIGENT_[A-Z0-9_]+\b")
FENCE_RE = re.compile(r"^```([A-Za-z0-9_-]+)?\s*$")
IMPORT_LINE_RE = re.compile(r"^\s*(from|import)\s+traigent[\w.]*")


@dataclass(frozen=True, slots=True)
class CodeBlock:
    language: str
    start_line: int
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def collect_from_repo(repo_root: Path) -> list[ContractFact]:
    facts: list[ContractFact] = []
    skills_root = repo_root / "skills"
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        files = [skill_file]
        references = skill_dir / "references"
        if references.is_dir():
            files.extend(sorted(references.glob("*.md")))
        for path in files:
            facts.extend(collect_file(skill_dir.name, path))
    return _dedupe(facts)


def collect_file(skill: str, path: Path) -> list[ContractFact]:
    return collect_markdown(skill, path, path.read_text(encoding="utf-8"))


def collect_markdown(skill: str, path: Path, text: str) -> list[ContractFact]:
    facts: list[ContractFact] = []
    lines = text.splitlines()
    for line_number, line in enumerate(lines, start=1):
        for match in ENV_RE.finditer(line):
            facts.append(ContractFact(kind="env", skill=skill, path=path, line=line_number, name=match.group(0)))

    for block in _iter_fenced_blocks(lines):
        language = block.language.lower()
        if language in {"python", "py"}:
            facts.extend(_extract_python_block(skill, path, block))
        elif language in {"bash", "sh", "shell"}:
            facts.extend(_extract_cli_block(skill, path, block))
    return _dedupe(facts)


def _iter_fenced_blocks(lines: list[str]) -> list[CodeBlock]:
    blocks: list[CodeBlock] = []
    in_block = False
    language = ""
    start_line = 0
    collected: list[str] = []

    for idx, line in enumerate(lines, start=1):
        match = FENCE_RE.match(line)
        if match and not in_block:
            in_block = True
            language = match.group(1) or ""
            start_line = idx + 1
            collected = []
            continue
        if match and in_block:
            blocks.append(CodeBlock(language=language, start_line=start_line, lines=tuple(collected)))
            in_block = False
            language = ""
            start_line = 0
            collected = []
            continue
        if in_block:
            collected.append(line)

    return blocks


def _extract_python_block(skill: str, path: Path, block: CodeBlock) -> list[ContractFact]:
    if block.lines and block.lines[0].strip() == "# contract: skip":
        return []
    try:
        tree = ast.parse(block.text)
    except SyntaxError:
        return _regex_import_fallback(skill, path, block)

    facts: list[ContractFact] = []
    imported_roots: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _rooted_at_traigent(alias.name):
                    continue
                line = block.start_line + node.lineno - 1
                facts.append(ContractFact(kind="import", skill=skill, path=path, line=line, module=alias.name))
                binding = alias.asname or alias.name.split(".", 1)[0]
                imported_roots[binding] = alias.name if alias.asname else alias.name.split(".", 1)[0]
        elif isinstance(node, ast.ImportFrom):
            module = _import_from_module(node)
            if not _rooted_at_traigent(module):
                continue
            line = block.start_line + node.lineno - 1
            facts.append(ContractFact(kind="import", skill=skill, path=path, line=line, module=module))
            for alias in node.names:
                if alias.name == "*":
                    continue
                facts.append(
                    ContractFact(
                        kind="symbol",
                        skill=skill,
                        path=path,
                        line=line,
                        module=module,
                        symbol=alias.name,
                    )
                )
                imported_roots[alias.asname or alias.name] = f"{module}.{alias.name}"

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kwargs = tuple(keyword.arg for keyword in node.keywords if keyword.arg)
        if not kwargs:
            continue
        target = _call_target(node.func, imported_roots)
        if target and _rooted_at_traigent(target):
            facts.append(
                ContractFact(
                    kind="call_kwargs",
                    skill=skill,
                    path=path,
                    line=block.start_line + node.lineno - 1,
                    target=target,
                    kwargs=kwargs,
                )
            )

    return facts


def _regex_import_fallback(skill: str, path: Path, block: CodeBlock) -> list[ContractFact]:
    facts: list[ContractFact] = []
    for offset, line in enumerate(block.lines):
        if not IMPORT_LINE_RE.match(line):
            continue
        line_number = block.start_line + offset
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith("import "):
            imported = stripped.removeprefix("import ")
            for item in imported.split(","):
                module = item.strip().split(" as ", 1)[0].strip()
                if _rooted_at_traigent(module):
                    facts.append(ContractFact(kind="import", skill=skill, path=path, line=line_number, module=module))
        elif stripped.startswith("from "):
            rest = stripped.removeprefix("from ")
            if " import " not in rest:
                continue
            module, symbols = rest.split(" import ", 1)
            module = module.strip()
            if not _rooted_at_traigent(module):
                continue
            facts.append(ContractFact(kind="import", skill=skill, path=path, line=line_number, module=module))
            symbols = symbols.strip().removeprefix("(").removesuffix(")")
            for item in symbols.split(","):
                symbol = item.strip().split(" as ", 1)[0].strip()
                if symbol and symbol != "*":
                    facts.append(
                        ContractFact(
                            kind="symbol",
                            skill=skill,
                            path=path,
                            line=line_number,
                            module=module,
                            symbol=symbol,
                        )
                    )
    return facts


def _extract_cli_block(skill: str, path: Path, block: CodeBlock) -> list[ContractFact]:
    facts: list[ContractFact] = []
    for offset, raw_line in enumerate(block.lines):
        stripped = raw_line.strip()
        if stripped.startswith("$ "):
            stripped = stripped[2:].strip()
        if stripped.startswith("traigent "):
            command = stripped.split("#", 1)[0].strip()
            facts.append(ContractFact(kind="cli", skill=skill, path=path, line=block.start_line + offset, command=command))
        elif stripped.startswith("python -m traigent."):
            command = stripped.split("#", 1)[0].strip()
            facts.append(ContractFact(kind="cli", skill=skill, path=path, line=block.start_line + offset, command=command))
    return facts


def _import_from_module(node: ast.ImportFrom) -> str:
    module = node.module or ""
    if node.level:
        return "." * node.level + module
    return module


def _rooted_at_traigent(value: str | None) -> bool:
    return bool(value == "traigent" or (value and value.startswith("traigent.")))


def _call_target(func: ast.AST, imported_roots: dict[str, str]) -> str | None:
    parts: list[str] = []
    current = func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    root = imported_roots.get(current.id)
    if not root:
        return None
    return ".".join([root, *reversed(parts)])


def _dedupe(facts: list[ContractFact]) -> list[ContractFact]:
    seen: set[object] = set()
    deduped: list[ContractFact] = []
    for fact in facts:
        key: object
        if fact.kind == "env":
            # Per-skill, not global: each skill's floor/env_version_floors must
            # see its own facts (a global dedupe hid a 0.13-only var taught by a
            # 0.12-floor skill behind another skill's gated fact).
            key = (fact.kind, fact.skill, fact.name)
        elif fact.kind == "cli":
            key = (fact.kind, fact.skill, fact.command)
        else:
            key = fact
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fact)
    return deduped
