# Injection Modes Reference

Injection mode controls how Traigent delivers the optimized configuration to your function during trials and production use.

```python
import litellm
from traigent.api.decorators import InjectionOptions

def prompt_model(prompt: str, *, model: str, temperature: float) -> str:
    response = litellm.completion(
        model=model,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""
```

## Mode Comparison

| Mode | Code Changes | Thread-Safe | Best For |
|---|---|---|---|
| `"context"` (default) | Add `traigent.get_config()` call | Yes (contextvars) | Most use cases. Clean, explicit config access. |
| `"parameter"` | Add a config parameter to function signature | Yes (per-call argument) | When you want the config as a visible function argument. |
| `"seamless"` | A local assignment (or parameter) named after each config key | Yes (AST transform) | Existing codebases where the config values already sit in named locals; a literal kwarg in the call is **not** rewritten. |

## Context Mode (Default)

Uses Python's `contextvars` to store the trial configuration. Access it with `traigent.get_config()` anywhere inside the function (including nested calls).

```python
@traigent.optimize(
    # injection_mode defaults to "context", no InjectionOptions needed
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.1, 0.5, 0.9],
    },
)
def answer_question(question: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(question, model=cfg["model"], temperature=cfg["temperature"])
```

### Thread Safety

Context mode uses `contextvars`, which are natively thread-safe in Python 3.7+. Each thread (and each asyncio task) gets its own copy of the context. When Traigent runs parallel trials, each trial sees its own configuration without interference.

**Important**: If you spawn your own threads inside an optimized function, the context does not propagate automatically. Use `traigent.config.context.copy_context_to_thread()` to capture and restore context in worker threads:

```python
from traigent.config.context import copy_context_to_thread

@traigent.optimize(
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def parallel_processing(data_batch: list) -> list:
    cfg = traigent.get_config()

    # Capture context before spawning threads
    snapshot = copy_context_to_thread()

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        def worker(item):
            with snapshot.restore():  # restore context inside the thread
                return process_item(item, cfg)
        return list(executor.map(worker, data_batch))
```

## Parameter Mode

Passes the trial configuration directly as a function parameter. You must specify `config_param` to name the parameter.

```python
@traigent.optimize(
    injection=InjectionOptions(
        injection_mode="parameter",
        config_param="config",
    ),
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.1, 0.5, 0.9],
    },
)
def answer_question(question: str, config: dict = None) -> str:
    return prompt_model(question, model=config["model"], temperature=config["temperature"])
```

### When to Use Parameter Mode

- When you want the configuration dependency to be explicit in the function signature
- When your function is already designed to accept a config dict
- In testing scenarios where you want to pass config directly without Traigent context

### Notes

- The `config` parameter must have a default value (typically `None`) so the function can be called normally outside of optimization.
- During optimization, Traigent injects the trial config as this parameter.
- After `apply_best_config()`, calling the function without a config argument uses the applied best config.

## Seamless Mode

No `get_config()` call. Traigent uses AST (Abstract Syntax Tree) transformation to rewrite **local assignments and parameters whose name equals a configuration key** with the trial's values.

```python
@traigent.optimize(
    injection=InjectionOptions(injection_mode="seamless"),
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.1, 0.5, 0.9],
    },
)
def answer_question(question: str) -> str:
    model = "gpt-4o-mini"      # rewritten per trial: the name matches a config key
    temperature = 0.7          # rewritten per trial
    response = litellm.completion(
        model=model,
        temperature=temperature,
        messages=[{"role": "user", "content": question}],
    )
    return response.choices[0].message.content
```

> Mock mode covers LiteLLM/LangChain calls only — a raw `openai` / `anthropic` client in the body makes real, billable calls even during a "keyless" mock dry-run.

### How It Works

1. At decoration time, Traigent inspects the function's AST.
2. During trials, it rewrites `Assign` / `AnnAssign` statements (and parameters) whose target name is a configuration key; nothing else is touched — not keyword arguments in a call, not `os.environ.get(...)`, not a dict built for `**kwargs`.
3. When no local name matches, the SDK logs `Seamless provider found no injectable targets … the function ran with original values` and every trial runs the original configuration. A mock dry-run still passes in that state, so prove the value reaching the provider call changes across two configurations before any paid run.
4. The original function source is never modified on disk.

### When to Use Seamless Mode

- Migrating an existing codebase to Traigent without touching function bodies
- Quick prototyping where you want zero friction
- Functions with straightforward, single-call LLM usage

### Limitations

- Works with any call whose arguments come from named locals; keep `litellm.completion` in the body for a keyless mock dry-run
- May not detect LLM calls that are deeply nested or dynamically constructed
- Context mode gives more explicit control and is recommended for production

## InjectionOptions Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `injection_mode` | `str \| InjectionMode` | `"context"` | How to deliver config: `"context"`, `"parameter"`, or `"seamless"`. |
| `config_param` | `str \| None` | `None` | Parameter name for `injection_mode="parameter"`. Required when using parameter mode. |
| `auto_override_frameworks` | `bool` | `False` | Auto-override framework constructor calls. Nothing extra to install: `traigent.integrations.enable_framework_overrides` is in the core package. |
| `framework_targets` | `list[str] \| None` | `None` | Dotted `module.Class` paths to override (e.g., `["langchain_openai.ChatOpenAI"]`); the package must be importable. A bare framework name such as `"langchain"` is skipped silently (Traigent/Traigent#2299). |

## Removed Modes

The `"attribute"` and `"decorator"` injection modes were removed in Traigent v2.x due to thread-safety issues. If you pass either of these, Traigent raises a `ValueError` with migration guidance. Use `"context"` (recommended) or `"seamless"` instead.

## Framework Auto-Override

When using `auto_override_frameworks=True`, Traigent intercepts the listed framework constructors and applies the trial configuration automatically. Targets are dotted `module.Class` paths whose package is importable; a bare framework name is skipped silently. Nothing extra to install (`traigent.integrations.enable_framework_overrides` is in core).

```python
@traigent.optimize(
    injection=InjectionOptions(
        injection_mode="context",
        auto_override_frameworks=True,
        framework_targets=["langchain_openai.ChatOpenAI"],
    ),
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_chain(query: str) -> str:
    # LangChain calls are automatically intercepted
    llm = ChatOpenAI(model="gpt-4o-mini")  # Will be overridden
    chain = prompt | llm | output_parser
    return chain.invoke({"query": query})
```
