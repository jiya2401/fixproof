"""GitHub pull-request integration, tested against an in-memory stand-in for PyGithub."""

import base64
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from github import (
    BadCredentialsException,
    GithubException,
    InputGitTreeElement,
    RateLimitExceededException,
    UnknownObjectException,
)

from app import github_pr
from app.agents.models import AdversarialTest
from app.api import routes
from app.certificate import FixCertificate, IterationRecord
from app.config import get_settings
from app.main import app
from app.orchestrator.state import InvestigationStage, InvestigationState
from app.verification.results import CheckOutcome, CheckResult, VerificationVerdict
from tests.conftest import REPO_ROOT, fixture_text

client = TestClient(app)
ORIGINAL = (REPO_ROOT / "examples" / "buggy-python-app" / "auth.py").read_text(encoding="utf-8")
PATCH = fixture_text("auth_correct.diff")
TOKEN = "ghp_exampletoken1234567890"


def make_cert(verdict: VerificationVerdict = VerificationVerdict.VERIFIED) -> FixCertificate:
    tests = [
        AdversarialTest(
            name="refresh_token_accepted", rationale="Refresh tokens must validate | exactly",
            code="", key="refresh_token_accepted", grounded=True,
        ),
        AdversarialTest(
            name="access_token_rejected", rationale="Access tokens must be rejected",
            code="", key="access_token_rejected", grounded=False,
        ),
        AdversarialTest(
            name="flaky_attack", rationale="Fails on this patch", code="", key="flaky_attack",
            grounded=True,
        ),
        AdversarialTest(
            name="excluded_by_human", rationale="Disputed", code="", key="excluded_by_human",
            grounded=True, disputed=True,
        ),
    ]  # fmt: skip
    cert = FixCertificate(
        verdict=verdict,
        selected_root_cause="The check compares against 'access' so refresh tokens fail. @octocat",
        patch_summary="Accept refresh tokens in validate_refresh_token.",
        final_patch=PATCH,
        changed_files=["auth.py"],
        adversarial_tests=tests,
        selected_attempt=1,
        iterations=[
            IterationRecord(
                index=1,
                rationale="Invert the comparison.",
                test_results={
                    "refresh_token_accepted": "passed",
                    "access_token_rejected": "passed",
                    "flaky_attack": "failed",
                    "excluded_by_human": "passed",
                },
            )  # fmt: skip
        ],
        checks=[
            CheckResult(name="reproduction_green", outcome=CheckOutcome.PASSED, tests_executed=1),
            CheckResult(name="adversarial", outcome=CheckOutcome.PASSED, tests_executed=2),
        ],
        limitations=["Isolation is process-level only."],
    )
    return cert.seal()


class FakeRepo:
    def __init__(
        self, files: dict[str, bytes], *, branches=("main",), open_prs=(), create_pull_error=None
    ):
        self.files = files
        self.branches = set(branches)
        self.open_prs = list(open_prs)  # head names
        self.create_pull_error = create_pull_error
        self.archived = False
        self.permissions = SimpleNamespace(push=True)
        self.default_branch = "main"
        self.owner = SimpleNamespace(login="acme")
        self.blobs: dict[str, bytes] = {}
        self.tree_elements: list[dict] = []
        self.commit_message = ""
        self.created_refs: list[str] = []
        self.deleted_refs: list[str] = []
        self.pulls: list[dict] = []
        self.mergeable = True

    def get_branch(self, name):
        if name not in self.branches:
            raise UnknownObjectException(404, {"message": "Branch not found"}, {})
        return SimpleNamespace(commit=SimpleNamespace(sha="basesha"))

    def get_git_commit(self, sha):
        return SimpleNamespace(sha=sha, tree=SimpleNamespace(sha="basetree"))

    def get_git_tree(self, sha, recursive=False):
        entries = [
            SimpleNamespace(path=p, mode="100644", type="blob", sha=f"blob:{p}") for p in self.files
        ]
        return SimpleNamespace(tree=entries, truncated=False)

    def get_git_blob(self, sha):
        data = self.files[sha.removeprefix("blob:")]
        return SimpleNamespace(content=base64.b64encode(data).decode(), encoding="base64")

    def create_git_blob(self, content, encoding):
        assert encoding == "base64"
        sha = f"new{len(self.blobs)}"
        self.blobs[sha] = base64.b64decode(content)
        return SimpleNamespace(sha=sha)

    def create_git_tree(self, elements, base_tree):
        assert all(isinstance(e, InputGitTreeElement) for e in elements)
        self.tree_elements = [e._identity for e in elements]
        return SimpleNamespace(sha="newtree")

    def create_git_commit(self, message, tree, parents):
        self.commit_message = message
        return SimpleNamespace(sha="commitsha")

    def create_git_ref(self, ref, sha):
        name = ref.removeprefix("refs/heads/")
        if name in self.branches:
            raise GithubException(422, {"message": "Reference already exists"}, {})
        self.branches.add(name)
        self.created_refs.append(name)

    def get_pulls(self, state, head):
        return [
            SimpleNamespace(number=3, html_url="https://github.com/acme/app/pull/3")
            for h in self.open_prs
            if head == f"acme:{h}"
        ]

    def create_pull(self, base, head, title, body, maintainer_can_modify):
        if self.create_pull_error:
            raise self.create_pull_error
        self.pulls.append({"base": base, "head": head, "title": title, "body": body})
        return SimpleNamespace(number=7, html_url="https://github.com/acme/app/pull/7")

    def get_pull(self, number):
        return SimpleNamespace(mergeable=self.mergeable)

    def get_git_ref(self, path):
        return SimpleNamespace(delete=lambda: self.deleted_refs.append(path))


