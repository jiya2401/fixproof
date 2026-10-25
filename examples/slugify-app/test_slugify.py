from slugify import slugify


def test_two_words_are_joined_with_a_dash() -> None:
    assert slugify("Hello World") == "hello-world"


def test_already_a_slug_is_unchanged() -> None:
    assert slugify("abc") == "abc"
