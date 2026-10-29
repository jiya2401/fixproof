"""Open a GitHub pull request for a verified FixProof patch.

Everything goes through the GitHub REST API (PyGithub): no clone and no credentials on disk.
The patch is applied with the pipeline's own strict `git apply` in a throwaway workspace that
holds only the files the diff touches, then committed with the Git Data API. A patch that no
longer applies to the target branch is reported as a conflict, never guessed at.
"""

import base64
import json
import re
import secrets
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from github import (
    Auth,
    BadCredentialsException,
    Github,
    GithubException,
    InputGitTreeElement,
    RateLimitExceededException,
)
from pydantic import BaseModel
from requests.exceptions import RequestException

from app.agents.models import AdversarialTest
from app.certificate import FixCertificate, IterationRecord
from app.repair.patching import apply_patch, patch_violations, touched_paths
from app.verification.results import CheckOutcome, VerificationVerdict

# Verdicts that mean "every mandatory check passed". Anything else must not become a PR.
ELIGIBLE_VERDICTS = frozenset(
    {VerificationVerdict.VERIFIED, VerificationVerdict.VERIFIED_WITH_CONDITIONS}
)
MAX_BRANCH_ATTEMPTS = 3
MERGEABLE_POLLS = 3  # GitHub computes mergeability asynchronously
MAX_TABLE_ROWS = 100  # keeps the body far below GitHub's 65,536 character limit
_SYMLINK_OR_SUBMODULE = {"120000", "160000"}

_REPO = re.compile(r"^(?:https://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,99}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_.\-]{10,255}$")

_sleep: Callable[[float], None] = time.sleep


