import pytest
from truncate import truncate


def test_truncation_is_exactly_width() -> None:
    assert truncate("hello world", 8) == "hello..."
    assert truncate("hello!", 5) == "he..."
    assert truncate("abcdef", 4, "\u2026") == "abc\u2026"


def test_short_text_is_unchanged() -> None:
    assert truncate("hi", 10) == "hi"
    assert truncate("hello", 5) == "hello"


def test_width_smaller_than_suffix_raises() -> None:
    with pytest.raises(ValueError):
        truncate("hello", 2)
