from merge_intervals import merge_intervals


def test_unsorted_overlap() -> None:
    assert merge_intervals([(5, 6), (1, 3), (2, 4)]) == [(1, 4), (5, 6)]


def test_touching_intervals_merge() -> None:
    assert merge_intervals([(1, 2), (2, 3)]) == [(1, 3)]


def test_contained_interval_keeps_outer_end() -> None:
    assert merge_intervals([(1, 10), (2, 3)]) == [(1, 10)]


def test_input_not_modified_and_edge_cases() -> None:
    data = [(3, 4), (1, 2)]
    assert merge_intervals(data) == [(1, 2), (3, 4)]
    assert data == [(3, 4), (1, 2)]
    assert merge_intervals([]) == []
    assert merge_intervals([(7, 8)]) == [(7, 8)]
