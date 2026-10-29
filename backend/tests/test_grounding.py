from app.verification.grounding import build_spec_corpus, check_grounding


def test_quote_must_appear_verbatim_ignoring_case_and_whitespace(auth_src) -> None:
    corpus = build_spec_corpus("Refresh tokens are rejected.", auth_src)
    assert check_grounding("return  true ONLY for refresh tokens.", corpus)[0]
    assert check_grounding("refresh tokens are rejected", corpus)[0]
    assert not check_grounding("tokens may contain whitespace", corpus)[0]


def test_short_or_empty_quotes_never_ground(auth_src) -> None:
    corpus = build_spec_corpus("a", auth_src)
    assert not check_grounding("", corpus)[0]
    assert not check_grounding("refresh", corpus)[0]


def test_corpus_comes_from_the_given_source_only(tmp_path) -> None:
    (tmp_path / "m.py").write_text('def f():\n    """Only original docs count here."""\n')
    corpus = build_spec_corpus("issue", tmp_path)
    assert check_grounding("Only original docs count here", corpus)[0]
    # a docstring added later by a patch is not in the pre-patch corpus
    assert not check_grounding("A sentence added by the patch", corpus)[0]


def test_test_files_are_not_a_source_of_spec(tmp_path) -> None:
    (tmp_path / "test_x.py").write_text('def test_a():\n    """Tests may claim anything."""\n')
    assert not check_grounding("Tests may claim anything", build_spec_corpus("i", tmp_path))[0]
