"""CI safety gate: live skill pointers, no private tracker link, least-privilege workflows.

Traigent/traigent-skills#324. The skill pointed at a removed ``traigent`` skill
section, quoted a private tracker URL as the place to "track progress", and its
reference workflow exported ``TRAIGENT_API_KEY`` at job level (so every step,
including ``pip install``, saw it) with no ``permissions:`` and no provider key
for the real holdout calls.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import yaml

from .extract import _iter_fenced_blocks

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "skills" / "traigent-ci-safety-gate"


def _skill_files() -> list[Path]:
    return sorted(SKILL_DIR.glob("**/*.md"))


def _workflows() -> list[tuple[str, dict]]:
    found = []
    for path in _skill_files():
        for block in _iter_fenced_blocks(path.read_text(encoding="utf-8").splitlines()):
            if block.language in {"yaml", "yml"}:
                workflow = yaml.safe_load(block.text)
                if isinstance(workflow, dict) and "jobs" in workflow:
                    found.append((f"{path.relative_to(ROOT)}:{block.start_line}", workflow))
    return found


def test_backticked_skill_references_resolve_to_catalog_skills() -> None:
    catalog = json.loads((ROOT / "catalog" / "skills.json").read_text(encoding="utf-8"))
    names = {entry["name"] for entry in catalog["skills"]}
    dangling = [
        f"{path.relative_to(ROOT)}:{number}: `{match.group(1)}`"
        for path in _skill_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        for match in re.finditer(r"`(traigent(?:-[a-z0-9]+)*)`", line)
        if match.group(1) not in names
    ]
    assert not dangling, "skill references outside catalog/skills.json:\n" + "\n".join(dangling)


# Skills whose shipped files this guard owns; widen as the other skills are cleaned.
GUARDED_SKILLS = (
    "traigent-boost-agent",
    "traigent-recipe-text2sql",
    "traigent-debugging",
    "traigent-ci-safety-gate",
)
# sha256 hex digests of the lower-cased private repository names and internal
# process names this guard forbids. Only digests are stored, so this public file
# does not itself publish the names. A name is matched as an exact token or as a
# space-joined pair of adjacent tokens.
_FORBIDDEN_DIGESTS = frozenset(
    {
        "4b0d52b5fe57a72118686eceb450745490a7845fd8aed3cd70d63a61d6ae83f5",
        "e263d8477cc55c17a893b97f6f157670e08c6e9a4075b64640d36fb8577c11a1",
        "46a4eb38efcb91478fa66e5ee562d06d1fdd8ab589505e8d6b1414c391d234d1",
        "5e4bce6b1241887627c40c217bbbc3449cf1671fee397a1b491e8216ae04e704",
        "9118ba5723deb2140b1aa04a341762a7b665cb72b812c9d82dab6b9f6270f857",
        "d3893c473eedf3da07c3d47ff384a0a95efb25d95383e248e3c44d73c88617ec",
        "d481251561a99ec03fb85d7d878743f5884e9a473e21e6f51b0c3f3ccb059336",
        "d96433c5035ffaf14e44254294b4b8ca6d1a5cb0e666fe4ec3e4111bc52a7c98",
        "861f45c372adf689e09f74df2a47d0b0349b619da62e8c87d2cd75a8fe45c341",
        "0eccb671e337969d9b79992fbee4643624ea1ee5c53a7ea353ca2ce0a4be9f40",
        "5ad146f2d30d19c4970bdb35799506be10c8c30e53d894d2f2c549e0319547d5",
        "a30958eb2bd12be964d08ddf0576695d8f5effb899f625960148c9f0eed311c5",
        "36b7640ccb0ba79136e544fb4837f2a5e1c456e413b9132ec4d67f8fd1fe692c",
        "9ef8a4f3e1f38e84cd348a77301deb10e98bf3fbefbc78077a9c192c1b03b420",
        "09cf980b5ff304ac11b7f6d2c5c263da2a867425798ef5cc5d2ebcf55c4fcd23",
        "4cf962fe4001587c403c11b44fd382f1cd5f130f0079b4a994ce1d8e1f024764",
        "8d2a1c62f317564f9f5e2bfc6a2bdc26dd84bac4d4991e97f45d07df94bb82d7",
    }
)
_TOKEN_RE = re.compile(r"[a-z0-9_.-]+")
# Internal trail / session id shapes (generic patterns, not names).
_ID_RE = re.compile(r"\bst_[0-9a-f]{12}\b|\bcs_[0-9a-f]{16}\b", re.IGNORECASE)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _forbidden_in(line: str) -> list[str]:
    # Trim edge punctuation so a name that ends a sentence ("name.") still matches.
    tokens = [tok.strip("._-") for tok in _TOKEN_RE.findall(line.lower())]
    tokens = [tok for tok in tokens if tok]
    candidates = tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
    found = [c for c in candidates if _digest(c) in _FORBIDDEN_DIGESTS]
    return found + [m.group(0) for m in _ID_RE.finditer(line)]


def _shipped_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *(f"skills/{name}" for name in GUARDED_SKILLS)],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return [ROOT / rel for rel in listed.split("\0") if rel]


def test_no_private_repository_or_internal_process_names_in_shipped_skill_files() -> None:
    files = _shipped_files()
    assert files, "git ls-files returned nothing for the guarded skills"
    hits = [
        f"{path.relative_to(ROOT)}:{number}: {match!r}"
        for path in files
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        for match in _forbidden_in(line)
    ]
    assert not hits, "private repository / internal process names in public skill files:\n" + "\n".join(hits)
    assert "track progress at https://" not in "".join(p.read_text(encoding="utf-8") for p in files)


def test_workflows_are_read_only_and_keep_secrets_off_job_level_env() -> None:
    workflows = _workflows()
    assert len(workflows) >= 2, workflows
    for where, workflow in workflows:
        assert workflow.get("permissions") == {"contents": "read"}, where
        for job_name, job in workflow["jobs"].items():
            job_env = job.get("env", {}) or {}
            leaked = [k for k, v in job_env.items() if "secrets." in str(v)]
            assert not leaked, f"{where}:{job_name}: secrets in job-level env: {leaked}"


def test_real_holdout_steps_receive_a_provider_key() -> None:
    nightly = [
        (where, workflow["jobs"]["nightly-real-holdout"])
        for where, workflow in _workflows()
        if "nightly-real-holdout" in workflow["jobs"]
    ]
    assert nightly
    for where, job in nightly:
        holdout_steps = [
            step for step in job["steps"]
            if "run_holdout_eval.py" in step.get("run", "") and "--mode mock" not in step.get("run", "")
        ]
        assert holdout_steps, where
        for step in holdout_steps:
            keys = [k for k in (step.get("env") or {}) if k.endswith("_API_KEY") and k != "TRAIGENT_API_KEY"]
            assert keys, f"{where}: step {step.get('name')!r} calls the agent with no provider key"
