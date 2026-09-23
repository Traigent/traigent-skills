# LangChain Integration Reference

> **Dry-run first.** Before running any real LangChain optimization, activate `enable_mock_mode_for_quickstart()`, run, review the cost estimate, and get explicit approval. See the `traigent-boost-agent` skill for the dry-run-first / cost-approval mandate.
> - LangChain clients require a key at construction, so set a non-secret
>   placeholder in the dry-run process only — e.g. `OPENAI_API_KEY=mock-placeholder` (it cannot bill;
>   the calls are intercepted).

## Overview

Traigent integrates with LangChain to optimize model selection, temperature, and other parameters across chains, agents, and RAG pipelines. There are two approaches:

1. **Manual config injection** - call `traigent.get_config()` and construct LangChain objects yourself
2. **Auto override** - let Traigent intercept LangChain model instantiation via `auto_override_frameworks=True` together with `framework_targets`

## Installation

```bash
pip install "traigent[integrations]>=0.19"

# Plus the LangChain provider packages you need
pip install langchain-openai langchain-anthropic langchain-google-genai
```

## auto_override_frameworks

> **Released SDK caveat:** on `traigent<=0.27.0` auto-override is a silent no-op — every trial
> constructs the client with the literal values in your code, and the run still ranks the trials
> and reports a `best_config`. Until a release that fixes it, use manual injection (the Basic
> Pattern: build the client from `traigent.get_config()`). Before any paid run, verify in mock mode
> that the constructed client's `model_name` differs across two trials (the preflight in
> [Verify the override before a paid run](#verify-the-override-before-a-paid-run) below).

> **Requires `framework_targets`.** `auto_override_frameworks=True` alone is not sufficient — both flags must be set together, otherwise the override is silently skipped.
>
> **Swaps the model string, not the client class.** Auto-override intercepts the `__init__` call and replaces `model=` with the trial's config value. It does NOT swap `ChatOpenAI` for `ChatAnthropic` when an Anthropic model is selected — using a mixed-provider config space with a single-provider function causes invalid-model errors for the non-matching provider's trials. Use a single-provider config space per override target, or use manual config injection for cross-provider optimization.

When `auto_override_frameworks=True` and `framework_targets` are set, Traigent intercepts LLM client constructors and injects the current trial's configuration:

```python
import traigent
from langchain_openai import ChatOpenAI

@traigent.optimize(
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],  # single provider only
        "temperature": [0.0, 0.5, 1.0],
    },
    objectives=["accuracy"],
    max_trials=6,
    auto_override_frameworks=True,
    framework_targets=["langchain_openai.ChatOpenAI"],  # required
)
def my_chain(text):
    # ChatOpenAI.__init__ is intercepted; model and temperature are replaced per trial
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)
    return llm.invoke(text).content
```

On an SDK where auto-override applies (see the caveat above), each trial replaces the `model` and `temperature` arguments with the trial's configuration values. After optimization, calling `apply_best_config()` locks in the best configuration.

### Verify the override before a paid run

Run this keyless mock check first. It fails when the constructed client never changes across
trials. `OPENAI_API_KEY=mock-placeholder` is a non-secret placeholder: LangChain needs a key at
construction, and mock mode intercepts the calls, so nothing is billed.

```python
# OPENAI_API_KEY=mock-placeholder python verify_override.py
import traigent
from langchain_openai import ChatOpenAI
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()
built = set()

@traigent.optimize(
    eval_dataset="questions.jsonl",  # a few rows of {"input": {"question": ...}, "output": ...}
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
    objectives=["accuracy"],
    offline=True,
    algorithm="grid",
    max_trials=2,
    auto_override_frameworks=True,
    framework_targets=["langchain_openai.ChatOpenAI"],
)
def probe(question):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)
    built.add(llm.model_name)
    return llm.invoke(question).content

probe.optimize_sync()
if len(built) < 2:
    raise SystemExit(f"auto-override did not apply: every trial built {sorted(built)}; use manual injection")
print("auto-override applied:", sorted(built))
```

### How It Works

1. Traigent scans the `framework_targets` list for the specified classes
2. During a trial, `__init__` calls to those classes are intercepted
3. Configuration parameters (`model`, `temperature`, etc.) are replaced with the trial values
4. After the trial, the override is removed

### Supported Auto-Discovery Targets

- `langchain_openai.ChatOpenAI`
- `langchain_anthropic.ChatAnthropic`
- `openai.OpenAI`, `openai.AsyncOpenAI`
- `anthropic.Anthropic`, `anthropic.AsyncAnthropic`

## framework_targets

For finer control, specify exactly which classes to override. `framework_targets` does nothing
without `auto_override_frameworks=True` in the same call, and the released-SDK caveat above applies:

```python
@traigent.optimize(
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.5],
    },
    objectives=["accuracy"],
    max_trials=8,
    auto_override_frameworks=True,  # required
    framework_targets=["langchain_openai.ChatOpenAI"],
)
def my_func(text):
    # Only ChatOpenAI is overridden, other LLM classes are untouched
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)
    return llm.invoke(text).content
```

This is useful when your function uses multiple LLM clients and you only want to optimize one of them.

## Manual Config Injection (Recommended for Complex Chains)

For chains with multiple components, manual injection gives you full control:

```python
import traigent
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

@traigent.optimize(
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.3, 0.7],
        "system_prompt_style": ["concise", "detailed", "academic"],
    },
    objectives=["accuracy"],
    max_trials=12,
)
def qa_chain(question):
    config = traigent.get_config()

    system_prompts = {
        "concise": "Answer briefly and accurately.",
        "detailed": "Provide a thorough, well-structured answer.",
        "academic": "Answer with academic rigor, citing reasoning.",
    }

    llm = ChatOpenAI(
        model=config["model"],
        temperature=config["temperature"],
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompts[config["system_prompt_style"]]),
        ("human", "{question}"),
    ])
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"question": question})
```

## RAG Chain Optimization

Optimize retrieval-augmented generation by including retrieval parameters in the config space:

```python
import traigent
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

@traigent.optimize(
    eval_dataset="rag_eval.jsonl",
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.3],
        "top_k": [3, 5, 10],
        "prompt_template": [
            "Answer based on the context:\n{context}\n\nQuestion: {question}",
            "Context: {context}\n\nUsing only the above, answer: {question}",
        ],
    },
    objectives=["accuracy"],
    max_trials=12,
)
def rag_answer(question):
    config = traigent.get_config()

    # Retriever with optimized top_k
    embeddings = OpenAIEmbeddings()
    vectorstore = FAISS.load_local("my_index", embeddings)
    retriever = vectorstore.as_retriever(
        search_kwargs={"k": config["top_k"]}
    )

    # LLM with optimized model and temperature
    llm = ChatOpenAI(
        model=config["model"],
        temperature=config["temperature"],
    )

    # Chain with optimized prompt
    prompt = ChatPromptTemplate.from_template(config["prompt_template"])
    chain = (
        {"context": retriever, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain.invoke(question)

results = rag_answer.optimize_sync()
```

## Programmatic Framework Override API

For advanced use cases, you can manage overrides programmatically:

```python
from traigent.integrations import enable_framework_overrides, disable_framework_overrides

# Enable overrides for specific targets
enable_framework_overrides(["langchain_openai.ChatOpenAI"])

# ... run your code ...

# Disable when done
disable_framework_overrides()
```

## Tips

- Use manual config injection for production code where you want explicit control
- Use `auto_override_frameworks` for quick experimentation and prototyping
- When optimizing RAG, include retrieval parameters (top_k, chunk_size) alongside model parameters
- LangChain's streaming and async interfaces work normally with Traigent config injection
- Always construct LangChain objects inside the decorated function, not at module level
