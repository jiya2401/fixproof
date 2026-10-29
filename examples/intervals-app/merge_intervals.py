def merge_intervals(intervals: list) -> list:
    """Merge intervals given as ``(start, end)`` tuples.

    Contract:
    - The input may be unsorted.
    - Intervals that overlap or touch (``end == next start``) are merged.
    - Returns a new sorted list of ``(start, end)`` tuples; the input is not modified.
    """
    merged = []
    for start, end in intervals:
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged
