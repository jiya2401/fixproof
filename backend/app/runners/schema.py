"""Unified test-run result schema consumed by the FixProof frontend.

All language runners normalise their raw tool output into a ``TestRunResult``
so the dashboard never has to know which toolchain was used.

Frontend contract (JSON representation)::

    {
        "total_tests": 12,
        "passed":      10,
        "failed":       2,
        "errors":       0,
        "duration_seconds": 1.23,
        "timed_out": false,
        "failures": [
            {
                "test_name": "TestFoo/subcase",
                "message":   "expected 1 got 0",
                "file":      "pkg/math_test.go",
                "line":      42
            }
        ]
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FailureDetail:
    """A single failing test case extracted from raw runner output."""

    test_name: str
    message: str
    file: str | None = None
    line: int | None = None

    def to_dict(self) -> dict:
        return {
            "test_name": self.test_name,
            "message": self.message,
            "file": self.file,
            "line": self.line,
        }


@dataclass
class TestRunResult:
    __test__: bool = False
    """Normalised summary of a test suite execution.

    Attributes
    ----------
    total_tests:
        Total number of test cases that were collected and attempted.
    passed:
        Number of test cases that passed.
    failed:
        Number of test cases that failed with an assertion error.
    errors:
        Number of test cases that failed with an infrastructure error
        (collection failure, panic, import error, etc.).
    duration_seconds:
        Wall-clock seconds spent running the suite.
    failures:
        Structured details for each failing test case.
    raw_output:
        The original stdout/stderr combined, preserved for diagnostics.
    timed_out:
        True when the runner was killed because it exceeded its timeout.
    """

    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    failures: list[FailureDetail] = field(default_factory=list)
    raw_output: str = ""
    timed_out: bool = False

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def ok(self) -> bool:
        """True when the suite completed with no failures and no errors."""
        return not self.timed_out and self.failed == 0 and self.errors == 0

    def to_dict(self) -> dict:
        """Serialise to the canonical frontend JSON schema."""
        return {
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "duration_seconds": round(self.duration_seconds, 3),
            "timed_out": self.timed_out,
            "failures": [f.to_dict() for f in self.failures],
        }

    @classmethod
    def timed_out_result(cls, raw_output: str = "") -> TestRunResult:
        """Convenience constructor for a timeout outcome."""
        return cls(timed_out=True, raw_output=raw_output)

    @classmethod
    def error_result(cls, message: str, raw_output: str = "") -> TestRunResult:
        """Convenience constructor for an infrastructure error outcome."""
        return cls(errors=1, raw_output=raw_output, failures=[FailureDetail("(setup)", message)])

