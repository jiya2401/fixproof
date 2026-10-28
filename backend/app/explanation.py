"""Feature 3: Visual Explanations & "Why I Fixed It" engine.

Generates a structured, punchy JSON explanation of the root cause and fix
immediately after the patch execution loop completes, before the certificate
is sealed. The output is designed for collapsible dashboard components in the UI.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# Module-level import so tests can patch app.explanation.NebiusClient
try:
    from app.llm.nebius import NebiusClient as _NebiusClient
    NebiusClient = _NebiusClient
except Exception:  # noqa: BLE001 — no key configured yet in test environments
    NebiusClient = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

EXPLANATION_FALLBACK: dict[str, Any] = {
    "root_cause": "Analysis unavailable. The explanation service could not process this fix.",
    "the_fix": "See the patch diff for details of what was changed.",
    "technical_keywords": ["patch", "bug-fix"],
}


class FixExplanation(BaseModel):
    """Structured explanation of a bug fix, surfaced on the dashboard."""

    root_cause: str = Field(
        description="A 1-2 sentence summary of the fundamental root cause of the bug.",
    )
    the_fix: str = Field(
        description="A 1-2 sentence description of how the patch resolves the root cause.",
    )
    technical_keywords: list[str] = Field(
        description="A list of 2-4 concise architectural or domain terms that characterise the fix.",
    )

    @field_validator("technical_keywords")
    @classmethod
    def clamp_keywords(cls, v: list[str]) -> list[str]:
        """Silently clamp the keyword list to 2-4 items to honour the UI contract."""
        # Ensure we have at least 2 items, then cap at 4
        padded = (v + ["bug-fix", "patch"])[:max(2, len(v))]
        return padded[:4]


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a concise technical writer embedded in an automated bug-fix pipeline.
Your only job is to explain, to a software engineer, WHY a bug occurred and HOW
the generated patch fixes it.

OUTPUT RULES — read these carefully and follow them exactly:
1. Return a single, raw JSON object. No markdown. No ```json fences. No prose before or after.
2. The object must contain EXACTLY these three keys:
   - "root_cause"          : string — max 2 sentences; the fundamental technical cause.
   - "the_fix"             : string — max 2 sentences; what the patch changed and why it resolves the root cause.
   - "technical_keywords"  : array of 2-4 short strings; precise architectural or domain terms
                             (e.g. "off-by-one error", "SQL injection", "race condition", "integer overflow").
3. Do NOT include extra keys, nesting, or explanatory text.
4. Be precise. Avoid filler words like "simply" or "just".
5. If information is genuinely absent, write "Insufficient context." for that field.\
"""

_USER_TEMPLATE = """\
## ORIGINAL BUGGY CODE
```
{buggy_code}
```

## FAILING TEST TRACEBACK
```
{traceback}
```

## UNIFIED PATCH DIFF (the accepted fix)
```diff
{patch_diff}
```

Analyse the above and return the JSON explanation object.\
"""


def build_explanation_prompt(
    buggy_code: str,
    traceback: str,
    patch_diff: str,
    *,
    max_code_chars: int = 3_000,
    max_tb_chars: int = 2_000,
    max_diff_chars: int = 3_000,
) -> tuple[str, str]:
    """Return ``(system, user)`` prompt strings, each hard-capped to avoid token bloat.

    The caps keep the explanation call cheap: it is a fast, summarisation-only
    call and does not need the full context that the repair loop sees.
    """
    system = _SYSTEM_PROMPT
    user = _USER_TEMPLATE.format(
        buggy_code=buggy_code[:max_code_chars],
        traceback=traceback[:max_tb_chars],
        patch_diff=patch_diff[:max_diff_chars],
    )
    return system, user


# ---------------------------------------------------------------------------
# LLM call + parsing
# ---------------------------------------------------------------------------

def _parse_explanation(raw: str) -> FixExplanation:
    """Parse the LLM's raw string into a validated ``FixExplanation``.

    Tolerates markdown fences and surrounding prose by attempting two
    extraction strategies before raising.

    Raises:
        ValueError: if the string cannot be parsed into a valid FixExplanation.
    """
    import re

    text = raw.strip()

    # Strategy 1: strip a ```json … ``` fence if the model ignored our instructions
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    # Strategy 2: JSON decode
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            data = json.loads(text[start : end + 1])
        else:
            raise ValueError(f"No JSON object found in LLM output: {raw[:200]!r}")

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object, got {type(data).__name__}")

    return FixExplanation.model_validate(data)


def generate_explanation(
    buggy_code: str,
    traceback: str,
    patch_diff: str,
    *,
    llm_client: Any | None = None,
) -> FixExplanation:
    """Generate a structured explanation for a completed fix.

    Parameters
    ----------
    buggy_code:
        The source code as it was *before* the patch.
    traceback:
        The failing-test traceback / pytest output that proved the bug.
    patch_diff:
        The unified diff of the accepted patch.
    llm_client:
        An optional pre-built ``NebiusClient`` instance.  When ``None`` a
        fresh client is created.  Inject a mock in tests.

    Returns
    -------
    FixExplanation
        Always returns a valid ``FixExplanation``.  On any error (network
        timeout, malformed JSON, validation failure) a safe fallback is
        returned so the certificate can still be sealed.
    """
    if not patch_diff or not patch_diff.strip():
        logger.debug("explanation: no patch diff available, returning fallback")
        return FixExplanation(**EXPLANATION_FALLBACK)

    system, user = build_explanation_prompt(buggy_code, traceback, patch_diff)

    try:
        if llm_client is None:
            if NebiusClient is None:  # type: ignore[truthy-function]
                raise RuntimeError("NebiusClient is not available")
            llm_client = NebiusClient()

        raw = llm_client.complete(system=system, user=user, temperature=0.0)
        explanation = _parse_explanation(raw)
        logger.info(
            "explanation: generated successfully (%d chars raw)", len(raw)
        )
        return explanation

    except Exception as exc:  # noqa: BLE001  — never let this kill the pipeline
        logger.warning(
            "explanation: failed (%s: %s), using fallback",
            type(exc).__name__,
            str(exc)[:200],
        )
        return FixExplanation(**EXPLANATION_FALLBACK)
