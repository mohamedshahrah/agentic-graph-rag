"""Answer styles. The requested style is injected into the prompt so the same
retrieval can be phrased for different audiences."""

from __future__ import annotations

from graphrag.core.types import AnswerStyle

_STYLE_INSTRUCTIONS: dict[AnswerStyle, str] = {
    AnswerStyle.CONCISE: "Answer in 2-4 sentences. Lead with the direct answer. No preamble.",
    AnswerStyle.DETAILED: (
        "Give a thorough, well-structured answer with short paragraphs or bullet points. "
        "Explain the reasoning and connect related facts."
    ),
    AnswerStyle.TECHNICAL: (
        "Answer for an expert. Use precise terminology, include specifics (names, numbers, "
        "relationships), and don't over-explain basics."
    ),
    AnswerStyle.ELI5: (
        "Explain simply, as if to a curious beginner. Use plain words and a short analogy "
        "where it helps."
    ),
}


def style_instruction(style: str | AnswerStyle) -> str:
    try:
        style = AnswerStyle(style)
    except ValueError:
        style = AnswerStyle.DETAILED
    return _STYLE_INSTRUCTIONS[style]
