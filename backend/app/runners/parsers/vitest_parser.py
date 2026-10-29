"""Vitest JSON output parser for FixProof.

Vitest's ``--reporter=json`` emits a **single JSON object** to stdout once
the suite completes.  This parser converts that blob into a ``TestRunResult``.

Vitest JSON shape (abridged)::

    {
      "numPassedTests": 10,
      "numFailedTests": 2,
      "numPendingTests": 0,
      "numTotalTests": 12,
      "startTime": 1700000000000,
      "success": false,
      "testResults": [
        {
          "testFilePath": "/workspace/src/math.test.ts",
          "status": "failed",
          "assertionResults": [
            {
              "fullName": "Math > add > should return 3",
              "status": "failed",
              "failureMessages": ["expected 2 to equal 3"],
              "duration": 5,
              "location": {"line": 12, "column": 0}
            }
          ]
        }
      ]
    }

If the JSON cannot be parsed (e.g. Vitest itself failed to start), the function
falls back to a best-effort regex scan of the raw output.
"""

from __future__ import annotations

import json
import re

from app.runners.schema import FailureDetail, TestRunResult

# Matches lines like:  ✓ 10 | ✗ 2 | ↓ 0
_SUMMARY_RE = re.compile(r"(\d+)\s+passed.*?(\d+)\s+failed", re.IGNORECASE)


def parse_vitest_json(stdout: str, *, raw_output: str = "") -> TestRunResult:
    """Parse Vitest ``--reporter=json`` stdout into a ``TestRunResult``.

    Parameters
    ----------
    stdout:
        Raw standard output from the Vitest process.
    raw_output:
        Combined stdout + stderr, stored verbatim in the result for
        diagnostics.

    Returns
    -------
    TestRunResult
        Normalised result.  Falls back to ``TestRunResult.error_result`` when
        the JSON cannot be decoded.
    """
    # ------------------------------------------------------------------ JSON parse
    blob: dict | None = _extract_json(stdout)
    if blob is None:
        return _fallback(stdout, raw_output)

    try:
        total: int = int(blob.get("numTotalTests", 0))
        passed: int = int(blob.get("numPassedTests", 0))
        failed: int = int(blob.get("numFailedTests", 0))
        # Vitest doesn't distinguish "errors" from "failures" — map pending to errors
        pending: int = int(blob.get("numPendingTests", 0))

        # Compute duration from startTime (ms epoch) — not always present
        duration = _extract_duration(blob)

        failures = _extract_failures(blob)

        return TestRunResult(
            total_tests=total,
            passed=passed,
            failed=failed,
            errors=pending,          # pending/skipped surfaced as errors for consistency
            duration_seconds=duration,
            failures=failures,
            raw_output=raw_output or stdout,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return TestRunResult.error_result(
            f"vitest parser: unexpected JSON structure: {exc}",
            raw_output=raw_output or stdout,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_json(stdout: str) -> dict | None:
    """Find and parse the first JSON object in *stdout*."""
    # Vitest may print non-JSON progress lines before the blob; find the
    # first '{' that opens the top-level object.
    start = stdout.find("{")
    if start == -1:
        return None
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError:
        pass
    # Try line-by-line (some Vitest configurations wrap output)
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def _extract_duration(blob: dict) -> float:
    """Extract test duration in seconds from the Vitest JSON blob."""
    # Vitest records startTime (ms); total duration is across all testResults
    total_ms = 0.0
    for file_result in blob.get("testResults", []):
        for assertion in file_result.get("assertionResults", []):
            dur = assertion.get("duration")
            if isinstance(dur, (int, float)):
                total_ms += float(dur)
    return round(total_ms / 1000.0, 3)


def _extract_failures(blob: dict) -> list[FailureDetail]:
    """Walk assertionResults and collect all failed test cases."""
    details: list[FailureDetail] = []
    for file_result in blob.get("testResults", []):
        file_path: str = file_result.get("testFilePath", "")
        for assertion in file_result.get("assertionResults", []):
            if assertion.get("status") != "failed":
                continue
            name: str = assertion.get("fullName") or assertion.get("title", "unknown")
            messages: list[str] = assertion.get("failureMessages") or []
            message = "\n".join(messages)[:1000]  # cap at 1 kB per test
            loc = assertion.get("location") or {}
            line = loc.get("line")
            details.append(
                FailureDetail(
                    test_name=name,
                    message=message,
                    file=file_path or None,
                    line=int(line) if line is not None else None,
                )
            )
    return details


def _fallback(stdout: str, raw_output: str) -> TestRunResult:
    """Best-effort regex parse when JSON decoding fails."""
    m = _SUMMARY_RE.search(stdout)
    if m:
        passed = int(m.group(1))
        failed = int(m.group(2))
        return TestRunResult(
            total_tests=passed + failed,
            passed=passed,
            failed=failed,
            raw_output=raw_output or stdout,
        )
    return TestRunResult.error_result(
        "vitest parser: could not decode JSON or find summary line",
        raw_output=raw_output or stdout,
    )

