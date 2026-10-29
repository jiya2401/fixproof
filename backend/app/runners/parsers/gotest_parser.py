"""Go test JSON (NDJSON) output parser for FixProof.

``go test -json`` emits one JSON object per line (newline-delimited JSON /
NDJSON).  Each event has an ``Action`` field:

* ``"run"``     — a test has been scheduled to run
* ``"pass"``    — a test/package passed
* ``"fail"``    — a test/package failed
* ``"output"``  — a line of text output from the test binary
* ``"skip"``    — a test was skipped
* ``"start"``   — a package started (no ``Test`` key)
* ``"pause"``   — a test was paused (parallel tests)
* ``"cont"``    — a test was resumed

The parser accumulates failure details by matching ``"output"`` events to
the ``"fail"`` events of the same test.

Example NDJSON::

    {"Action":"run","Package":"example.com/pkg","Test":"TestAdd"}
    {"Action":"output","Package":"example.com/pkg","Test":"TestAdd",
     "Output":"    math_test.go:12: expected 1 got 0\\n"}
    {"Action":"fail","Package":"example.com/pkg","Test":"TestAdd","Elapsed":0.001}
    {"Action":"pass","Package":"example.com/pkg","Test":"TestMul","Elapsed":0.000}
    {"Action":"fail","Package":"example.com/pkg","Elapsed":0.005}
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

from app.runners.schema import FailureDetail, TestRunResult

# Matches the location prefix that go test puts in output lines:
#     "    math_test.go:42: error message"
_LOCATION_RE = re.compile(r"^\s+([\w./\\-]+\.go):(\d+):\s*(.*)")


def parse_gotest_json(stdout: str, *, raw_output: str = "") -> TestRunResult:
    """Parse ``go test -json`` NDJSON output into a ``TestRunResult``.

    Parameters
    ----------
    stdout:
        Raw standard output from the ``go test -json`` process.
    raw_output:
        Combined stdout + stderr, stored verbatim in the result.

    Returns
    -------
    TestRunResult
        Normalised result.  Falls back gracefully on malformed lines.
    """
    # ------------------------------------------------------------------ accumulators
    # test-level tracking
    ran: set[str] = set()          # all test keys that were "run"
    passed: set[str] = set()       # tests that "pass"ed
    failed: set[str] = set()       # tests that "fail"ed
    skipped: set[str] = set()      # tests that were "skip"ped

    # output lines per test (for failure message extraction)
    output_lines: dict[str, list[str]] = defaultdict(list)

    # package elapsed times
    total_elapsed = 0.0

    # ------------------------------------------------------------------ parse
    for raw_line in stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue  # non-JSON progress/build output — skip silently

        action: str = event.get("Action", "")
        pkg: str = event.get("Package", "")
        test: str = event.get("Test", "")  # empty for package-level events
        key = f"{pkg}/{test}" if test else ""

        if action == "run" and test:
            ran.add(key)

        elif action == "output" and test:
            line: str = event.get("Output", "")
            output_lines[key].append(line)

        elif action == "pass":
            if test:
                passed.add(key)
            else:
                # Package-level pass — accumulate elapsed
                elapsed = event.get("Elapsed", 0)
                if isinstance(elapsed, (int, float)):
                    total_elapsed += float(elapsed)

        elif action == "fail":
            if test:
                failed.add(key)
            else:
                elapsed = event.get("Elapsed", 0)
                if isinstance(elapsed, (int, float)):
                    total_elapsed += float(elapsed)

        elif action == "skip" and test:
            skipped.add(key)

    # ------------------------------------------------------------------ counts
    total = len(ran)
    # a test that passes after failing is unusual but handle it
    passed_count = len(passed - failed)
    failed_count = len(failed)
    # skipped tests are not counted in total by Go's convention
    # (go test reports them separately; they inflate 'ran' so we subtract)
    total_effective = max(total - len(skipped), 0)

    # ------------------------------------------------------------------ failure details
    failure_details: list[FailureDetail] = []
    for key in sorted(failed):
        lines = output_lines.get(key, [])
        # Extract file/line from the first location-annotated output line
        file_hint: str | None = None
        line_hint: int | None = None
        msg_parts: list[str] = []
        for ln in lines:
            m = _LOCATION_RE.match(ln)
            if m:
                if file_hint is None:
                    file_hint = m.group(1)
                    line_hint = int(m.group(2))
                msg_parts.append(m.group(3).strip())
            else:
                stripped = ln.strip()
                if stripped:
                    msg_parts.append(stripped)

        message = "\n".join(msg_parts)[:1000]  # cap at 1 kB
        # test key is "pkg/TestName" — extract just the test name part
        test_name = key.rsplit("/", 1)[-1] if "/" in key else key

        failure_details.append(
            FailureDetail(
                test_name=test_name,
                message=message,
                file=file_hint,
                line=line_hint,
            )
        )

    return TestRunResult(
        total_tests=total_effective,
        passed=passed_count,
        failed=failed_count,
        errors=0,
        duration_seconds=round(total_elapsed, 3),
        failures=failure_details,
        raw_output=raw_output or stdout,
    )

