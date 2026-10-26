import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.config import get_settings
from app.main import app
from app.pipeline import factory
from app.pipeline.runner import RepairPipeline
from app.sandbox.local import LocalSandbox
from tests.conftest import REPO_ROOT, fixture_text
from tests.doubles import PAGINATE_ADVERSARIAL, ScriptedFixer, ScriptedPlanner

client = TestClient(app)
TARGET = "test_paginate.py::test_second_page_returns_items_4_to_6"
ISSUE = "paginate returns the wrong slice for page 2"


def zip_dir(path: Path, top: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for file in path.rglob("*"):
            if file.is_file() and "__pycache__" not in file.parts:
                rel = file.relative_to(path).as_posix()
                archive.write(file, f"{top}/{rel}" if top else rel)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "projects_dir", str(tmp_path / "projects"))
    monkeypatch.setattr(routes, "get_sandbox", lambda: LocalSandbox())


def upload(top: str | None = "paginate-main") -> dict:
    data = zip_dir(REPO_ROOT / "examples" / "paginate-app", top)
    response = client.post(
        "/api/v1/projects/upload", content=data,
        headers={"Content-Type": "application/zip", "X-Filename": "paginate-main.zip"},
    )  # fmt: skip
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_scan_pick_failing_test_and_run_on_your_own_project(monkeypatch) -> None:
    project = upload()
    assert (
        project["python_files"] == 2 and project["test_files"] == 1 and project["origin"] == "zip"
    )

    scan = client.post(f"/api/v1/projects/{project['id']}/scan").json()
    assert [t["node_id"] for t in scan["failing_tests"]] == [TARGET]

    def build(on_event=None, *, adversarial=True):
        return RepairPipeline(
            sandbox=LocalSandbox(),
            fixer=ScriptedFixer(
                [fixture_text("paginate_weak.diff"), fixture_text("paginate_correct.diff")]
            ),
            planner=ScriptedPlanner([PAGINATE_ADVERSARIAL]),
            on_event=on_event,
        )

    monkeypatch.setattr(factory, "build_pipeline", build)
    created = client.post(
        "/api/v1/investigations",
        json={"issue": ISSUE, "project_id": project["id"], "repro_targets": [TARGET]},
    )
    assert created.status_code == 201, created.text
    iid = created.json()["id"]
    assert created.json()["project_name"] == "paginate-main"
    assert client.post(f"/api/v1/investigations/{iid}/run").status_code == 202
    for _ in range(100):
        state = client.get(f"/api/v1/investigations/{iid}").json()
        if state["stage"] in ("completed", "failed"):
            break
        time.sleep(0.3)
    assert state["stage"] == "completed", state.get("error")
    assert any(e["stage"] == "reproducing" for e in state["events"])  # live progress is recorded
    cert = state["certificate"]
    assert cert["source_label"] == "project/paginate-main" and len(cert["iterations"]) == 2
    assert cert["verdict"] == "verified_with_conditions"


def test_bad_repro_targets_are_rejected_at_creation() -> None:
    project = upload()
    for targets in ([], ["--rootdir=/"], ["../x.py"], ["nope.py::t"]):
        r = client.post(
            "/api/v1/investigations",
            json={"issue": ISSUE, "project_id": project["id"], "repro_targets": targets},
        )
        assert r.status_code == 422, targets


def test_project_and_example_are_mutually_exclusive_and_ids_are_checked() -> None:
    project = upload()
    both = {"issue": ISSUE, "project_id": project["id"], "example_case": "paginate-app"}
    assert client.post("/api/v1/investigations", json=both).status_code == 422
    missing = {"issue": ISSUE, "project_id": "0" * 12, "repro_targets": [TARGET]}
    assert client.post("/api/v1/investigations", json=missing).status_code == 404
    assert client.get("/api/v1/projects/..%2F..").status_code in (404, 422)


def test_upload_errors_are_clear() -> None:
    bad = client.post("/api/v1/projects/upload", content=b"nope", headers={"X-Filename": "x.zip"})
    assert bad.status_code == 422 and "zip" in bad.json()["detail"]
    slip = io.BytesIO()
    with zipfile.ZipFile(slip, "w") as z:
        z.writestr("../evil.py", "x")
    r = client.post("/api/v1/projects/upload", content=slip.getvalue())
    assert r.status_code == 422 and "unsafe" in r.json()["detail"]


def test_git_and_local_intake_are_guarded() -> None:
    assert client.post("/api/v1/projects/git", json={"url": "file:///etc"}).status_code == 422
    r = client.post("/api/v1/projects/local", json={"path": "/etc"})
    assert r.status_code == 422 and "disabled" in r.json()["detail"]


def test_project_can_be_deleted() -> None:
    project = upload()
    assert client.delete(f"/api/v1/projects/{project['id']}").status_code == 204
    assert client.get(f"/api/v1/projects/{project['id']}").status_code == 404


def test_benchmark_endpoint_never_invents_results(tmp_path, monkeypatch) -> None:
    data = client.get("/api/v1/benchmark").json()
    assert data["available"] in (True, False)
    if data["available"]:
        assert "trials" in data["report"]


def test_about_lists_every_validated_case() -> None:
    about = client.get("/api/v1/about").json()
    assert len(about["example_cases"]) == 7 and about["project_sources"]["zip"] is True
    assert set(about["example_issues"]) == set(about["example_cases"])
