#!/usr/bin/env python
"""Synthetic traffic generator — sends realistic traces to a running llmlens.

    python examples/generate_traffic.py                 # steady traffic
    python examples/generate_traffic.py --spike         # cost + error spike (trips alerts)
    python examples/generate_traffic.py --count 500 --rate 50

It uses the SDK's low-level API and fabricates timestamps so it can produce
varied latencies/costs/errors quickly (cost is computed server-side from tokens).
"""

from __future__ import annotations

import argparse
import random
import time
from datetime import datetime, timedelta, timezone

import llmlens
from llmlens.tracer import finish, start

MODELS = [
    ("openai", "gpt-4o", 0.4),
    ("openai", "gpt-4o-mini", 0.9),
    ("anthropic", "claude-opus-4-8", 0.6),
    ("anthropic", "claude-haiku-4-5", 0.95),
    ("google", "gemini-2.5-flash", 0.8),
]
USERS = ["alice", "bob", "carol", "dave", "erin"]
PROMPTS = [
    "Summarize the quarterly report.",
    "What is the capital of France?",
    "Write a haiku about databases.",
    "Explain vector search to a beginner.",
    "Translate 'hello' into Japanese.",
]


def _fabricate(error_rate: float, spike: bool) -> None:
    provider, model, speed = random.choice(MODELS)
    user = random.choice(USERS)
    now = datetime.now(timezone.utc)

    latency = random.uniform(0.2, 1.2) / speed
    if spike:
        latency *= random.uniform(3, 8)
    is_error = random.random() < (0.4 if spike else error_rate)

    root = start("chat_request", kind="trace")
    root.user_id, root.tags = user, ["demo"]
    root.start_time, root.end_time = now - timedelta(seconds=latency + 0.05), now

    retr = start("retrieve", kind="tool", trace_id=root.trace_id, parent_span_id=root.span_id)
    retr.start_time = root.start_time
    retr.end_time = root.start_time + timedelta(seconds=0.03)
    retr.output("retrieved 3 documents", role="tool_output")
    finish(retr)

    gen = start(f"chat {model}", kind="generation", trace_id=root.trace_id,
                parent_span_id=root.span_id, provider=provider, model=model)
    gen.start_time = retr.end_time
    gen.end_time = now
    gen.input(random.choice(PROMPTS), role="user")
    in_tok = random.randint(200, 2000) * (5 if spike else 1)
    out_tok = random.randint(50, 800) * (5 if spike else 1)
    gen.usage(in_tok, out_tok)
    if is_error:
        gen.error("RateLimitError: 429 Too Many Requests")
    else:
        gen.output("Here is a helpful answer based on the retrieved context.")
    finish(gen)
    finish(root)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--rate", type=float, default=20, help="traces per second")
    ap.add_argument("--error-rate", type=float, default=0.05)
    ap.add_argument("--spike", action="store_true", help="generate a cost + error spike")
    args = ap.parse_args()

    llmlens.configure()  # reads LLMLENS_URL / LLMLENS_API_KEY from env
    print(f"Sending {args.count} traces to {llmlens.get_config().url} ...")
    interval = 1.0 / max(1.0, args.rate)
    for i in range(args.count):
        _fabricate(args.error_rate, args.spike)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{args.count}")
        time.sleep(interval)
    llmlens.flush()
    print("Done. Open the dashboard to see traces, cost, latency, and (with --spike) alerts.")


if __name__ == "__main__":
    main()
