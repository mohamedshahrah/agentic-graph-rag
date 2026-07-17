#!/usr/bin/env python
"""Score retrieval and answers against the golden set in data/eval/qa.yaml.

    python scripts/eval.py               # retrieval + answer keyword checks
    python scripts/eval.py --no-answers  # retrieval only (no LLM calls, fast)
    python scripts/eval.py --judge       # + LLM-judged faithfulness
    python scripts/eval.py --strict      # non-zero exit if any check fails (CI)

Needs the stack (Neo4j, and the model backends the profile selects) running.
Ingests data/sample.md first, so it is self-contained on a fresh database.

Three scores per question:
  retrieval  did the expected source appear in the top-k chunks?
  answer     did the answer contain the expected keywords?
  faithful   (--judge) does the answer follow from the retrieved chunks,
             according to the configured LLM?

The point of this file: every retrieval change is a guess until it moves these
numbers. Run it before and after.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from graphrag.container import Container  # noqa: E402
from graphrag.pipelines import IngestPipeline, QueryService  # noqa: E402

_JUDGE_PROMPT = (
    "Question: {question}\n\nRetrieved evidence:\n{evidence}\n\n"
    "Proposed answer:\n{answer}\n\n"
    "Does the answer follow from the evidence, without inventing facts? "
    "Reply with exactly YES or NO."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-answers", action="store_true", help="skip agent answers")
    parser.add_argument("--judge", action="store_true", help="LLM-judge faithfulness")
    parser.add_argument("--strict", action="store_true", help="exit 1 on any failure")
    parser.add_argument("--user", default="default")
    args = parser.parse_args()

    cases = yaml.safe_load((ROOT / "data" / "eval" / "qa.yaml").read_text(encoding="utf-8"))
    container = Container()
    service = QueryService(container)

    print("Ingesting data/sample.md (idempotent) ...")
    IngestPipeline(container).run(ROOT / "data" / "sample.md", user_id=args.user)

    retrieval_hits = answer_hits = faithful_hits = 0
    answers_run = judged = 0
    failures: list[str] = []

    for case in cases:
        question = case["question"]
        keywords = [str(k) for k in case.get("expect_keywords", [])]
        source = str(case.get("expect_source", ""))

        chunks = service.search(question, k=8, user_id=args.user)
        got_source = any(source in c.source for c in chunks) if source else bool(chunks)
        retrieval_hits += got_source
        if not got_source:
            failures.append(f"retrieval missed '{source}' for: {question}")

        line = f"  [{'ok' if got_source else 'MISS'}] retrieval"

        if not args.no_answers:
            answers_run += 1
            result = service.answer(question, user_id=args.user)
            text = result.answer.lower()
            hit_kw = [k for k in keywords if k.lower() in text]
            ok = len(hit_kw) == len(keywords)
            answer_hits += ok
            if not ok:
                missing = sorted(set(keywords) - set(hit_kw))
                failures.append(f"answer missing {missing} for: {question}")
            line += f" · [{'ok' if ok else 'MISS'}] answer ({len(hit_kw)}/{len(keywords)} keywords)"

            if args.judge and result.answer.strip():
                judged += 1
                evidence = "\n---\n".join(c.text[:600] for c in result.sources[:6])
                verdict = container.llm.invoke(
                    _JUDGE_PROMPT.format(
                        question=question, evidence=evidence, answer=result.answer
                    )
                )
                verdict_text = str(verdict.content).strip().upper()
                faithful = verdict_text.startswith("YES")
                faithful_hits += faithful
                if not faithful:
                    failures.append(f"judge says unfaithful: {question}")
                line += f" · [{'ok' if faithful else 'MISS'}] faithful"

        print(f"\nQ: {question}\n{line}")

    total = len(cases)
    print(f"\n{'=' * 60}")
    print(f"retrieval : {retrieval_hits}/{total}")
    if answers_run:
        print(f"answers   : {answer_hits}/{answers_run}")
    if judged:
        print(f"faithful  : {faithful_hits}/{judged}")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
    return 1 if (args.strict and failures) else 0


if __name__ == "__main__":
    raise SystemExit(main())
