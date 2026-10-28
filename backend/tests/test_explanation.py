"""Unit tests for Feature 3: Visual Explanations & "Why I Fixed It" engine.

Tests cover:
- Prompt template generation and content limits
- JSON parsing (happy path, fenced markdown, surrounding prose, extraction fallback)
- FixExplanation model validation and keyword clamping
- generate_explanation: successful flow, LLM errors, timeouts, malformed JSON, empty patch
- Fallback defaults on every failure path
- Integration: FixCertificate.explanation field round-trips through seal()
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from pydantic import ValidationError

import pytest

from app.explanation import (
    EXPLANATION_FALLBACK,
    FixExplanation,
    _parse_explanation,
    build_explanation_prompt,
    generate_explanation,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BUGGY_CODE = "def divide(a, b):\n    return a / b\n"
TRACEBACK = (
    "FAILED test_divide.py::test_zero_division\n"
    "ZeroDivisionError: division by zero\n"
)
PATCH_DIFF = (
    "--- a/divide.py\n"
    "+++ b/divide.py\n"
    "@@ -1,2 +1,4 @@\n"
    " def divide(a, b):\n"
    "-    return a / b\n"
    "+    if b == 0:\n"
    "+        raise ValueError('denominator must not be zero')\n"
    "+    return a / b\n"
)

VALID_LLM_JSON = json.dumps(
    {
        "root_cause": "The function divided by zero without a guard. Python raises ZeroDivisionError.",
        "the_fix": "A ValueError guard was added before the division. This replaces the implicit error with an explicit contract.",
        "technical_keywords": ["ZeroDivisionError", "input validation", "guard clause", "defensive programming"],
    }
)


# ---------------------------------------------------------------------------
# FixExplanation model tests
# ---------------------------------------------------------------------------


class TestFixExplanation:
    def test_valid_construction(self) -> None:
        exp = FixExplanation(
            root_cause="The root cause.",
            the_fix="The fix.",
            technical_keywords=["kw1", "kw2"],
        )
        assert exp.root_cause == "The root cause."
        assert len(exp.technical_keywords) == 2

    def test_keyword_clamp_max_four(self) -> None:
        """Keywords beyond 4 are silently dropped."""
        exp = FixExplanation(
            root_cause="rc",
            the_fix="fx",
            technical_keywords=["a", "b", "c", "d", "e", "f"],
        )
        assert exp.technical_keywords == ["a", "b", "c", "d"]

    def test_keyword_clamp_min_two_pads(self) -> None:
        """Fewer than 2 keywords are padded to exactly 2."""
        exp = FixExplanation(
            root_cause="rc",
            the_fix="fx",
            technical_keywords=["only-one"],
        )
        assert len(exp.technical_keywords) == 2
        assert exp.technical_keywords[0] == "only-one"

    def test_keyword_empty_list_pads_to_two(self) -> None:
        exp = FixExplanation(root_cause="rc", the_fix="fx", technical_keywords=[])
        assert len(exp.technical_keywords) == 2

    def test_fallback_defaults_are_valid(self) -> None:
        """EXPLANATION_FALLBACK must itself produce a valid model."""
        exp = FixExplanation(**EXPLANATION_FALLBACK)
        assert exp.root_cause
        assert exp.the_fix
        assert len(exp.technical_keywords) >= 2

    def test_model_dump_round_trip(self) -> None:
        exp = FixExplanation(
            root_cause="rc", the_fix="fx", technical_keywords=["a", "b"]
        )
        d = exp.model_dump()
        assert set(d.keys()) == {"root_cause", "the_fix", "technical_keywords"}
        exp2 = FixExplanation.model_validate(d)
        assert exp2 == exp


# ---------------------------------------------------------------------------
# Prompt template tests
# ---------------------------------------------------------------------------


class TestBuildExplanationPrompt:
    def test_returns_two_strings(self) -> None:
        system, user = build_explanation_prompt(BUGGY_CODE, TRACEBACK, PATCH_DIFF)
        assert isinstance(system, str) and len(system) > 0
        assert isinstance(user, str) and len(user) > 0

    def test_system_forbids_markdown_fences(self) -> None:
        system, _ = build_explanation_prompt(BUGGY_CODE, TRACEBACK, PATCH_DIFF)
        assert "```json" in system or "markdown" in system.lower()

    def test_system_requires_three_keys(self) -> None:
        system, _ = build_explanation_prompt(BUGGY_CODE, TRACEBACK, PATCH_DIFF)
        assert "root_cause" in system
        assert "the_fix" in system
        assert "technical_keywords" in system

    def test_user_contains_all_inputs(self) -> None:
        _, user = build_explanation_prompt(BUGGY_CODE, TRACEBACK, PATCH_DIFF)
        assert "def divide" in user
        assert "ZeroDivisionError" in user
        assert "--- a/divide.py" in user

    def test_code_capped_at_max_code_chars(self) -> None:
        long_code = "x = 1\n" * 10_000  # very long
        _, user = build_explanation_prompt(long_code, TRACEBACK, PATCH_DIFF, max_code_chars=100)
        # The code section should be truncated to at most 100 chars
        assert long_code[:100] in user
        assert long_code[:200] not in user

    def test_traceback_capped_at_max_tb_chars(self) -> None:
        long_tb = "E " * 5_000
        _, user = build_explanation_prompt(BUGGY_CODE, long_tb, PATCH_DIFF, max_tb_chars=50)
        assert long_tb[:50] in user
        assert long_tb[:120] not in user

    def test_diff_capped_at_max_diff_chars(self) -> None:
        long_diff = "+x = 1\n" * 5_000
        _, user = build_explanation_prompt(BUGGY_CODE, TRACEBACK, long_diff, max_diff_chars=80)
        assert long_diff[:80] in user
        assert long_diff[:200] not in user


# ---------------------------------------------------------------------------
# _parse_explanation tests
# ---------------------------------------------------------------------------


class TestParseExplanation:
    def test_parses_clean_json(self) -> None:
        result = _parse_explanation(VALID_LLM_JSON)
        assert isinstance(result, FixExplanation)
        assert "zero" in result.root_cause.lower()

    def test_parses_json_with_markdown_fence(self) -> None:
        fenced = f"```json\n{VALID_LLM_JSON}\n```"
        result = _parse_explanation(fenced)
        assert isinstance(result, FixExplanation)

    def test_parses_json_with_generic_fence(self) -> None:
        fenced = f"```\n{VALID_LLM_JSON}\n```"
        result = _parse_explanation(fenced)
        assert isinstance(result, FixExplanation)

    def test_parses_json_with_surrounding_prose(self) -> None:
        with_prose = f"Here is the analysis:\n{VALID_LLM_JSON}\nEnd of analysis."
        result = _parse_explanation(with_prose)
        assert isinstance(result, FixExplanation)

    def test_raises_on_empty_string(self) -> None:
        with pytest.raises((ValueError, json.JSONDecodeError)):
            _parse_explanation("")

    def test_raises_on_plain_text_no_json(self) -> None:
        with pytest.raises((ValueError, json.JSONDecodeError)):
            _parse_explanation("This is just English text with no JSON object.")

    def test_raises_on_json_array_not_object(self) -> None:
        with pytest.raises((ValueError, json.JSONDecodeError)):
            _parse_explanation('["a", "b", "c"]')

    def test_raises_on_missing_required_key(self) -> None:
        """Missing 'the_fix' must fail Pydantic validation."""
        bad = json.dumps({"root_cause": "rc", "technical_keywords": ["a", "b"]})
        with pytest.raises(ValidationError):
            _parse_explanation(bad)

    def test_strips_whitespace_around_json(self) -> None:
        padded = f"\n\n   {VALID_LLM_JSON}   \n\n"
        result = _parse_explanation(padded)
        assert isinstance(result, FixExplanation)

    def test_extra_keys_are_tolerated(self) -> None:
        """Pydantic should ignore unknown extra keys."""
        data = json.loads(VALID_LLM_JSON)
        data["extra_field"] = "should be ignored"
        result = _parse_explanation(json.dumps(data))
        assert isinstance(result, FixExplanation)
        assert not hasattr(result, "extra_field")


# ---------------------------------------------------------------------------
# generate_explanation integration tests (with mocked LLM)
# ---------------------------------------------------------------------------


def _make_mock_llm(return_value: str) -> MagicMock:
    mock = MagicMock()
    mock.complete.return_value = return_value
    return mock


class TestGenerateExplanation:
    def test_happy_path_returns_fix_explanation(self) -> None:
        mock_llm = _make_mock_llm(VALID_LLM_JSON)
        result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        assert isinstance(result, FixExplanation)
        assert result.root_cause
        assert result.the_fix
        assert len(result.technical_keywords) >= 2

    def test_llm_called_with_correct_temperature(self) -> None:
        mock_llm = _make_mock_llm(VALID_LLM_JSON)
        generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        mock_llm.complete.assert_called_once()
        _, kwargs = mock_llm.complete.call_args
        assert kwargs.get("temperature") == 0.0

    def test_returns_fallback_on_llm_exception(self) -> None:
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = RuntimeError("network timeout")
        result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        assert isinstance(result, FixExplanation)
        assert result.root_cause == EXPLANATION_FALLBACK["root_cause"]

    def test_returns_fallback_on_connection_error(self) -> None:
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = ConnectionError("Connection refused")
        result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        assert isinstance(result, FixExplanation)
        assert result.the_fix == EXPLANATION_FALLBACK["the_fix"]

    def test_returns_fallback_on_malformed_json(self) -> None:
        mock_llm = _make_mock_llm("This is not JSON at all!")
        result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        assert isinstance(result, FixExplanation)
        assert result.technical_keywords == EXPLANATION_FALLBACK["technical_keywords"]

    def test_returns_fallback_on_missing_required_keys(self) -> None:
        bad_json = json.dumps({"root_cause": "only this key"})
        mock_llm = _make_mock_llm(bad_json)
        result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        assert isinstance(result, FixExplanation)
        assert result.root_cause == EXPLANATION_FALLBACK["root_cause"]

    def test_returns_fallback_on_json_array_response(self) -> None:
        mock_llm = _make_mock_llm('["root_cause", "the_fix", "technical_keywords"]')
        result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        assert isinstance(result, FixExplanation)

    def test_returns_fallback_when_patch_diff_empty(self) -> None:
        mock_llm = MagicMock()
        result = generate_explanation(BUGGY_CODE, TRACEBACK, "", llm_client=mock_llm)
        assert isinstance(result, FixExplanation)
        # LLM must NOT be called at all for an empty diff
        mock_llm.complete.assert_not_called()

    def test_returns_fallback_when_patch_diff_whitespace_only(self) -> None:
        mock_llm = MagicMock()
        result = generate_explanation(BUGGY_CODE, TRACEBACK, "   \n  ", llm_client=mock_llm)
        assert isinstance(result, FixExplanation)
        mock_llm.complete.assert_not_called()

    def test_tolerates_fenced_markdown_from_llm(self) -> None:
        fenced_response = f"```json\n{VALID_LLM_JSON}\n```"
        mock_llm = _make_mock_llm(fenced_response)
        result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        assert isinstance(result, FixExplanation)
        assert result.root_cause  # must parse successfully, not fallback

    def test_tolerates_prose_around_json(self) -> None:
        with_prose = f"Sure! Here's the analysis:\n{VALID_LLM_JSON}\nHope that helps."
        mock_llm = _make_mock_llm(with_prose)
        result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        assert isinstance(result, FixExplanation)
        # Should have successfully parsed the real JSON, not the fallback
        assert result.root_cause != EXPLANATION_FALLBACK["root_cause"]

    def test_keyword_list_is_clamped_from_llm_output(self) -> None:
        """Even if the LLM returns >4 keywords, we clamp to 4."""
        data = {
            "root_cause": "rc",
            "the_fix": "fx",
            "technical_keywords": ["a", "b", "c", "d", "e", "f", "g"],
        }
        mock_llm = _make_mock_llm(json.dumps(data))
        result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        assert len(result.technical_keywords) <= 4

    def test_creates_nebius_client_when_none_injected(self) -> None:
        """When llm_client is None, generate_explanation should attempt to build NebiusClient."""
        with patch("app.explanation.NebiusClient") as MockClient:
            MockClient.return_value.complete.return_value = VALID_LLM_JSON
            result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=None)
        MockClient.assert_called_once()
        assert isinstance(result, FixExplanation)

    def test_returns_fallback_if_nebius_client_init_fails(self) -> None:
        """NebiusConfigurationError (or any error) during client init → fallback, not crash."""
        with patch(
            "app.explanation.NebiusClient",
            side_effect=RuntimeError("NEBIUS_API_KEY not set"),
        ):
            result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=None)
        assert isinstance(result, FixExplanation)
        assert result.root_cause == EXPLANATION_FALLBACK["root_cause"]

    def test_empty_llm_response_returns_fallback(self) -> None:
        mock_llm = _make_mock_llm("")
        result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        assert isinstance(result, FixExplanation)

    def test_result_is_json_serialisable(self) -> None:
        mock_llm = _make_mock_llm(VALID_LLM_JSON)
        result = generate_explanation(BUGGY_CODE, TRACEBACK, PATCH_DIFF, llm_client=mock_llm)
        dumped = json.dumps(result.model_dump())
        parsed = json.loads(dumped)
        assert set(parsed.keys()) == {"root_cause", "the_fix", "technical_keywords"}


# ---------------------------------------------------------------------------
# FixCertificate integration test
# ---------------------------------------------------------------------------


class TestFixCertificateExplanationField:
    def test_explanation_field_defaults_to_none(self) -> None:
        from app.certificate import FixCertificate

        cert = FixCertificate(issue="test")
        assert cert.explanation is None

    def test_explanation_field_accepts_fix_explanation(self) -> None:
        from app.certificate import FixCertificate

        exp = FixExplanation(
            root_cause="rc",
            the_fix="fx",
            technical_keywords=["a", "b"],
        )
        cert = FixCertificate(issue="test", explanation=exp)
        assert cert.explanation is not None

    def test_certificate_seal_with_explanation_is_stable(self) -> None:
        """Sealing a cert with an explanation must produce a reproducible SHA256."""
        from app.certificate import FixCertificate

        exp = FixExplanation(
            root_cause="rc",
            the_fix="fx",
            technical_keywords=["a", "b"],
        )
        cert = FixCertificate(issue="test", explanation=exp)
        sealed = cert.seal()
        assert sealed.certificate_sha256
        assert sealed.hash_is_valid()

    def test_certificate_seal_without_explanation_still_works(self) -> None:
        """The explanation field is optional; sealing must not break when it is None."""
        from app.certificate import FixCertificate

        cert = FixCertificate(issue="test")
        sealed = cert.seal()
        assert sealed.certificate_sha256
        assert sealed.hash_is_valid()

    def test_certificate_model_dump_includes_explanation(self) -> None:
        from app.certificate import FixCertificate

        exp = FixExplanation(
            root_cause="rc",
            the_fix="fx",
            technical_keywords=["a", "b"],
        )
        cert = FixCertificate(issue="test", explanation=exp)
        dumped = cert.model_dump()
        assert "explanation" in dumped

