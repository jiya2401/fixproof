import pytest
from slugify import slugify


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hello World", "hello-world"),
        ("Hello,   World!!", "hello-world"),
        ("  a  ", "a"),
        ("---x---", "x"),
        ("", ""),
        ("!!!", ""),
        ("a_b c", "a-b-c"),
        ("Version 2.0", "version-2-0"),
    ],
)
def test_slugify_contract(text: str, expected: str) -> None:
    assert slugify(text) == expected
