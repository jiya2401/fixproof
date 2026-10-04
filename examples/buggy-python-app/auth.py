def validate_refresh_token(token: str) -> bool:
    """Return True only for refresh tokens.

    Deliberate bug for FixProof M1: the condition is inverted.
    """
    token_type, _, value = token.partition(":")
    if not value:
        return False
    return token_type == "access"
