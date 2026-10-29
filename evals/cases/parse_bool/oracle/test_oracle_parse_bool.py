import pytest
from parse_bool import parse_bool


@pytest.mark.parametrize("value", ["yes", "on", "1", " TRUE ", "True", True])
def test_truthy(value) -> None:
    assert parse_bool(value) is True


@pytest.mark.parametrize("value", ["no", "off", "0", " FALSE ", "False", False])
def test_falsy(value) -> None:
    assert parse_bool(value) is False


@pytest.mark.parametrize("value", ["maybe", "", None, 1, 2.5])
def test_everything_else_raises(value) -> None:
    with pytest.raises(ValueError):
        parse_bool(value)