def factory_for(repo: FakeRepo):
    calls: list[str] = []

    def factory(token: str):
        calls.append(token)
        return SimpleNamespace(get_repo=lambda full: repo)

    factory.calls = calls  # type: ignore[attr-defined]
    return factory


def failing_factory(exc: Exception):
    def get_repo(_full):
        raise exc

    return lambda _token: SimpleNamespace(get_repo=get_repo)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(github_pr, "_sleep", lambda _s: None)


def publish(repo_or_factory, cert=None, **kwargs):
    factory = repo_or_factory if callable(repo_or_factory) else factory_for(repo_or_factory)
    return github_pr.publish_pull_request(
        cert or make_cert(), token=TOKEN, owner="acme", name="app", github_factory=factory, **kwargs
    )


def repo_with_auth(**kwargs) -> FakeRepo:
    return FakeRepo({"auth.py": ORIGINAL.encode(), "README.md": b"hi\n"}, **kwargs)


# ------------------------------------------------------------------ the happy path


def test_creates_branch_commit_and_pull_request() -> None:
    repo = repo_with_auth()
    cert = make_cert()
    result = publish(repo, cert)

    assert result.number == 7 and result.url.endswith("/pull/7") and not result.reused
    assert result.base == "main" and result.mergeable is True
    assert result.branch == f"fixproof/patch-{result.patch_id}"
    assert repo.created_refs == [result.branch]
    assert [(f.path, f.change) for f in result.files_changed] == [("auth.py", "modified")]
    assert [e["path"] for e in repo.tree_elements] == ["auth.py"]
    new_text = repo.blobs[repo.tree_elements[0]["sha"]].decode()
    assert 'token_type == "refresh"' in new_text and 'token_type == "access"' not in new_text
    assert repo.pulls[0]["head"] == result.branch and repo.pulls[0]["base"] == "main"
    assert repo.pulls[0]["title"] == "fix: Accept refresh tokens in validate_refresh_token"
    assert "certificate" in repo.commit_message


def test_crlf_files_keep_their_line_endings() -> None:
    repo = FakeRepo({"auth.py": ORIGINAL.replace("\n", "\r\n").encode()})
    publish(repo)
    new_bytes = repo.blobs[repo.tree_elements[0]["sha"]]
    assert b'"refresh"' in new_bytes and b"\r\n" in new_bytes
    assert new_bytes.count(b"\n") == new_bytes.count(b"\r\n")


def test_deleting_a_file_sends_a_null_sha() -> None:
    diff = "--- a/README.md\n+++ /dev/null\n@@ -1 +0,0 @@\n-hi\n"
    cert = make_cert()
    cert.final_patch = diff
    repo = repo_with_auth()
    result = publish(repo, cert)
    assert repo.tree_elements == [
        {"path": "README.md", "mode": "100644", "type": "blob", "sha": None}
    ]
    assert result.files_changed[0].change == "deleted"


def test_explicit_base_branch_is_used() -> None:
    repo = repo_with_auth(branches=("main", "develop"))
    assert publish(repo, base_branch="develop").base == "develop"
    assert repo.pulls[0]["base"] == "develop"


