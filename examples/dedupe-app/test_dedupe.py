from dedupe import dedupe


def test_first_occurrence_order_is_kept() -> None:
    assert dedupe([3, 1, 3, 2]) == [3, 1, 2]


def test_empty_list() -> None:
    assert dedupe([]) == []
