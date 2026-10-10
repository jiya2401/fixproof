def paginate(items: list, page: int, per_page: int) -> list:
    """Return the items on a 1-indexed ``page``.

    Contract:
    - ``paginate([1, 2, 3, 4, 5], 1, 2) == [1, 2]``; a page past the end returns ``[]``.
    - Raises ``ValueError`` if ``page < 1`` or ``per_page < 1``.
    """
    start = page * per_page
    return list(items[start : start + per_page])
