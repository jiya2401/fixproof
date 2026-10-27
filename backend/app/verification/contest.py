"""Detect attack tests that cannot all be satisfied by the patches tried.

Every attack test is run against every attempt's patch. If attempt i passes some tests that
attempt j fails, while j passes other tests that i fails, the two groups conflict across the
attempts. At least one test in a conflict may be wrong (model-authored tests do contain mistakes),
so the certificate flags them for human review instead of silently trusting either side.
"""

from pydantic import BaseModel, Field


class Contest(BaseModel):
    first_attempt: int
    second_attempt: int
    only_first_satisfies: list[str] = Field(default_factory=list)
    only_second_satisfies: list[str] = Field(default_factory=list)

    @property
    def keys(self) -> set[str]:
        return set(self.only_first_satisfies) | set(self.only_second_satisfies)

    def describe(self) -> str:
        return (
            f"attempt {self.first_attempt} satisfies {', '.join(self.only_first_satisfies)} "
            f"but fails {', '.join(self.only_second_satisfies)}; attempt {self.second_attempt} "
            "does the opposite. These tests cannot all be satisfied by the patches tried, so "
            "at least one of them may be wrong."
        )


def find_contests(results: dict[int, dict[str, str]]) -> list[Contest]:
    """`results[attempt][test_key]` is 'passed' | 'failed' | 'error'."""
    contests: list[Contest] = []
    attempts = sorted(results)
    for pos, i in enumerate(attempts):
        for j in attempts[pos + 1 :]:
            shared = set(results[i]) & set(results[j])
            first_only = sorted(
                k for k in shared if results[i][k] == "passed" and results[j][k] == "failed"
            )
            second_only = sorted(
                k for k in shared if results[i][k] == "failed" and results[j][k] == "passed"
            )
            if first_only and second_only:
                contests.append(Contest(
                    first_attempt=i, second_attempt=j,
                    only_first_satisfies=first_only, only_second_satisfies=second_only,
                ))  # fmt: skip
    return contests
