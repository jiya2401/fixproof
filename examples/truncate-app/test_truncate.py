from truncate import truncate


def test_long_text_fits_the_width() -> None:
    assert truncate("hello world", 8) == "hello..."


def test_empty_suffix() -> None:
    assert truncate("abc", 10, "") == "abc"
