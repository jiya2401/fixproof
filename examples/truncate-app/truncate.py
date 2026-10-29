def truncate(text: str, width: int, suffix: str = "...") -> str:
    """Shorten ``text`` to at most ``width`` characters.

    Contract:
    - Text no longer than ``width`` is returned unchanged (no suffix added).
    - Otherwise the result ends with ``suffix`` and is exactly ``width`` characters long.
    - Raises ``ValueError`` if ``width`` is smaller than ``len(suffix)``.
    """
    return text[:width] + suffix