# ------------------------------------------------------------------ PR description


def test_body_has_root_cause_fix_and_table_of_passed_tests_only() -> None:
    cert = make_cert()
    body = github_pr.build_pull_request_body(
        cert, files=[github_pr.ChangedFile(path="auth.py", change="modified")],
        patch_id="abc123", base="main",
    )  # fmt: skip
    assert "### 🔍 Root cause" in body and "refresh tokens fail" in body
    assert "### 🔧 The fix" in body and "Accept refresh tokens" in body
    assert "| # | Test | Intent | Status |" in body
    row = "| 1 | `refresh_token_accepted` | Refresh tokens must validate \\| exactly | ✅ Passed |"
    assert row in body
    assert "`access_token_rejected`" in body and "✅ Passed · unvalidated" in body
    assert "flaky_attack" not in body  # failed on this patch
    assert "excluded_by_human" not in body  # excluded by a human reviewer
    assert "Adversarial attack tests passed (2)" in body
    assert "@\u200boctocat" in body  # no accidental pings from model-written text
    assert "Isolation is process-level only." in body


def test_body_without_per_test_record_falls_back_to_grounded_tests() -> None:
    cert = make_cert()
    cert.iterations[0].test_results = {}
    names = [t.name for t in github_pr.passed_attack_tests(cert)]
    assert names == ["refresh_token_accepted", "flaky_attack"]


# ------------------------------------------------------------------ guards


def test_only_verified_patches_can_be_published() -> None:
    factory = factory_for(repo_with_auth())
    for verdict in (VerificationVerdict.NOT_VERIFIED, VerificationVerdict.INSUFFICIENT_EVIDENCE):
        with pytest.raises(github_pr.PullRequestError) as err:
            publish(factory, make_cert(verdict))
        assert err.value.code == "NOT_VERIFIED" and err.value.status_code == 409
    assert factory.calls == []  # never even contacted GitHub


def test_verified_with_conditions_is_allowed() -> None:
    result = publish(repo_with_auth(), make_cert(VerificationVerdict.VERIFIED_WITH_CONDITIONS))
    assert result.number == 7


def test_patch_touching_tests_is_refused() -> None:
    cert = make_cert()
    cert.final_patch = "--- a/tests/test_auth.py\n+++ b/tests/test_auth.py\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises(github_pr.PullRequestError) as err:
        publish(repo_with_auth(), cert)
    assert err.value.code == "INVALID_PATCH"


# ------------------------------------------------------------------ failure modes


def test_expired_token() -> None:
    exc = BadCredentialsException(401, {"message": "Bad credentials"}, {})
    with pytest.raises(github_pr.PullRequestError) as err:
        publish(failing_factory(exc))
    assert err.value.code == "TOKEN_EXPIRED" and err.value.status_code == 401


def test_rate_limit_reports_reset_time() -> None:
    exc = RateLimitExceededException(
        403, {"message": "API rate limit exceeded"}, {"x-ratelimit-reset": "1893456000"}
    )
    with pytest.raises(github_pr.PullRequestError) as err:
        publish(failing_factory(exc))
    assert err.value.code == "RATE_LIMITED" and err.value.status_code == 429
    assert err.value.details and err.value.details["reset_at"].startswith("2030-")


@pytest.mark.parametrize(
    ("exc", "code", "status"),
    [
        (UnknownObjectException(404, {"message": "Not Found"}, {}), "NOT_FOUND", 404),
        (
            GithubException(403, {"message": "Resource not accessible"}, {}),
            "INSUFFICIENT_PERMISSIONS", 403,
        ),
        (
            GithubException(403, {"message": "SAML enforcement"}, {"x-github-sso": "required"}),
            "SSO_REQUIRED", 403,
        ),
        (GithubException(500, {"message": "boom"}, {}), "GITHUB_API_ERROR", 502),
    ],
)  # fmt: skip
def test_repository_level_errors_are_translated(exc, code, status) -> None:
    with pytest.raises(github_pr.PullRequestError) as err:
        publish(failing_factory(exc))
    assert (err.value.code, err.value.status_code) == (code, status)


def test_missing_base_branch() -> None:
    with pytest.raises(github_pr.PullRequestError) as err:
        publish(repo_with_auth(), base_branch="nope")
    assert err.value.code == "NOT_FOUND"


