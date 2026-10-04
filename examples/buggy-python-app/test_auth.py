from auth import validate_refresh_token


def test_refresh_token_is_accepted() -> None:
    assert validate_refresh_token("refresh:abc123") is True


def test_access_token_is_rejected() -> None:
    assert validate_refresh_token("access:abc123") is False
