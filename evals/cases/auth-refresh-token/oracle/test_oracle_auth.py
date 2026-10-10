import pytest
from auth import validate_refresh_token


def test_refresh_accepted() -> None:
    assert validate_refresh_token("refresh:abc123") is True


@pytest.mark.parametrize(
    "token", ["access:abc123", "other:abc123", "refresh:", "refresh", "", "access:refresh"]
)
def test_everything_else_rejected(token: str) -> None:
    assert validate_refresh_token(token) is False
