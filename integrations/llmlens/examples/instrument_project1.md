# Instrumenting Project 1 (agentic-graph-rag) with llmlens

Project 1 is a LangChain/LangGraph app, so the llmlens LangChain callback handler
captures its agent runs, LLM calls, tool calls, tokens, latency, and errors with
almost no code.

## 1. Install the SDK into Project 1's environment

```bash
pip install -e ../llmlens/sdk        # or: pip install llmlens
```

## 2. Point it at your llmlens server

```bash
export LLMLENS_URL=http://localhost:8000
export LLMLENS_API_KEY=sk_...        # from `llmlens-server create-project`, or omit in local/auth-off mode
```

## 3. Turn it on (one place, at startup)

In `agentic-graph-rag`'s API startup (e.g. `graphrag/api/app.py` `create_app`) or
`container.py`, add:

```python
import llmlens
llmlens.configure()                 # reads the env vars above
llmlens.instrument("langchain")     # global LangChain callback handler
```

`instrument("langchain")` registers a global handler, so every LangGraph agent
run, LLM call, retriever, and tool call is traced automatically — no per-call
wiring.

### Optional: tag traces with the end user

The agent already routes by `X-User-Id`. To attribute cost per user in llmlens,
wrap a request in a trace and set the user:

```python
with llmlens.trace("agent_query", user_id=user_id):
    result = agent.session(question, ...).run()
```

## 4. Generate some traffic and look

Ask a few questions in Project 1's UI, then open the llmlens dashboard — you'll
see the real agent traces (a waterfall of the tool-using loop), token cost per
model, and latency percentiles.
