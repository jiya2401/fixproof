import pytest

from app.agents.parsing import parse_patch_reply, parse_verification_reply
from tests.conftest import fixture_text
from tests.test_llm_client import make_client

DIFF = fixture_text("auth_correct.diff")  # contains double quotes: the JSON failure mode


def test_patch_reply_with_quotes_parses() -> None:
    raw = f"SUMMARY: flip condition\nRATIONALE: inverted\n```diff\n{DIFF}```\n"
    patch = parse_patch_reply(raw)
    assert patch.summary == "flip condition" and '"refresh"' in patch.diff
    assert patch.diff.endswith("\n")


def test_patch_reply_without_diff_block_rejected() -> None:
    with pytest.raises(ValueError):
        parse_patch_reply("SUMMARY: x\nno code")
    with pytest.raises(ValueError):
        parse_patch_reply("```diff\njust text\n```")


def test_verification_reply_parses_multiple_tests() -> None:
    raw = (
        "### TEST empty_value\nRATIONALE: empty value\n"
        "SPEC: Return True only for refresh tokens\n```python\n"
        "from auth import validate_refresh_token\n\ndef test_a():\n"
        '    assert not validate_refresh_token("refresh:")\n```\n'
        "### TEST other_type\n```python\ndef test_b():\n    assert True\n```\n"
        "INVARIANT: only refresh accepted\nRISK: prefix handling\n"
    )
    plan = parse_verification_reply(raw)
    assert [t.name for t in plan.tests] == ["empty_value", "other_type"]
    assert '"refresh:"' in plan.tests[0].code
    assert plan.tests[0].spec_quote == "Return True only for refresh tokens"
    assert plan.tests[1].spec_quote == ""
    assert plan.invariants == ["only refresh accepted"] and plan.risk_areas == ["prefix handling"]


def test_verification_reply_without_tests_rejected() -> None:
    with pytest.raises(ValueError):
        parse_verification_reply("I think it is fine.")


def test_complete_parsed_retries_once_then_succeeds() -> None:
    good = f"SUMMARY: s\n```diff\n{DIFF}```"
    client = make_client(["oops", good])
    assert "refresh" in client.complete_parsed(system="s", user="u", parser=parse_patch_reply).diff
    assert client.usage.retries_for_malformed_output == 1
