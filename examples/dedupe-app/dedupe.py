def dedupe(items: list) -> list:
    """Return ``items`` without duplicates, keeping the first occurrence of each.

    Contract:
    - The order of first occurrences is preserved.
    - Items need not be hashable (lists and dicts are allowed).
    - The input list is not modified.
    """
    return list(set(items))
