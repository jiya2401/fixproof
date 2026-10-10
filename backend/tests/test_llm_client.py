import json

import pytest
from pydantic import BaseModel

from app.llm.nebius import ModelOutputError, NebiusClient, extract_json


class Schema(BaseModel):
    a: int


def make_client(replies: list[str]) -> NebiusClient:
    client = NebiusClient.__new__(NebiusClient)
    from app.llm.nebius import UsageTracker

    client.usage = UsageTracker(model="test")
    client.model = "test"
    seq = iter(replies)
    client.complete = lambda **_: next(seq)  # type: ignore[method-assign]
    return client


def test_extract_json_handles_fences_and_prose() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"a": 2} hope that helps') == {"a": 2}


def test_extract_json_rejects_non_objects() -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json("[1, 2]")
    with pytest.raises(json.JSONDecodeError):
        extract_json("no json here")


def test_malformed_then_valid_retries_once() -> None:
    client = make_client(["not json", '{"a": 3}'])
    assert client.complete_model(system="s", user="u", schema=Schema).a == 3
    assert client.usage.retries_for_malformed_output == 1


def test_persistently_invalid_output_raises() -> None:
    client = make_client(['{"a": "x"}', '{"b": 1}'])
    with pytest.raises(ModelOutputError):
        client.complete_model(system="s", user="u", schema=Schema)


def test_missing_key_refuses_to_start(monkeypatch) -> None:
    from app.config import get_settings
    from app.llm.nebius import NebiusConfigurationError

    monkeypatch.setattr(get_settings(), "nebius_api_key", None)
    with pytest.raises(NebiusConfigurationError):
        NebiusClient()
