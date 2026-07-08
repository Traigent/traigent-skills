---
name: traigent-setup-integrations
description: "Integrate Traigent with LangChain, LiteLLM, DSPy, and other AI frameworks. Use when importing langchain/litellm/dspy alongside traigent, setting up multi-provider model testing, using auto_override_frameworks, or asking about framework-specific adapter patterns."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0.3"
---

# Traigent Framework Integrations

## When to Use

Use this skill when:

- Combining Traigent optimization with LangChain, LiteLLM, or DSPy
- Setting up multi-provider model testing (e.g., OpenAI + Anthropic + Google)
- Using `auto_override_frameworks` or `framework_targets` in the decorator
- Writing optimized functions that call framework-specific APIs
- Connecting Traigent results to observability tools (MLflow, Weights & Biases)

## Installation

Install Traigent with framework integration support:

```bash
# All integrations
pip install "traigent[integrations]>=0.19"

# Or install individual frameworks alongside Traigent
pip install "traigent>=0.19" langchain-openai langchain-anthropic
pip install "traigent>=0.19" litellm
pip install "traigent>=0.19" dspy
```

> **Dry-run first.** Before any paid optimization run, activate mock mode (`enable_mock_mode_for_quickstart()`), run with your chosen config, review the estimated cost, and get explicit user approval. See the `traigent` lifecycle skill for the mandatory dry-run-first / cost-approval workflow. Apply this to every integration example below before running against real providers.

## LangChain Integration

Traigent integrates with LangChain by optimizing the model and parameters used inside your chain. The key pattern: get the config from Traigent, then construct your LangChain objects.

### Basic Pattern

```python
import traigent
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

@traigent.optimize(
    eval_dataset="questions.jsonl",
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.3, 0.7, 1.0],
    },
    objectives=["accuracy"],
    max_trials=10,
)
def answer_question(question):
    config = traigent.get_config()

    # Create LangChain components using Traigent config
    llm = ChatOpenAI(
        model=config["model"],
        temperature=config["temperature"],
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Answer the question accurately and concisely."),
        ("human", "{question}"),
    ])
    chain = prompt | llm
    response = chain.invoke({"question": question})
    return response.content

results = answer_question.optimize_sync()  # real run — only after dry-run approval
```

### Auto Override Frameworks

> **Auto-override requires `framework_targets`.** Setting `auto_override_frameworks=True` alone does nothing — the SDK gate requires **both** `auto_override_frameworks=True` and an explicit `framework_targets` list. Without `framework_targets`, the override is silently skipped.
>
> **Single-provider only.** Auto-override swaps the **model string** that gets passed to the constructor — it does not swap the **client class**. If your config space mixes OpenAI and Anthropic models but the function only constructs `ChatOpenAI(...)`, the Anthropic trial passes an Anthropic model name to an OpenAI client and gets an invalid-model error. Scope the config space to one provider per override target, or use manual config injection for cross-provider optimization.

```python
@traigent.optimize(
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.5, 1.0],
    },
    objectives=["accuracy"],
    max_trials=6,
    auto_override_frameworks=True,
    framework_targets=["langchain_openai.ChatOpenAI"],  # required
)
def summarize_document(text):
    # ChatOpenAI constructor is intercepted; model and temperature are replaced per trial
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)
    response = llm.invoke(text)
    return response.content
```

For finer control, use `framework_targets` to specify exactly which classes to override:

```python
@traigent.optimize(
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.5],
    },
    objectives=["accuracy"],
    max_trials=8,
    auto_override_frameworks=True,  # required — framework_targets alone is silently skipped
    framework_targets=["langchain_openai.ChatOpenAI"],
)
def my_chain(input_text):
    llm = ChatOpenAI(model="gpt-4o-mini")  # Will be overridden
    return llm.invoke(input_text).content
```

See [LangChain reference](references/langchain.md) for RAG chain optimization and advanced patterns.

## LiteLLM Multi-Provider

LiteLLM provides a unified `completion()` interface across 100+ LLM providers (OpenAI, Anthropic, Google, OpenRouter, and more). This makes it natural to optimize across providers with Traigent:

