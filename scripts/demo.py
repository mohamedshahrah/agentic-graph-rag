#!/usr/bin/env python
"""End-to-end smoke test you can run once services are up:

    python scripts/demo.py

Ingests data/sample.md, then asks a graph-flavored question.
"""

from __future__ import annotations

from graphrag.container import Container
from graphrag.pipelines import IngestPipeline, QueryService


def main() -> None:
    container = Container()

    print("Ingesting data/sample.md ...")
    stats = IngestPipeline(container).run("data/sample.md")
    print(f"  chunks={stats.chunks} entities={stats.entities} relations={stats.relations}\n")

    service = QueryService(container)
    question = "How are Acme Robotics and Riverside University connected?"
    print(f"Q: {question}")
    result = service.answer(question, style="detailed")
    print(f"A: {result.answer}\n")
    print("Sources:", ", ".join(sorted({s.source for s in result.sources})))


if __name__ == "__main__":
    main()
