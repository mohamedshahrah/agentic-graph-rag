# Optimization notes: KV-cache & vector quantization

Two recent Google Research quantization methods were evaluated for this project.
This note records what they do and, honestly, where each does and doesn't fit.

## PolarQuant — belongs to the inference engine, not this repo

**Paper:** *PolarQuant: Leveraging Polar Transformation for Efficient Key Cache
Quantization and Decoding Acceleration* (KAIST + Google Research,
[arXiv:2502.00527](https://arxiv.org/abs/2502.00527)).

**What it does:** compresses the LLM's **KV (key) cache** during decoding. It
random-preconditions key embeddings, converts them to polar coordinates via a
recursive algorithm, and quantizes the angles — whose distribution is tightly
bounded, so no explicit normalization is needed. It reports ~4.2× KV-cache
compression and accelerates decoding by turning the query–key inner product into
a table lookup, at full-precision quality.

**Where it applies here:** the **LLM serving layer** — inside Ollama / vLLM /
llama.cpp's attention. This project *calls* an LLM; it does not run the attention
mechanism. So **there is nothing to implement in this codebase.** The realistic
action is operational: for long agent runs, choose a serving backend that
supports KV-cache quantization. We already run quantized *weights*
(`gemma4:e4b-q4_K_M`); KV-cache quantization is a separate, engine-side feature.

## TurboQuant — belongs to the vector layer (the applicable one)

**Paper:** *TurboQuant: Online Vector Quantization with Near-optimal Distortion
Rate* (Google Research / DeepMind + NYU,
[arXiv:2504.19874](https://arxiv.org/abs/2504.19874)).

**What it does:** a **data-oblivious, online** vector quantizer for
high-dimensional Euclidean vectors. It randomly rotates vectors (inducing a
concentrated Beta distribution per coordinate), applies optimal per-coordinate
scalar quantizers, and — for unbiased inner-product estimation — adds a 1-bit
Quantized-JL transform on the residual. It reaches near-optimal distortion at all
bit-widths and, for **nearest-neighbor search, beats product quantization on
recall while cutting index time and memory.**

**Where it applies here:** directly at the **embedding / vector-index** layer —
which is also where our memory footprint lives. This is the one worth pursuing.

**Why it isn't a drop-in today:** the default vector store is **Neo4j's native
vector index**, which stores float32 and runs its own ANN — there's no hook to
insert a custom quantized codec. To use TurboQuant for real we'd need a vector
backend that accepts a custom quantizer.

**The clean path (already scaffolded):** the `VectorStore` interface
(`src/graphrag/storage/vector/base.py`) is exactly the seam. A follow-up would:

1. Add a `VectorStore` adapter over a quantization-capable engine (FAISS / Qdrant
   / LanceDB) selectable via `storage.vector.provider`.
2. Implement a TurboQuant-style scalar quantizer (rotation → per-coordinate
   scalar quantization → optional QJL residual) as the codec.
3. Store quantized codes + keep the rotation seed; dequantize / use asymmetric
   distance at query time.

Expected payoff: materially lower vector memory (the user's stated goal) with
near-neutral recall. It's a real, self-contained project — not a config flag —
and should be built against a faithful reference and measured on a recall
benchmark, not dropped in unverified.
