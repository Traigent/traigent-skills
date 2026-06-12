from __future__ import annotations

import importlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .facts import ContractFact
from .verifier import format_dead_teaching


def test_taught_traigent_env_vars_exist_in_sdk_source(env_fact: ContractFact, repo_root: Path, sdk_version_label: str) -> None:
    import traigent

    sdk_root = Path(traigent.__file__).parent
    needle = env_fact.name or ""
    found = False
    for path in sdk_root.rglob("*.py"):
        if needle in path.read_text(encoding="utf-8", errors="ignore"):
            found = True
            break
    assert found, format_dead_teaching(
        env_fact,
        repo_root=repo_root,
        sdk_version=sdk_version_label,
        taught=needle,
        problem="env var missing from installed SDK source",
    )


def test_taught_traigent_cli_commands_exist(cli_fact: ContractFact, repo_root: Path, sdk_version_label: str) -> None:
    command = cli_fact.command or ""
    if command.startswith("python -m traigent."):
        module = command.split()[2]
        try:
            importlib.import_module(module)
        except ModuleNotFoundError as exc:
            raise AssertionError(
                format_dead_teaching(
                    cli_fact,
                    repo_root=repo_root,
                    sdk_version=sdk_version_label,
                    taught=command,
                    problem="module not found",
                )
            ) from exc
        return

    executable = Path(sys.executable).with_name("traigent")
    if not executable.exists():
        located = shutil.which("traigent")
        executable = Path(located) if located else executable
    help_text = subprocess.check_output([str(executable), "--help"], text=True)
    subcmd = command.split()[1]
    if _command_in_help(subcmd, help_text):
        _assert_taught_flags_exist(cli_fact, executable, command, repo_root, sdk_version_label)
        return

    for group in _groups_to_probe(command):
        group_help = subprocess.run([str(executable), group, "--help"], text=True, capture_output=True, check=False)
        if _command_in_help(subcmd, group_help.stdout + group_help.stderr):
            _assert_taught_flags_exist(cli_fact, executable, command, repo_root, sdk_version_label)
            return

    raise AssertionError(
        format_dead_teaching(
            cli_fact,
            repo_root=repo_root,
            sdk_version=sdk_version_label,
            taught=command,
            problem="cli command missing",
        )
    )


_FLAG_RE = re.compile(r"(?<!\S)--[a-z][\w-]*")


def _assert_taught_flags_exist(
    cli_fact: ContractFact,
    executable: Path,
    command: str,
    repo_root: Path,
    sdk_version_label: str,
) -> None:
    """A taught option must exist on the real subcommand, not just the command.

    Catches dead teachings like `traigent validate --dataset X` where the real
    CLI takes a positional DATASET_PATH.
    """
    flags = [f for f in _FLAG_RE.findall(command) if f != "--help"]
    if not flags:
        return
    parts = command.split()
    sub_help = subprocess.run(
        [str(executable), *parts[1:2], "--help"], text=True, capture_output=True, check=False
    )
    help_text = sub_help.stdout + sub_help.stderr
    for flag in flags:
        assert flag in help_text, format_dead_teaching(
            cli_fact,
            repo_root=repo_root,
            sdk_version=sdk_version_label,
            taught=command,
            problem=f"cli option {flag} not accepted by `traigent {parts[1]}`",
        )


def _command_in_help(subcmd: str, help_text: str) -> bool:
    return any(line.strip().startswith(f"{subcmd} ") or line.strip() == subcmd for line in help_text.splitlines())


def _groups_to_probe(command: str) -> list[str]:
    parts = command.split()
    if len(parts) >= 3 and parts[0] == "traigent":
        return [parts[1]]
    return []
