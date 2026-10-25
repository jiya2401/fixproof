from parse_bool import parse_bool


def test_false_string_is_false() -> None:
    assert parse_bool("false") is False


def test_true_values_are_true() -> None:
    assert parse_bool("true") is True
    assert parse_bool(True) is True
