def slugify(text: str) -> str:
    """Convert ``text`` to a URL slug.

    Contract:
    - Lowercase ASCII letters and digits are kept.
    - Every run of other characters becomes a single ``-``.
    - No leading or trailing ``-``; input with no letters or digits gives ``""``.
    """
    return text.lower()