def test_archived_and_read_only_repositories() -> None:
    repo = repo_with_auth()
    repo.archived = True
    with pytest.raises(github_pr.PullRequestError) as err:
        publish(repo)
    assert err.value.code == "REPO_ARCHIVED"
    repo = repo_with_auth()
    repo.permissions = SimpleNamespace(push=False)
    with pytest.raises(github_pr.PullRequestError) as err:
        publish(repo)
    assert err.value.code == "INSUFFICIENT_PERMISSIONS"


def test_patch_conflict_when_the_base_branch_moved_on() -> None:
    repo = FakeRepo({"auth.py": ORIGINAL.replace("access", "something_else").encode()})
    with pytest.raises(github_pr.PullRequestError) as err:
        publish(repo)
    assert err.value.code == "PATCH_CONFLICT" and err.value.status_code == 409
    assert err.value.details and "git" in err.value.details
    assert repo.created_refs == [] and repo.blobs == {}  # nothing was pushed


def test_branch_name_conflict_gets_a_fresh_suffix() -> None:
    cert = make_cert()
    first = publish(repo_with_auth(), cert)
    repo = repo_with_auth(branches=("main", first.branch))  # name taken, no PR on it
    result = publish(repo, cert)
    assert result.branch.startswith(f"{first.branch}-") and not result.reused
    assert repo.created_refs == [result.branch]


def test_publishing_twice_returns_the_existing_open_pr() -> None:
    cert = make_cert()
    first = publish(repo_with_auth(), cert)
    repo = repo_with_auth(branches=("main", first.branch), open_prs=[first.branch])
    result = publish(repo, cert)
    assert result.reused and result.number == 3 and result.branch == first.branch
    assert repo.pulls == [] and repo.created_refs == []


def test_failed_pr_creation_removes_the_pushed_branch() -> None:
    error = GithubException(
        422, {"message": "Validation Failed", "errors": [{"message": "No commits between"}]}, {}
    )
    repo = repo_with_auth(create_pull_error=error)
    with pytest.raises(github_pr.PullRequestError) as err:
        publish(repo)
    assert err.value.code == "NO_CHANGES"
    assert len(repo.deleted_refs) == 1 and repo.deleted_refs[0].startswith("heads/fixproof/patch-")


def test_merge_conflicts_on_the_new_pr_are_reported() -> None:
    repo = repo_with_auth()
    repo.mergeable = False
    result = publish(repo)
    assert result.mergeable is False and "merge conflicts" in (result.warning or "")


# ------------------------------------------------------------------ input parsing


@pytest.mark.parametrize(
    "text",
    ["acme/app", "https://github.com/acme/app", "https://github.com/acme/app.git", " acme/app/ "],
)
def test_parse_repository_accepts(text) -> None:
    assert github_pr.parse_repository(text) == ("acme", "app")


@pytest.mark.parametrize(
    "text", ["", "acme", "https://evil.com/acme/app", "a/b/c", "a b/c", "a/b;ls"]
)
def test_parse_repository_rejects(text) -> None:
    with pytest.raises(github_pr.PullRequestError):
        github_pr.parse_repository(text)


def test_branch_and_token_validation() -> None:
    assert github_pr.validate_base_branch("  ") is None
    assert github_pr.validate_base_branch("release/1.0") == "release/1.0"
    for bad in ("--upload-pack=x", "a..b", "x.lock", "trailing/"):
        with pytest.raises(github_pr.PullRequestError):
            github_pr.validate_base_branch(bad)
    assert github_pr.validate_token(f" {TOKEN} ") == TOKEN
    for bad in (None, "", "short", "bad token with spaces", "tok\nen12345678"):
        with pytest.raises(github_pr.PullRequestError):
            github_pr.validate_token(bad)


def test_repository_from_project() -> None:
    f = github_pr.repository_from_project
    assert f("git", "https://github.com/acme/app@develop") == ("acme", "app", "develop")
    assert f("git", "https://github.com/acme/app") == ("acme", "app", None)
    assert f("git", "https://gitlab.com/acme/app") is None
    assert f("zip", "app.zip") is None


# ------------------------------------------------------------------ HTTP endpoint


