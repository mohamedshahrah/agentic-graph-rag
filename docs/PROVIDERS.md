# Providers

Every model role is swappable. This table shows the local and cloud options and
which config key selects them.

| Role         | Config key            | Local default              | Cloud options                          |
|--------------|-----------------------|----------------------------|----------------------------------------|
| Reply LLM    | `llm.provider`        | `ollama` (gemma4)          | `anthropic` (claude-opus-4-8), `openai`, `gemini` |
| Extraction   | `ingestion.llm`       | `ollama` (gemma4) — defaults to `llm` | any chat provider |
| Embeddings   | `embeddings.provider` | `ollama` (bge-m3) or `sentence_transformers` (bge-m3) | `voyage`, `openai`, `gemini`, `cohere` |
| OCR          | `ocr.vision_llm.provider` | `ollama` (gemma3:4b)   | `gemini` (gemini-2.5-flash); or `tesseract` (offline) |
| Reranker     | `retrieval.rerank.provider` | `ollama` (any chat model) or `cross_encoder` (bge-reranker) | `voyage`, `cohere`, `anthropic`, `openai`, `gemini` |

## How swapping works

All chat models are built through one factory (`llm/factory.py`) and returned as
LangChain chat models, so they share the same `.invoke` / `.astream` /
`.bind_tools` interface. The agent never knows which provider it's talking to.

Embedders implement a tiny `Embedder` interface (`embed_documents`,
`embed_query`). Cloud models are wrapped from their LangChain integrations. Local
models have two routes:

- **`ollama`** — reuses a model you've already pulled, so nothing is downloaded
  twice and the weights stay out of the API/worker images. Ollama owns pooling,
  `max_seq_length`, and `device`; setting those in config logs a warning and has
  no effect. Prefixes, `normalize`, and Matryoshka `dimensions` still apply —
  they're applied to the text and vectors on our side.
- **`sentence_transformers`** — runs the model in-process for full control over
  every knob. Needs the `local-models` extra: it pulls torch, which ships ~2.7 GB
  of CUDA libraries on top of its own 1.2 GB. Install with
  `pip install '.[local-models]'`, or for Docker
  `docker compose build --build-arg EXTRAS='[local-models]'`. Without it the
  provider raises a `ProviderError` naming the extra.

Rerankers come in three shapes, because Ollama serves no cross-encoder endpoint
(`/api/rerank` is not a route — only generate/chat/embed):

| Provider | How it scores | Cost at `candidate_k: 24` |
|----------|---------------|---------------------------|
| `cross_encoder` | local HF model, all pairs in one batched pass | ~0.2s, needs the `local-models` extra + a 2.2 GB model download |
| `ollama` / `anthropic` / `openai` / `gemini` | a chat model rates each pair 0-10 | ~6s, no download |
| `cohere` / `voyage` | hosted rerank endpoint | network round-trip, API key |

Generative reranking is pointwise — one call per candidate — so `candidate_k`
drives its cost directly, and `concurrency` (default 4) hides what it can.
Raising concurrency past Ollama's own parallelism buys nothing.

Quality depends on the model returning a bare number, so `rerank.prompt` is
config-exposed. Candidates the model fails to score keep their retrieval order
rather than being dropped. **Under `ollama` this sets `reasoning: false`**: a
thinking model spends its whole token budget reasoning and returns empty content,
scoring nothing at all — and reasoning is ~8x the latency for no benefit here.
Override via `rerank.extra` (raise `rerank.max_tokens` too if you do).

Not every model tagged "reranker" works this way. A generative reranker must
follow the scoring prompt; some GGUF builds don't, and score every document
identically — test yours before trusting it.

## Running fully local

1. Pull the models into the Ollama on your host:
   ```
   ollama pull gemma4:e4b-it-q4_K_M   # chat + reranking + extraction
   ollama pull gemma3:4b              # OCR
   ollama pull bge-m3                 # embeddings
   ```
2. `make setup PROFILE=local`
3. `make up`

The containers reach your host Ollama at `host.docker.internal:11434`. No API
keys, and no model weights downloaded — the `local` profile runs every role on
Ollama. The only Hugging Face fetch is the bge-m3 *tokenizer* (~17 MB), used to
count chunk sizes exactly; see `embeddings.tokenizer`.

No Ollama on the host? Bring up the bundled service with `--profile local`, set
`GRAPHRAG_OLLAMA_BASE_URL_INTERNAL=http://ollama:11434`, and pull the models
inside that container instead.

### Why the local profile uses two models

Roles have different requirements, and a model that claims to cover several
doesn't always deliver all of them:

- **OCR is `gemma3:4b`, not gemma4.** `gemma4:e4b-it-q4_K_M` lists `vision` in
  `ollama show` and then ignores attached images, replying "please provide the
  image" — indistinguishable, to the pipeline, from a page with no text.
  gemma3:4b transcribes the same handwritten page correctly in ~13s.
- **Extraction is gemma4, not gemma3.** On notes dense with transition tables,
  gemma3:4b ignores "skip document-local labels" and fills the graph with state
  names (`Q0`..`Q16`); gemma4 on the same prompt returns none.

They're 3.3 GB each and won't co-reside on a 6 GB card, so ingest swaps models
once per document. On a larger card both stay resident and it costs nothing.

The lesson generalises: **the capability list is a claim, not a guarantee.** Test
one page, one chunk, one query against the model you plan to use.

### Size the model to the card

A larger model that doesn't fit in VRAM is a *slower* model: Ollama runs the
overflow on CPU, and that costs more than the quality gain is worth. Measured on
a 6 GB card, same prompt, both warm:

| Chat model | VRAM @ ctx 8192 | On GPU | Speed |
|---|---|---|---|
| `gemma4:e4b-it-q4_K_M` | 3.3 GB | **100%** | **41.2 tok/s** |
| `qwen2.5:7b-instruct` | 5.4 GB | 79% | 27.7 tok/s |

qwen2.5 is the stronger model with working tool calling, and it still loses by
~50% here — it can't fit beside the ~1 GB the desktop holds, at any context (82%
on GPU even at 4096). `ollama ps` is the test: below `100% GPU` you're paying for
weights you can't use. On a bigger card this flips, which is why it's a config
key rather than a default.

### Using a bigger Gemma 4 for chat

Gemma 4 has native tool calling across the whole family (including the small
`e4b`), so it works in the normal agentic mode — no special handling. The
`local-gemma` profile swaps in a larger chat model and leaves everything else:

```
ollama pull gemma4:12b        # chat — steadier tool calling
make setup PROFILE=local-gemma
make up
```

## Running on cloud APIs

1. `make setup PROFILE=api`
2. Put the relevant keys in `.env` (see `docs/CONFIGURATION.md`).
3. `make up`

## Adding a new provider

- **LLM:** add a branch in `llm/factory.py`.
- **Embeddings:** add a branch in `embeddings/api_providers.py` (or a new class
  implementing `Embedder`).
- **Store:** implement `GraphStore` / `VectorStore` and register it in
  `storage/__init__.py`.

Nothing else changes — the container wires whatever the config selects.
