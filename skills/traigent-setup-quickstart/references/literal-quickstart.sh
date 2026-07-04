#!/usr/bin/env bash
set -euo pipefail

python -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade --timeout 60 --retries 5 "traigent>=0.19"
python - <<'PY'
import importlib.metadata as md
import traigent
v = md.version("traigent")
if v == "0.0.1" or not hasattr(traigent, "optimize"):
    raise SystemExit(
        f"Bad Traigent install: traigent {v}. "
        'You likely got the PyPI placeholder — reinstall with: python -m pip install --upgrade "traigent>=0.19"'
    )
print(f"traigent {v} OK")
PY

cat > ticket_eval.jsonl <<'JSONL'
{"input": "I was charged twice for my subscription", "output": "billing"}
{"input": "Please update the email address on my account", "output": "account"}
{"input": "The API returns a 500 error on POST requests", "output": "technical"}
{"input": "What are your business hours?", "output": "general"}
{"input": "My invoice has the wrong tax ID", "output": "billing"}
{"input": "I cannot reset my password", "output": "account"}
JSONL

cat > ticket_classifier.py <<'PY'
import traigent, litellm
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()


def mock_demo_accuracy(output, expected, config=None, **_):
    # Mock-only demo scorer; delete this for real runs.
    cfg = config or traigent.get_config() or {}
    base = 0.88 if cfg.get("model") == "gpt-4o" else 0.68
    return max(0.0, base - 0.04 * float(cfg.get("temperature", 0.0)))


@traigent.optimize(
    eval_dataset="ticket_eval.jsonl",
    objectives=["accuracy"],
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.7],
    },
    metric_functions={"accuracy": mock_demo_accuracy},
    offline=True,
)
def classify_ticket(query: str) -> str:
    config = traigent.get_config()
    response = litellm.completion(
        model=config["model"],
        temperature=config["temperature"],
        messages=[
            {"role": "system", "content": "Classify the ticket as: billing, technical, account, or general."},
            {"role": "user", "content": query},
        ],
    )
    return response.choices[0].message.content


results = classify_ticket.optimize_sync(max_trials=4, algorithm="grid")
print(f"Stop reason: {getattr(results, 'stop_reason', None)}")
print(f"Best config: {results.best_config}")
assert results.trials, "no trials ran"
assert not getattr(results, "failed_trials", []), f"failed trials: {results.failed_trials}"
assert results.best_config is not None, "no best config selected"
print("TRAIGENT-DRY-RUN-OK")
PY

export TRAIGENT_OFFLINE_MODE=true
export LITELLM_LOCAL_MODEL_COST_MAP=True
# Mock/offline env is set in bash, BEFORE python imports anything.
export TRAIGENT_OFFLINE_MODE=true
export LITELLM_LOCAL_MODEL_COST_MAP=True
python ticket_classifier.py