class PullRequestError(Exception):
    """A problem the user can act on. `code` is stable and machine-readable."""

    def __init__(
        self, code: str, message: str, status_code: int = 400, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class ChangedFile(BaseModel):
    path: str
    change: str  # added | modified | deleted


class PullRequestResult(BaseModel):
    number: int
    url: str
    branch: str
    base: str
    patch_id: str
    commit_sha: str | None = None
    files_changed: list[ChangedFile] = []
    mergeable: bool | None = None  # None = GitHub is still computing it
    warning: str | None = None
    reused: bool = False  # an open PR for this certificate already existed


# ------------------------------------------------------------------ input handling


def parse_repository(text: str) -> tuple[str, str]:
    match = _REPO.match((text or "").strip())
    if not match:
        raise PullRequestError(
            "INVALID_REPOSITORY",
            'Repository must look like "owner/repo" or https://github.com/owner/repo.',
            422,
        )
    return match.group(1), match.group(2)


def repository_from_project(origin: str, origin_detail: str) -> tuple[str, str, str | None] | None:
    """(owner, repo, ref) when a project was cloned from github.com, else None."""
    if origin != "git" or not origin_detail.startswith("https://github.com/"):
        return None
    url, _, ref = origin_detail.partition("@")
    try:
        owner, name = parse_repository(url)
    except PullRequestError:
        return None
    return owner, name, ref or None


def validate_base_branch(branch: str | None) -> str | None:
    branch = (branch or "").strip()
    if not branch:
        return None
    if not _BRANCH.match(branch) or ".." in branch or branch.endswith(("/", ".lock")):
        raise PullRequestError("INVALID_BRANCH", "That is not a valid branch name.", 422)
    return branch


def validate_token(token: str | None) -> str:
    token = (token or "").strip()
    if not token:
        raise PullRequestError(
            "TOKEN_MISSING",
            "No GitHub token. Set FIXPROOF_GITHUB_TOKEN on the server or paste a token here.",
            401,
        )
    if not _TOKEN.match(token):
        raise PullRequestError("TOKEN_INVALID", "That does not look like a GitHub token.", 401)
    return token


def ensure_eligible(cert: FixCertificate) -> str:
    """Only a verified patch may be published. Returns the diff."""
    if cert.verdict not in ELIGIBLE_VERDICTS:
        raise PullRequestError(
            "NOT_VERIFIED",
            f"Only a verified patch can become a pull request (verdict: {cert.verdict.value}).",
            409,
        )
    diff = cert.final_patch or ""
    if not diff.strip():
        raise PullRequestError("NO_PATCH", "This certificate has no patch to publish.", 409)
    problems = patch_violations(diff)
    if problems:
        raise PullRequestError(
            "INVALID_PATCH", "The patch is not safe to publish.", 422, {"problems": problems}
        )
    return diff


# ------------------------------------------------------------------ error mapping


def _iso(epoch: str | None) -> str | None:
    try:
        return datetime.fromtimestamp(int(epoch or ""), UTC).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def map_github_error(exc: GithubException, action: str) -> PullRequestError:
    data = exc.data if isinstance(exc.data, dict) else {}
    message = str(data.get("message") or "")
    lowered = (message + " " + json.dumps(data.get("errors", ""), default=str)).lower()
    headers = {str(k).lower(): v for k, v in (exc.headers or {}).items()}
    status = exc.status

    if isinstance(exc, BadCredentialsException) or status == 401:
        return PullRequestError(
            "TOKEN_EXPIRED",
            "The GitHub token is expired, revoked or invalid. Create a new token and try again.",
            401,
        )
    if status in (403, 429):
        if (
            isinstance(exc, RateLimitExceededException)
            or status == 429
            or headers.get("x-ratelimit-remaining") == "0"
            or "rate limit" in lowered
        ):
            return PullRequestError(
                "RATE_LIMITED",
                "GitHub's API rate limit was reached. Wait a little and try again.",
                429,
                {"reset_at": _iso(headers.get("x-ratelimit-reset")),
                 "retry_after": headers.get("retry-after")},
            )  # fmt: skip
        if "x-github-sso" in headers or "saml" in lowered:
            return PullRequestError(
                "SSO_REQUIRED",
                "This organization enforces SAML SSO. Authorize the token for it on GitHub first.",
                403,
            )
        return PullRequestError(
            "INSUFFICIENT_PERMISSIONS",
            "The token cannot write to this repository. It needs repository 'Contents' and "
            "'Pull requests' write access (classic tokens: the `repo` scope).",
            403,
        )
    if status == 404:
        return PullRequestError(
            "NOT_FOUND",
            f"Not found while {action}. Check the repository and branch names; private "
            "repositories also need a token that can see them.",
            404,
        )
    if status == 409 and "empty" in lowered:
        return PullRequestError("EMPTY_REPOSITORY", "The repository has no commits yet.", 409)
    if status == 422 and "no commits between" in lowered:
        return PullRequestError(
            "NO_CHANGES", "The patch results in no change compared with the base branch.", 409
        )
    if status == 422 and "pull request already exists" in lowered:
        return PullRequestError(
            "PR_ALREADY_EXISTS", "A pull request for this branch already exists.", 409
        )
    if status == 422:
        return PullRequestError(
            "GITHUB_REJECTED", f"GitHub rejected the request while {action}: {message}", 422
        )
    return PullRequestError(
        "GITHUB_API_ERROR", f"GitHub returned an error while {action}: {message or status}", 502
    )


@contextmanager
def _github_errors(action: str) -> Iterator[None]:
    try:
        yield
    except PullRequestError:
        raise
    except GithubException as exc:
        raise map_github_error(exc, action) from exc
    except RequestException as exc:
        raise PullRequestError(
            "GITHUB_UNREACHABLE", f"Could not reach GitHub while {action}.", 502
        ) from exc


# ------------------------------------------------------------------ PR text

_CHECK_LABELS = {
    "reproduction_red": "Bug reproduced before the patch",
    "patch_applies_in_scope": "Patch applies, touches no tests",
    "reproduction_green": "Original failing test now passes",
    "regression": "Full existing test suite",
    "adversarial": "Spec-quoted attack tests",
    "adversarial_ungrounded": "Unvalidated attack tests (review only)",
}
_OUTCOME_ICON = {
    CheckOutcome.PASSED: "✅ passed",
    CheckOutcome.FAILED: "❌ failed",
    CheckOutcome.ERROR: "⚠️ error",
    CheckOutcome.SKIPPED: "⏭️ skipped",
    CheckOutcome.NOT_RUN: "⏭️ not run",
}
_VERDICT_LINE = {
    VerificationVerdict.VERIFIED: "✅ **Verified** — every mandatory check ran and none found "
    "a counterexample.",
    VerificationVerdict.VERIFIED_WITH_CONDITIONS: "⚠️ **Verified with conditions** — all "
    "mandatory checks passed, but the conditions below limit how far this can be trusted.",
}


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _defang(text: str) -> str:
    """Model-written text must not ping GitHub users."""
    return re.sub(r"(?<![\w`@])@(?=[A-Za-z0-9])", "@\u200b", text)


def _cell(text: str, limit: int = 240) -> str:
    return _defang(_clip(" ".join((text or "").split()), limit)).replace("|", "\\|") or "—"


def _code(text: str) -> str:
    return re.sub(r"[`|\r\n]", "", text or "").strip() or "unnamed"


def selected_attempt(cert: FixCertificate) -> IterationRecord | None:
    return next((it for it in cert.iterations if it.index == cert.selected_attempt), None)


def passed_attack_tests(cert: FixCertificate) -> list[AdversarialTest]:
    """Attack tests that passed against the reported patch (never reviewer-excluded ones)."""
    live = [t for t in cert.adversarial_tests if t.key and not t.disputed]
    attempt = selected_attempt(cert)
    if attempt and attempt.test_results:
        return [t for t in live if attempt.test_results.get(t.key) == "passed"]
    check = next((c for c in cert.checks if c.name == "adversarial"), None)
    if check and check.outcome == CheckOutcome.PASSED:  # no per-test record: only the grounded set
        return [t for t in live if t.grounded]
    return []


def build_pull_request_title(cert: FixCertificate) -> str:
    lines = (cert.patch_summary or "").strip().splitlines()
    summary = " ".join(lines[0].split()).rstrip(".") if lines else ""
    return f"fix: {_clip(summary or 'AI-verified patch', 80)}"


def build_pull_request_body(
    cert: FixCertificate, *, files: list[ChangedFile], patch_id: str, base: str
) -> str:
    attempt = selected_attempt(cert)
    tests = passed_attack_tests(cert)

    fix = _defang(_clip(cert.patch_summary or "", 600)) or "_No summary was recorded._"
    rationale = _defang(_clip(attempt.rationale if attempt else "", 800))
    root = _defang(_clip(cert.selected_root_cause or "", 1500)) or "_No root cause was recorded._"

    if tests:
        rows = [
            "| # | Test | Intent | Status |",
            "|:-:|------|--------|:------:|",
        ]
        for i, t in enumerate(tests[:MAX_TABLE_ROWS], 1):
            status = "✅ Passed" if t.grounded else "✅ Passed · unvalidated"
            rows.append(f"| {i} | `{_code(t.name)}` | {_cell(t.rationale)} | {status} |")
        if len(tests) > MAX_TABLE_ROWS:
            rows.append(f"\n_…and {len(tests) - MAX_TABLE_ROWS} more._")
        table = "\n".join(rows)
    else:
        table = "_No adversarial test results were recorded for this patch._"

    evidence = [
        "| Check | Result | Tests run |",
        "|-------|--------|:---------:|",
        *(
            f"| {_CHECK_LABELS.get(c.name, _code(c.name))} | {_OUTCOME_ICON[c.outcome]} "
            f"| {c.tests_executed} |"
            for c in cert.checks
        ),
    ]
    changed = "\n".join(f"- `{_code(f.path)}` ({f.change})" for f in files) or "_n/a_"

    sections = [
        "## 🛡️ FixProof automated patch",
        f"> {_VERDICT_LINE[cert.verdict]}",
        f"### 🔍 Root cause\n{root}",
        f"### 🔧 The fix\n{fix}" + (f"\n\n{rationale}" if rationale else ""),
        f"### ⚔️ Adversarial attack tests passed ({len(tests)})\n{table}",
        "### 🧪 Verification evidence\n" + "\n".join(evidence),
        f"### 📁 Files changed\n{changed}",
    ]
    if cert.limitations:
        shown = "\n".join(f"- {_defang(_clip(item, 300))}" for item in cert.limitations[:8])
        sections.append(f"### ⚠️ Conditions\n{shown}")
    disclaimer = cert.disclaimers[0] if cert.disclaimers else ""
    sections += [
        "---",
        f"<sub>{_defang(disclaimer)} Patch `{patch_id}` · base `{base}` · policy "
        f"v{cert.policy_version} · certificate `{cert.certificate_sha256[:16]}` · "
        "opened by FixProof</sub>",
    ]
    return "\n\n".join(sections) + "\n"


# ------------------------------------------------------------------ GitHub flow


def _make_github(token: str) -> Github:
    # retry=None: surface rate limits at once instead of sleeping inside a web request.
    return Github(
        auth=Auth.Token(token),
        timeout=20,
        retry=None,
        seconds_between_requests=None,
        seconds_between_writes=None,
        user_agent="fixproof-pull-request",
    )


def _patch_id(cert: FixCertificate) -> str:
    return re.sub(r"[^a-z0-9]", "", (cert.certificate_id or "").split("-")[0].lower()) or (
        secrets.token_hex(4)
    )


def _apply_in_workspace(
    repo: Any, tree: Any, base_sha: str, diff: str
) -> list[tuple[str, str, bool, bytes | None]]:
    """Apply `diff` strictly to the base branch's files.

    Returns [(path, mode, existed_before, new_bytes_or_None_if_deleted)] for files that changed.
    """
    entries = {t.path: t for t in tree.tree if t.type in ("blob", "commit")}

    def lookup(path: str) -> Any:
        entry = entries.get(path)
        if entry is not None or not getattr(tree, "truncated", False):
            return entry
        with _github_errors(f"reading {path}"):  # huge repo: the recursive tree was cut off
            try:
                content = repo.get_contents(path, ref=base_sha)
            except GithubException as exc:
                if exc.status == 404:
                    return None
                raise
        if isinstance(content, list):
            return None
        return SimpleNamespace(sha=content.sha, mode="100644", type="blob")

    paths = touched_paths(diff)
    with tempfile.TemporaryDirectory(prefix="fixproof-pr-") as tmp:
        workspace = Path(tmp).resolve()
        before: dict[str, bytes] = {}
        modes: dict[str, str] = {}
        for path in paths:
            entry = lookup(path)
            if entry is None:
                continue  # a file the patch creates
            if entry.mode in _SYMLINK_OR_SUBMODULE:
                raise PullRequestError(
                    "UNSUPPORTED_FILE", f"{path} is a symlink or submodule; refusing to patch.", 422
                )
            with _github_errors(f"reading {path}"):
                blob = repo.get_git_blob(entry.sha)
            data = (
                base64.b64decode(blob.content)
                if blob.encoding == "base64"
                else blob.content.encode()
            )
            target = (workspace / path).resolve()
            if workspace not in target.parents:
                raise PullRequestError("INVALID_PATCH", f"Unsafe path in patch: {path}", 422)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            before[path], modes[path] = data, entry.mode

        applied, message = apply_patch(workspace, diff)
        if not applied:
            raise PullRequestError(
                "PATCH_CONFLICT",
                "The patch no longer applies to the target branch (it has changed since this "
                "project was loaded). Re-run FixProof against the latest code.",
                409,
                {"git": message[:1500]},
            )

        changes: list[tuple[str, str, bool, bytes | None]] = []
        for path in paths:
            target = workspace / path
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise PullRequestError("INVALID_PATCH", f"{path}: links are not allowed.", 422)
            after = target.read_bytes() if target.exists() else None
            if after == before.get(path):
                continue  # untouched (e.g. a mode-only change)
            changes.append((path, modes.get(path, "100644"), path in before, after))
        return changes


def _change_kind(existed: bool, after: bytes | None) -> str:
    if after is None:
        return "deleted"
    return "modified" if existed else "added"


def publish_pull_request(
    cert: FixCertificate,
    *,
    token: str,
    owner: str,
    name: str,
    base_branch: str | None = None,
    github_factory: Callable[[str], Any] = _make_github,
) -> PullRequestResult:
    """Branch -> apply diff -> commit -> push -> open PR. Raises PullRequestError."""
    diff = ensure_eligible(cert)
    gh = github_factory(token)

    with _github_errors("reading the repository"):
        repo = gh.get_repo(f"{owner}/{name}")
        archived = bool(repo.archived)
        can_push = bool(getattr(repo.permissions, "push", True))
        default_branch = repo.default_branch
        owner_login = repo.owner.login
    if archived:
        raise PullRequestError("REPO_ARCHIVED", "This repository is archived (read-only).", 409)
    if not can_push:
        raise PullRequestError(
            "INSUFFICIENT_PERMISSIONS", "The token has no push access to this repository.", 403
        )

    base = base_branch or default_branch
    with _github_errors(f'reading branch "{base}"'):
        base_sha = repo.get_branch(base).commit.sha
        base_commit = repo.get_git_commit(base_sha)
        tree = repo.get_git_tree(base_commit.tree.sha, recursive=True)

    changes = _apply_in_workspace(repo, tree, base_sha, diff)
    if not changes:
        raise PullRequestError(
            "NO_CHANGES", "The patch results in no change compared with the base branch.", 409
        )
    files = [
        ChangedFile(path=path, change=_change_kind(existed, after))
        for path, _mode, existed, after in changes
    ]

    patch_id = _patch_id(cert)
    with _github_errors("creating the commit"):
        elements = []
        for path, mode, _existed, after in changes:
            if after is None:
                elements.append(InputGitTreeElement(path, mode, "blob", sha=None))
            else:
                blob = repo.create_git_blob(base64.b64encode(after).decode("ascii"), "base64")
                elements.append(InputGitTreeElement(path, mode, "blob", sha=blob.sha))
        new_tree = repo.create_git_tree(elements, base_commit.tree)
        commit = repo.create_git_commit(
            f"{build_pull_request_title(cert)}\n\nVerified by FixProof (certificate "
            f"{cert.certificate_sha256[:12]}, patch {patch_id}).",
            new_tree,
            [base_commit],
        )

    branch = ""
    for attempt in range(MAX_BRANCH_ATTEMPTS):
        candidate = f"fixproof/patch-{patch_id}" + (f"-{secrets.token_hex(2)}" if attempt else "")
        try:
            repo.create_git_ref(ref=f"refs/heads/{candidate}", sha=commit.sha)
        except GithubException as exc:
            if not (exc.status == 422 and "already exists" in str(exc.data).lower()):
                raise map_github_error(exc, "creating the branch") from exc
            with _github_errors("checking existing pull requests"):
                existing = list(repo.get_pulls(state="open", head=f"{owner_login}:{candidate}"))
            if existing:  # the same certificate was published before: hand back that PR
                return PullRequestResult(
                    number=existing[0].number, url=existing[0].html_url, branch=candidate,
                    base=base, patch_id=patch_id, files_changed=files, reused=True,
                )  # fmt: skip
            continue  # the name is taken by something else: retry with a random suffix
        except RequestException as exc:
            raise PullRequestError(
                "GITHUB_UNREACHABLE", "Could not reach GitHub while creating the branch.", 502
            ) from exc
        branch = candidate
        break
    if not branch:
        raise PullRequestError(
            "BRANCH_CONFLICT", "Could not find a free branch name after several attempts.", 409
        )

    try:
        with _github_errors("creating the pull request"):
            pr = repo.create_pull(
                base=base,
                head=branch,
                title=build_pull_request_title(cert),
                body=build_pull_request_body(cert, files=files, patch_id=patch_id, base=base),
                maintainer_can_modify=True,
            )
    except PullRequestError:
        try:  # never leave an orphan branch behind
            repo.get_git_ref(f"heads/{branch}").delete()
        except (GithubException, RequestException):
            pass
        raise

    mergeable: bool | None = None
    for _ in range(MERGEABLE_POLLS):
        _sleep(1)
        try:
            mergeable = repo.get_pull(pr.number).mergeable
        except (GithubException, RequestException):
            break
        if mergeable is not None:
            break

    return PullRequestResult(
        number=pr.number, url=pr.html_url, branch=branch, base=base, patch_id=patch_id,
        commit_sha=commit.sha, files_changed=files, mergeable=mergeable,
        warning=(
            f"GitHub reports merge conflicts with `{base}`. Resolve them on the pull request."
            if mergeable is False else None
        ),
    )  # fmt: skip
