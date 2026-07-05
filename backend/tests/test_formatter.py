# backend/tests/test_formatter.py
from backend.utils import format_output


def test_strips_leading_trailing_whitespace():
    assert format_output("  hello world  ") == "hello world"


def test_collapses_triple_newlines():
    assert format_output("line1\n\n\n\n\nline2") == "line1\n\nline2"


def test_leaves_double_newlines_intact():
    text = "para one\n\npara two"
    assert format_output(text) == text


def test_empty_string():
    assert format_output("") == ""