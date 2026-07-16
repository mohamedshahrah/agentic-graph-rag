"""Answer-style resolution."""

from graphrag.agent.styles import style_instruction
from graphrag.core.types import AnswerStyle


def test_known_styles_resolve():
    for style in AnswerStyle:
        assert style_instruction(style)


def test_unknown_style_falls_back_to_detailed():
    assert style_instruction("banana") == style_instruction(AnswerStyle.DETAILED)
