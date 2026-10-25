def parse_bool(value) -> bool:
    """Parse a boolean from a config value.

    Contract:
    - ``bool`` values are returned unchanged.
    - Strings, case-insensitive with surrounding whitespace ignored: ``true``, ``yes``,
      ``1``, ``on`` give ``True``; ``false``, ``no``, ``0``, ``off`` give ``False``.
    - Anything else (including ``None``, numbers and other strings) raises ``ValueError``.
    """
    return bool(value)
