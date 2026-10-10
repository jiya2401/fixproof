import pytest
from paginate import paginate


def test_pages() -> None:
    data = list(range(1, 8))
    assert paginate(data, 1, 3) == [1, 2, 3]
    assert paginate(data, 2, 3) == [4, 5, 6]
    assert paginate(data, 3, 3) == [7]
    assert paginate(data, 4, 3) == []


@pytest.mark.parametrize("page,per_page", [(0, 3), (-1, 3), (1, 0), (1, -2)])
def test_invalid_arguments_raise(page: int, per_page: int) -> None:
    with pytest.raises(ValueError):
        paginate([1, 2, 3], page, per_page)
