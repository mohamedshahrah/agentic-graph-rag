# The llmlens SDK

`pip install llmlens`. It's intentionally tiny (one dependency, `httpx`) so it's cheap to
add to any app. Provider libraries are imported lazily — none are hard dependencies.

## Configure

```python
import llmlens
llmlens.configure(api_key="sk_...", url="http://localhost:8000")
# or set LLMLENS_API_KEY / LLMLENS_URL and call llmlens.configure()
```

Env knobs: `LLMLENS_API_KEY`, `LLMLENS_URL`, `LLMLENS_ENABLED`,
`LLMLENS_RECORD_CONTENT` (store prompt/response bodies), `LLMLENS_SAMPLE_RATE`.

## Auto-instrument providers

```python
llmlens.instrument("openai", "anthropic", "langchain")
```

- **openai / anthropic** — wraps `chat.completions.create` / `messages.create`, capturing
  model, tokens, prompt, and response.
- **langchain** — registers a global callback handler that traces every LLM call, chain,
  and tool call (this is how Project 1 is instrumented — see
  `examples/instrument_project1.md`).

## Manual tracing

```python
with llmlens.trace("handle_request", user_id="u1", tags=["prod"]):
    with llmlens.span("retrieve", kind="tool") as s:
        s.output(str(docs), role="tool_output")

    with llmlens.span("chat", kind="generation", provider="openai", model="gpt-4o") as g:
        g.input(prompt, role="user")
        resp = call_model(prompt)
        g.usage(resp.usage.prompt_tokens, resp.usage.completion_tokens)
        g.output(resp.text)
```

Or wrap a function:

```python
@llmlens.observe()
def step(x): ...
```

## How it stays safe

The exporter runs on a background thread with a **bounded queue** — if the app out-produces
the network, events are dropped rather than blocking or growing memory. Every network error
is swallowed and retried with backoff. Instrumentation must never slow or crash the app it
observes.

## Standard OpenTelemetry

Already using the OpenTelemetry SDK? Point your OTLP/HTTP exporter at
`http://<llmlens>/v1/traces` — llmlens reads the `gen_ai.*` semantic conventions directly,
no llmlens SDK required.
