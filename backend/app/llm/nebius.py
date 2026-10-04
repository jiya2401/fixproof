import json
from typing import Any

from openai import OpenAI

from app.config import get_settings


class NebiusConfigurationError(RuntimeError):
    pass


class NebiusClient:
    """Thin Token Factory wrapper.

    Keeping this layer small makes it obvious which behavior comes from Nemotron and
    which behavior comes from deterministic FixProof tooling.
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
        )

    def complete(self, *, system: str, user: str, temperature: float = 0.1) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("Nemotron returned an empty response")
        return content

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """Parse a JSON response for early milestones.

        Later milestones should move to provider-supported structured outputs/tool calls
        where appropriate. This parser exists so the starter remains provider-light.
        """
        raw = self.complete(
            system=system + "\nReturn only valid JSON. Do not wrap it in markdown fences.",
            user=user,
            temperature=0.0,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Nemotron response was not valid JSON") from exc