> **Verify model IDs are live + priced before a real run.** Provider catalogs change — IDs get
> delisted, renamed, or re-routed to a retired backend. A dead ID causes a 404 or a *degraded*
> trial whose cost stays unpriced ($0.00). The IDs below were valid when written; re-check them
> first with `traigent models --provider <p> --check <id>` (or the provider's live catalog
> endpoint — e.g. `curl -s https://openrouter.ai/api/v1/models` for OpenRouter). Prefer specific
> versioned IDs over `-latest` aliases. See [LiteLLM reference](references/litellm.md#verifying-model-availability) and the `traigent-debugging` skill's "Model 404 / retired endpoint" entry.

> **⚠️ Give reasoning models enough `max_tokens` headroom.** Reasoning models (`gemini-2.5`/`3.x`,
> `gpt-5`, the `o`-series) spend hidden reasoning tokens that count against `max_tokens` *before*
> any answer text is emitted. A cap sized for a normal model (e.g. `256`/`512`) can be fully
> consumed by reasoning, truncating the answer mid-output (`finish_reason=length`), so the more
> capable model silently scores *far below* a cheap non-reasoning one purely as a measurement
> artifact — not a real quality gap. Give reasoning models ample output headroom (**≥1024–2048**);
> the sweep below uses headroom-safe values because its model pool mixes reasoning and
> non-reasoning models — sweep low caps only in a space with no reasoning models. Field-observed:
> `gemini-2.5-pro` at `max_tokens=256` spent 241 tokens on reasoning and emitted a truncated
> query (~23% of the expected output); at `1536` it completed correctly.

```python
import traigent
import litellm

@traigent.optimize(
    eval_dataset="classification_eval.jsonl",
    configuration_space={
        # Re-verify each ID is live + priced first (see note above); examples are illustrative.
        "model": [
            "gpt-4o-mini",          # OpenAI
            "gpt-4o",               # OpenAI
            "claude-3-haiku-20240307",  # Anthropic (versioned, not a -latest alias)
            "claude-3-5-sonnet-20241022",  # Anthropic
            "gemini/gemini-3-flash",    # Google
        ],
        "temperature": [0.0, 0.3, 0.7],
        "max_tokens": [1024, 2048],  # headroom-safe: the pool includes a reasoning model (see note above)
    },
    objectives=["accuracy"],
    max_trials=15,
)
def classify_text(text):
    config = traigent.get_config()

    response = litellm.completion(
        model=config["model"],
        messages=[{"role": "user", "content": f"Classify this text: {text}"}],
        temperature=config["temperature"],
        max_tokens=config["max_tokens"],
    )
    return response.choices[0].message.content

results = classify_text.optimize_sync()  # real run — only after dry-run approval

# Check cost across providers
for trial in results.successful_trials:
    model = trial.config["model"]
    accuracy = trial.get_metric("accuracy", 0.0)
    print(f"{model}: accuracy={accuracy:.2%}")
```

LiteLLM handles API key routing automatically based on the model prefix. Set provider API keys in environment variables:

```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="..."      # LiteLLM reads GEMINI_API_KEY for gemini/* models
export OPENROUTER_API_KEY="sk-or-..."  # LiteLLM reads OPENROUTER_API_KEY for openrouter/* models
# Note: google-genai SDK reads GOOGLE_API_KEY; LiteLLM reads GEMINI_API_KEY — they are different env vars
```

See [LiteLLM reference](references/litellm.md) for the full provider list and cost tracking details.

## DSPy Integration

Traigent provides a `DSPyPromptOptimizer` adapter that wraps DSPy's MIPROv2 and BootstrapFewShot optimizers for automatic prompt engineering:

```python
from traigent.integrations.dspy_adapter import DSPyPromptOptimizer

optimizer = DSPyPromptOptimizer(method="mipro")

result = optimizer.optimize_prompt(
    module=my_dspy_module,
    trainset=train_examples,
    metric=accuracy_metric,
)

# Access the optimized module
optimized_module = result.optimized_module
print(f"Best score: {result.best_score}")
print(f"Method: {result.method}")
print(f"Demos: {result.num_demos}")
```

You can also use DSPy modules inside a Traigent-optimized function for model-level optimization:

```python
import traigent
import dspy

@traigent.optimize(
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.5, 1.0],
    },
    objectives=["accuracy"],
    max_trials=6,
)
def dspy_qa(question):
    config = traigent.get_config()
    lm = dspy.LM(config["model"], temperature=config["temperature"])
    dspy.configure(lm=lm)

    qa = dspy.Predict("question -> answer")
    result = qa(question=question)
    return result.answer
```

See [DSPy reference](references/dspy.md) for BootstrapFewShot patterns and advanced configuration.

## Observability Integrations

### MLflow

Log Traigent optimization results to MLflow for experiment tracking:

```python
import mlflow

results = func.optimize_sync()

with mlflow.start_run():
    mlflow.log_param("algorithm", results.algorithm)
    mlflow.log_param("best_config", results.best_config)
    mlflow.log_metric("best_score", results.best_score or 0.0)
    mlflow.log_metric("total_cost", results.total_cost or 0.0)
    mlflow.log_metric("total_trials", len(results.trials))
    mlflow.log_metric("success_rate", results.success_rate)

    for trial in results.successful_trials:
        with mlflow.start_run(nested=True, run_name=trial.trial_id):
            mlflow.log_params(trial.config)
            mlflow.log_metrics(trial.metrics)
```

### Weights & Biases

```python
import wandb

results = func.optimize_sync()

wandb.init(project="traigent-optimization")
for trial in results.trials:
    wandb.log({
        "trial_id": trial.trial_id,
        "status": str(trial.status),
        **trial.config,
        **trial.metrics,
    })
wandb.log({
    "best_score": results.best_score,
    "best_config": results.best_config,
    "total_cost": results.total_cost,
})
wandb.finish()
```

## Pattern: The Right Way

When using Traigent with any framework, always follow this order:

1. Get the config from Traigent
2. Create framework objects using that config
3. Execute with those objects

```python
# CORRECT: get config first, then create client
@traigent.optimize(
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"], "temperature": [0.0, 0.5]},
    objectives=["accuracy"],
)
def my_func(text):
    config = traigent.get_config()           # 1. Get config
    llm = ChatOpenAI(                        # 2. Create client with config
        model=config["model"],
        temperature=config["temperature"],
    )
    return llm.invoke(text).content          # 3. Execute
```

Do not create the client outside the function or before getting the config:

```python
# WRONG: client created before config is available
llm = ChatOpenAI(model="gpt-4o-mini")  # Fixed model, Traigent cannot optimize this

@traigent.optimize(...)
def my_func(text):
    return llm.invoke(text).content  # Always uses the same model
```

The exception is when using `auto_override_frameworks=True`, which intercepts client construction automatically.

## Reference Files

- [LangChain Integration Details](references/langchain.md)
- [LiteLLM Multi-Provider Guide](references/litellm.md)
- [DSPy Adapter Reference](references/dspy.md)

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->

<!-- INTERACTION_POLICY v1 (synced — do not edit inline; edit docs/shared/interaction-policy.v1.md) -->
## Traigent Interaction Policy
Track an interaction profile and adapt to it. Persona (stable): control=`delegate|guided|inspect`,
expertise=`se|ds|unknown`. Mood (this session): pace=`execute|balanced|explore`. Default when
unknown: `guided,se,balanced`. Infer from explicit user statements first, then recent behavior;
an explicit correction wins immediately. Never store or send this profile anywhere by default.

### Fetch the live profile (when available)
At session or skill start, if a configured Traigent client is available, seed the profile from the
backend with the skill name:

```python
policy = None
try: policy = await client.get_interaction_policy(skill="<this skill>")
except Exception: pass
```

Treat the returned `profile` as the STARTING seed: its control/expertise/pace axes plus
`question_budget`, `options_max`, and `jargon_level` replace the static defaults below. Explicit user
corrections in-conversation ALWAYS override the seed. If the call is unavailable or
`fallback_policy="static_v1"`, simply use the static defaults below; the SDK already fails soft.

- Always be concise.
- Match terminology to expertise. For `se`: plain engineering words; define each Traigent or
  statistics term once in plain language (no Bayesian / variance-decomposition / Pareto jargon
  unless asked). For `ds`: compact optimization and statistical terms are fine.
- Presenting options: show at most 3, mark exactly one **Recommended**, and give one short
  persona-appropriate trade-off per option.
- Autonomy. For `delegate` or `execute`: pick the recommended reversible action and proceed, asking
  only at hard gates. For `guided`: offer options with a recommendation at the key decisions. For
  `inspect` or `explore`: give brief rationale or evidence before asking, and ask before branch
  choices.
- Hard gates — always confirm regardless of persona: paid or provider model calls, sending data or
  private content off the machine, destructive edits, decisions the Traigent service is meant to
  return, and any missing fact the step truly requires.
- Always end by recommending the next Traigent skill or action to take.
- Never weaken Traigent safety: dry-run before any paid run; get explicit approval before real cost
  or before any data leaves the machine; treat service-returned plans and next steps as
  authoritative. Never put the persona profile or any private content into telemetry, run metadata,
  experiment names, logs, or provenance files.
<!-- /INTERACTION_POLICY v1 -->