@pytest.fixture
def investigation(monkeypatch):
    monkeypatch.setattr(get_settings(), "github_token", None)

    def make(cert=None, **fields) -> str:
        state = InvestigationState(
            issue="Refresh token returns 401.", stage=InvestigationStage.COMPLETED,
            certificate=cert or make_cert(), example_case="buggy-python-app", **fields,
        )  # fmt: skip
        routes._INVESTIGATIONS[state.id] = state
        return state.id

    return make


def test_endpoint_opens_pr_and_forwards_token(monkeypatch, investigation) -> None:
    seen = {}

    def fake_publish(cert, **kwargs):
        seen.update(kwargs)
        return github_pr.PullRequestResult(
            number=9, url="https://github.com/acme/app/pull/9", branch="fixproof/patch-x",
            base="main", patch_id="x",
        )  # fmt: skip

    monkeypatch.setattr(routes, "publish_pull_request", fake_publish)
    iid = investigation()
    r = client.post(
        f"/api/v1/investigations/{iid}/pull-request",
        json={"repository": "https://github.com/acme/app", "base_branch": "develop"},
        headers={"X-GitHub-Token": TOKEN},
    )
    assert r.status_code == 200 and r.json()["number"] == 9
    assert (seen["owner"], seen["name"], seen["base_branch"], seen["token"]) == (
        "acme", "app", "develop", TOKEN,
    )  # fmt: skip
    assert TOKEN not in r.text


def test_endpoint_uses_the_server_token_when_none_is_sent(monkeypatch, investigation) -> None:
    seen = {}
    monkeypatch.setattr(
        routes, "publish_pull_request",
        lambda cert, **kw: seen.update(kw) or github_pr.PullRequestResult(
            number=1, url="u", branch="b", base="main", patch_id="x"
        ),
    )  # fmt: skip
    monkeypatch.setattr(get_settings(), "github_token", "ghp_servertoken1234567890")
    iid = investigation()
    r = client.post(f"/api/v1/investigations/{iid}/pull-request", json={"repository": "a/b"})
    assert r.status_code == 200 and seen["token"] == "ghp_servertoken1234567890"


def test_endpoint_error_shape_and_guards(monkeypatch, investigation) -> None:
    url = "/api/v1/investigations/{}/pull-request"
    body = {"repository": "acme/app"}

    r = client.post(url.format(investigation()), json=body)  # no token anywhere
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_MISSING"
    assert isinstance(r.json()["detail"], str)

    unverified = investigation(make_cert(VerificationVerdict.NOT_VERIFIED))
    r = client.post(url.format(unverified), json=body, headers={"X-GitHub-Token": TOKEN})
    assert r.status_code == 409 and r.json()["code"] == "NOT_VERIFIED"

    r = client.post(  # a bundled example is not a GitHub clone, so a repository is required
        url.format(investigation()), json={}, headers={"X-GitHub-Token": TOKEN}
    )
    assert r.status_code == 422 and r.json()["code"] == "REPOSITORY_REQUIRED"

    r = client.post(
        url.format(investigation()), json={"repository": "x.com/a/b"},
        headers={"X-GitHub-Token": TOKEN},
    )  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "INVALID_REPOSITORY"

    assert client.post(url.format("missing"), json=body).status_code == 404

    incomplete = InvestigationState(issue="A long enough issue text.")
    routes._INVESTIGATIONS[incomplete.id] = incomplete
    assert client.post(url.format(incomplete.id), json=body).status_code == 409


def test_endpoint_translates_github_failures(monkeypatch, investigation) -> None:
    def boom(cert, **_kw):
        raise github_pr.PullRequestError("PATCH_CONFLICT", "no longer applies", 409, {"git": "x"})

    monkeypatch.setattr(routes, "publish_pull_request", boom)
    r = client.post(
        f"/api/v1/investigations/{investigation()}/pull-request",
        json={"repository": "acme/app"}, headers={"X-GitHub-Token": TOKEN},
    )  # fmt: skip
    assert r.status_code == 409
    assert r.json() == {
        "detail": "no longer applies", "code": "PATCH_CONFLICT", "details": {"git": "x"},
    }  # fmt: skip
    assert routes._PR_IN_PROGRESS == set()  # the lock is always released


def test_about_reports_whether_github_is_configured(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "github_token", None)
    assert client.get("/api/v1/about").json()["github_configured"] is False
    monkeypatch.setattr(get_settings(), "github_token", "ghp_servertoken1234567890")
    assert client.get("/api/v1/about").json()["github_configured"] is True
