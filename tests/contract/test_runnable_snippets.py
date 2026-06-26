from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from .extract import RunnableSnippet


SENSITIVE_ENV_NAMES = {
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "COHERE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "TRAIGENT_API_KEY",
}
CI_ENV_NAMES = {
    "CI",
    "GITHUB_ACTIONS",
    "GITHUB_RUN_ID",
    "GITHUB_WORKFLOW",
}


def test_runnable_python_snippet_executes_in_offline_mock(
    runnable_snippet: RunnableSnippet,
    tmp_path: Path,
) -> None:
    snippet_path = tmp_path / "snippet.py"
    runner_path = tmp_path / "run_snippet.py"
    home_path = tmp_path / "home"
    home_path.mkdir()
    snippet_path.write_text(runnable_snippet.text + "\n", encoding="utf-8")
    runner_path.write_text(_runner_source(snippet_path), encoding="utf-8")
    env = _offline_mock_env()
    env["HOME"] = str(home_path)

    completed = subprocess.run(
        [sys.executable, str(runner_path)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, (
        f"runnable snippet failed: {runnable_snippet.identifier()}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def _runner_source(snippet_path: Path) -> str:
    return textwrap.dedent(
        f"""
        from __future__ import annotations

        import runpy
        import sys
        import warnings

        ALLOWED_DEPRECATION_SUBSTRINGS = (
            "execution_mode='edge_analytics' is deprecated for TraigentConfig",
            "execution_mode='hybrid' is deprecated for TraigentConfig",
            "privacy_enabled is deprecated for TraigentConfig",
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default")
            runpy.run_path({str(snippet_path)!r}, run_name="__main__")

        deprecations = [
            item
            for item in caught
            if issubclass(item.category, DeprecationWarning)
            and not any(marker in str(item.message) for marker in ALLOWED_DEPRECATION_SUBSTRINGS)
        ]
        if deprecations:
            for item in deprecations:
                print(
                    f"{{item.category.__name__}}: {{item.message}} "
                    f"at {{item.filename}}:{{item.lineno}}",
                    file=sys.stderr,
                )
            sys.exit(1)
        """
    )


def _offline_mock_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in SENSITIVE_ENV_NAMES and key not in CI_ENV_NAMES
    }
    for key in list(env):
        if key.endswith("_API_KEY") or key.endswith("_SECRET_ACCESS_KEY"):
            env.pop(key, None)

    env.update(
        {
            "ENVIRONMENT": "test",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "TRAIGENT_OFFLINE_MODE": "true",
        }
    )
    return env
