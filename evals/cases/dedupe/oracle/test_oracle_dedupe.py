from dedupe import dedupe


def test_order_and_values() -> None:
    assert dedupe([3, 1, 3, 2, 1]) == [3, 1, 2]
    assert dedupe([1, "1", 1]) == [1, "1"]


def test_unhashable_items_are_supported() -> None:
    assert dedupe([[1], [2], [1]]) == [[1], [2]]
    assert dedupe([{"a": 1}, {"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]


def test_input_is_not_modified() -> None:
    data = [2, 2, 1]
    dedupe(data)
    assert data == [2, 2, 1]
