from merge_intervals import merge_intervals


def test_unsorted_input_is_merged() -> None:
    assert merge_intervals([(5, 6), (1, 3), (2, 4)]) == [(1, 4), (5, 6)]


def test_empty_and_disjoint_sorted_input() -> None:
    assert merge_intervals([]) == []
    assert merge_intervals([(1, 2), (5, 6)]) == [(1, 2), (5, 6)]
