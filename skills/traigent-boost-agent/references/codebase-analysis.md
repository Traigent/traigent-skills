# Codebase Analysis Heuristics

Use this reference when you are inside a client repository and need to decide where Traigent belongs.

## Find the agent surface

Start broad, then narrow to the scoreable function.

Raw OpenAI:

```bash
rg -n "OpenAI\\(|AsyncOpenAI|chat\\.completions\\.create|responses\\.create|embeddings\\.create|stream=True|tools=|tool_choice|response_format|model=|temperature=|top_p=|max_tokens" .
```

Raw Anthropic:

```bash
rg -n "Anthropic\\(|AsyncAnthropic|messages\\.create|system=|tools=|tool_choice|max_tokens|temperature" .
```

LiteLLM:

```bash
rg -n "litellm\\.(completion|acompletion)|from litellm import|completion\\(|acompletion\\(" .
```

LangChain and agent frameworks:

```bash
rg -n "ChatOpenAI|ChatAnthropic|init_chat_model|PromptTemplate|ChatPromptTemplate|Runnable|RunnableSequence|AgentExecutor|create_react_agent|bind_tools|tool\\(|as_retriever|similarity_search|RetrievalQA|ConversationalRetrievalChain" .
```

Framework-neutral control flow:

```bash
rg -n "system_prompt|user_prompt|messages|retriev|rerank|vector|tool_calls|function_call|scratchpad|critic|judge|verify|repair|retry|fallback|route|classif" .
```

## Shape markers

| Shape | Code clues |
|---|---|
| Single LLM call | One prompt/messages builder and one model invocation with no branch, tool loop, judge, or verifier. |
| Cheap-vs-expensive path | Conditional model tier, confidence threshold, "fast" then "accurate" model, or escalation after low confidence. |
| Multi-stage chain | Sequential `classify -> retrieve -> answer`, `draft -> judge -> repair`, `plan -> execute -> summarize`, or similar stage functions. |
| Router | Domain, intent, language, risk, or input-type classifier chooses one handler before the main call. |
| Tool loop | `while`/`for` loop around tool calls, scratchpad, observations, `bind_tools`, function-calling, or ReAct-style agent executor. |
| Generate-then-check | Draft plus validator, judge, verifier, unit test, schema check, SQL execution check, or citation check. |
| Specialist committee | Multiple prompts, personas, retrievers, or models answer the same input before vote/judge aggregation. |
| Fallback | Primary call plus backup model/provider/prompt, usually after no answer, low confidence, parse failure, timeout, or exception. |
| Iterative refine | Loop over draft, critique, repair, score, previous score, or improvement delta. |

## Where the decorator goes

Place `@traigent.optimize` on the smallest function that:

- accepts the user/task input you can evaluate,
- returns the final answer, patch, route, classification, or structured result,
- contains or directly calls the LLM/retrieval/tool stages whose behavior will change,
- can be invoked repeatedly from an eval dataset without external side effects, or can have those side effects mocked.

Good targets:

- `answer(question: str) -> str`
- `run_agent(task: str) -> AgentResult`
- `solve_issue(issue: IssueInput) -> Patch`
- `classify_ticket(ticket: Ticket) -> str`
- `rag_answer(question: str, tenant_id: str) -> Answer`

Poor targets:

- web route handlers that mix auth, HTTP, billing, and agent logic,
- generic provider wrappers used by many unrelated features,
- retry/backoff helpers,
- credential loaders,
- tracing/export code,
- database migration or infra setup code.

If the framework hides the call inside an object graph, create a narrow adapter that receives the same logical input, calls the existing chain/agent, and is used only for evaluation until the winning config is applied.

## What not to touch

Do not alter auth, tenant isolation, provider key loading, billing, retry/backoff policy, HTTP routing, persistence schemas, deployment config, or observability exporters just to add Traigent. If a tuned variable needs runtime wiring, thread it only into the prompt, model parameters, retriever, context assembly, tool policy, stage choice, or verifier path it actually controls.

Keep the current production behavior represented as a baseline value in the config space. Do not delete the old path until optimization evidence shows a better config and the user approves applying it.

## Build the eval dataset honestly

Prefer existing evidence:

- unit/integration fixtures with known expected outputs,
- golden QA/classification/extraction sets,
- accepted historical code-agent patches and the tests they passed,
- production logs only after redaction, permission checks, and removal of secrets/PII,
- support tickets or task traces with stable outcome labels.

Dataset rules:

- Use JSONL with `input` and `output` when the built-in evaluator can score the task.
- Preserve a held-out set if enough data exists; do not tune and claim on the same cherry-picked examples.
- Stratify by known input classes, difficulty, tenants/domains, languages, and failure modes.
- Include the current baseline behavior and cost as the comparison point.
- For RAG, score both answer correctness and support/citation quality when possible.
- For coding agents, score patch acceptance, focused tests, regression tests, lint/type checks, and cost/time.
- For tool agents, score task success, invalid tool calls, loop exhaustion, latency, and spend.

Report dataset limits explicitly: sample count, source, holdout status, label quality, and anything excluded.
