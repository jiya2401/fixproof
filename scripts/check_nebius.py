"""Verify the live Nebius Token Factory connection and model id. Needs NEBIUS_API_KEY.

    python scripts/check_nebius.py
Exits non-zero if the key is missing, the endpoint is unreachable, the configured model is
not in the account's model list, or a one-token completion fails.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.llm.nebius import NebiusClient, NebiusConfigurationError  # noqa: E402


def main() -> int:
    try:
        client = NebiusClient()
    except NebiusConfigurationError as exc:
        print(f"FAIL: {exc}")
        return 2
    models = client.list_models()
    nvidia = [m for m in models if "nemotron" in m.lower()]
    print(f"endpoint reachable; {len(models)} models; Nemotron models: {nvidia}")
    if client.model not in models:
        print(f"FAIL: configured NEBIUS_MODEL={client.model!r} is not in the model list")
        return 3
    reply = client.complete(system="Reply with the single word: ok", user="ping", temperature=0.0)
    print(f"OK: {client.model} replied {reply[:40]!r}; usage={client.usage.model_dump()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
