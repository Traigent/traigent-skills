from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path

from packaging.version import Version


UNPUBLISHED_NPM_INSTALL_RE = re.compile(r"\bnpm\s+(?:i|install|add)\s+@traigent/sdk\b")


def test_public_python_sdk_install_target_is_present(sdk_version_label: str) -> None:
    installed = importlib.metadata.version("traigent")
    if sdk_version_label == "develop":
        # Develop is a moving target; released buckets enforce version identity.
        assert installed
        Version(installed)
        return
    assert installed == sdk_version_label


def test_unpublished_js_sdk_is_not_taught_as_public_npm_install(
    repo_root: Path,
) -> None:
    offenders: list[str] = []
    for path in _markdown_files(repo_root):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            lowered = line.lower()
            if (
                UNPUBLISHED_NPM_INSTALL_RE.search(line)
                and "not published" not in lowered
                and "404" not in lowered
            ):
                offenders.append(
                    f"{path.relative_to(repo_root)}:{line_number}: {line.strip()}"
                )

    assert not offenders, (
        "`@traigent/sdk` is not on the public npm registry yet; do not teach "
        "`npm install @traigent/sdk` as an install path while #30 is blocked.\n"
        + "\n".join(offenders)
    )


def _markdown_files(repo_root: Path) -> list[Path]:
    roots = [repo_root / "README.md", *(repo_root / "skills").glob("**/*.md")]
    return sorted(path for path in roots if path.is_file())
