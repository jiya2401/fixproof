import json
import re
import time
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)


class NebiusConfigurationError(RuntimeError):
    pass


class ModelOutputError(RuntimeError):
    """The model returned something that could not be parsed/validated after a retry."""


class UsageTracker(BaseModel):
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0
    model: str = ""
    retries_for_malformed_output: int = 0


def extract_json(raw: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating fences and surrounding prose."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise json.JSONDecodeError("expected a JSON object", text, 0)
    return value


class NebiusClient:
    """Thin NVIDIA Nemotron-via-Nebius Token Factory wrapper (OpenAI-compatible API).

    Everything that comes from the language model passes through here, so model usage is
    observable (`usage`) and the boundary between model output and deterministic tooling is
    explicit. There is no fallback or canned response: without a key it refuses to start.
    """

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.nebius_api_key:
            raise NebiusConfigurationError(
                "NEBIUS_API_KEY is not configured. Copy .env.example to .env and add a key."
            )
        self.model = settings.nebius_model
        self.client = OpenAI(
            api_key=settings.nebius_api_key,
            base_url=settings.nebius_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        self.usage = UsageTracker(model=self.model)

    def list_models(self) -> list[str]:
        return sorted(model.id for model in self.client.models.list().data)

    def complete(self, *, system: str, user: str, temperature: float = 0.1) -> str:
        started = time.monotonic()
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        self.usage.calls += 1
        self.usage.latency_seconds += time.monotonic() - started
        if response.usage:
            self.usage.prompt_tokens += response.usage.prompt_tokens or 0
            self.usage.completion_tokens += response.usage.completion_tokens or 0
        content = response.choices[0].message.content
        if not content:
            raise ModelOutputError("Nemotron returned an empty response")
        return content

    def complete_model(self, *, system: str, user: str, schema: type[T]) -> T:
        """Return a validated `schema` instance; one corrective retry on malformed output."""
        instruction = (
            system
            + "\nReturn only one valid JSON object, with no markdown fences and no commentary."
        )
        prompt = user
        last_error: Exception | None = None
        for _ in range(2):
            raw = self.complete(system=instruction, user=prompt, temperature=0.0)
            try:
                return schema.model_validate(extract_json(raw))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                self.usage.retries_for_malformed_output += 1
                prompt = (
                    f"{user}\n\nYour previous reply was rejected: {str(exc)[:500]}\n"
                    "Reply again with only the corrected JSON object."
                )
        raise ModelOutputError(f"Nemotron output failed validation: {last_error}")
