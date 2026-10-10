from paginate import paginate


def test_second_page_returns_items_4_to_6() -> None:
    assert paginate([1, 2, 3, 4, 5, 6, 7], 2, 3) == [4, 5, 6]


def test_empty_input_returns_empty_list() -> None:
    assert paginate([], 1, 3) == []
