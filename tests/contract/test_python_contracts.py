from __future__ import annotations

from .facts import ContractFact
from .verifier import verify_python_fact


def test_python_contract_fact_imports_symbols_and_kwargs(
    python_fact: ContractFact,
    repo_root,
    sdk_version_label: str,
) -> None:
    verify_python_fact(python_fact, repo_root=repo_root, sdk_version=sdk_version_label)
