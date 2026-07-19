"""Flattening LLM reply content to text.

The bug this guards: Gemini and Anthropic return `.content` as a list of blocks,
and `str()` on that list is a Python repr — which broke graph extraction, OCR,
and community summaries silently (they parsed the repr and found nothing).
"""

from graphrag.core.messages import content_to_text


def test_plain_string_passes_through():
    assert content_to_text("hello world") == "hello world"


def test_block_list_is_flattened_to_its_text():
    """The exact shape Gemini 3.5 Flash returns."""
    content = [{"type": "text", "text": '```json\n{"entities": []}\n```'}]
    assert content_to_text(content) == '```json\n{"entities": []}\n```'


def test_multiple_text_blocks_are_concatenated():
    content = [
        {"type": "text", "text": "Acme "},
        {"type": "text", "text": "Robotics"},
    ]
    assert content_to_text(content) == "Acme Robotics"


def test_non_text_blocks_are_skipped():
    """Reasoning traces and images must not leak into parsed text."""
    content = [
        {"type": "thinking", "thinking": "hmm"},
        {"type": "text", "text": "the answer"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]
    assert content_to_text(content) == "the answer"


def test_bare_strings_in_a_list_are_kept():
    assert content_to_text(["a", "b"]) == "ab"


def test_objects_exposing_text_are_read():
    class Block:
        text = "from an object"

    assert content_to_text([Block()]) == "from an object"


def test_the_repr_trap_it_exists_to_prevent():
    """`str(list)` would have embedded the JSON in a Python repr; the helper
    must return parseable text instead."""
    content = [{"type": "text", "text": '{"k": "v"}'}]
    import json

    assert json.loads(content_to_text(content)) == {"k": "v"}


def test_empty_and_odd_inputs_do_not_raise():
    assert content_to_text([]) == ""
    assert content_to_text(None) == "None"
    assert content_to_text(42) == "42"
