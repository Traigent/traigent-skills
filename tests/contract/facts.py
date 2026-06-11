from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ContractFact:
    kind: str
    skill: str
    path: Path
    line: int
    module: str | None = None
    symbol: str | None = None
    target: str | None = None
    kwargs: tuple[str, ...] = field(default_factory=tuple)
    name: str | None = None
    command: str | None = None

    def rel_path(self, repo_root: Path | None = None) -> str:
        if repo_root is not None:
            try:
                return self.path.resolve().relative_to(repo_root.resolve()).as_posix()
            except ValueError:
                pass
        return self.path.as_posix()

    def display(self) -> str:
        if self.kind == "import":
            return f"import {self.module}"
        if self.kind == "symbol":
            return f"from {self.module} import {self.symbol}"
        if self.kind == "call_kwargs":
            kwargs = ", ".join(f"{name}=" for name in self.kwargs)
            return f"{self.target}({kwargs})"
        if self.kind == "env":
            return self.name or ""
        if self.kind == "cli":
            return self.command or ""
        return self.kind

    def identifier(self, repo_root: Path | None = None) -> str:
        return f"{self.rel_path(repo_root)}:{self.line}::{self.display()}"


@lru_cache(maxsize=8)
def collect_contract_facts(repo_root: str) -> tuple[ContractFact, ...]:
    from .extract import collect_from_repo

    return tuple(collect_from_repo(Path(repo_root)))
