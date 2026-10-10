import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.pipeline import factory
from app.pipeline.runner import RepairPipeline
from app.sandbox.local import LocalSandbox
from tests.conftest import fixture_text
from tests.doubles import AUTH_ADVERSARIAL, ScriptedFixer, ScriptedPlanner

client = TestClient(app)
BODY = {"repo_url": "https://github.com/example/project", "issue": "Refresh token returns 401."}


def test_health() -> None:
    assert client.get("/health").json()["status"] == "ok"


def test_create_and_get_investigation() -> None:
    created = client.post("/api/v1/investigations", json=BODY)
    assert created.status_code == 201 and created.json()["stage"] == "created"
    fetched = client.get(f"/api/v1/investigations/{created.json()['id']}")
    assert fetched.json()["issue"] == BODY["issue"]


def test_unknown_example_case_rejected() -> None:
    r = client.post("/api/v1/investigations", json={**BODY, "example_case": "../../etc"})
    assert r.status_code == 422


def test_run_without_example_case_is_rejected() -> None:
    inv = client.post("/api/v1/investigations", json=BODY).json()
    assert client.post(f"/api/v1/investigations/{inv['id']}/run").status_code == 422


def test_run_without_nebius_key_fails_loudly_not_fake(monkeypatch) -> None:
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "nebius_api_key", None)
    inv = client.post("/api/v1/investigations", json={**BODY, "example_case": "buggy-python-app"})
    r = client.post(f"/api/v1/investigations/{inv.json()['id']}/run")
    assert r.status_code == 503 and "NEBIUS_API_KEY" in r.json()["detail"]
    assert client.get(f"/api/v1/investigations/{inv.json()['id']}/certificate").status_code == 404


@pytest.fixture
def scripted_factory(monkeypatch):
    def build(on_event=None, *, adversarial=True):
        return RepairPipeline(
            sandbox=LocalSandbox(),
            fixer=ScriptedFixer(
                [fixture_text("auth_weak.diff"), fixture_text("auth_correct.diff")]
            ),
            planner=ScriptedPlanner([AUTH_ADVERSARIAL]),
            on_event=on_event,
        )

    monkeypatch.setattr(factory, "build_pipeline", build)


def test_run_produces_certificate_via_api(scripted_factory) -> None:
    inv = client.post("/api/v1/investigations", json={**BODY, "example_case": "buggy-python-app"})
    iid = inv.json()["id"]
    assert client.post(f"/api/v1/investigations/{iid}/run").status_code == 202
    for _ in range(100):
        state = client.get(f"/api/v1/investigations/{iid}").json()
        if state["stage"] in ("completed", "failed"):
            break
        time.sleep(0.3)
    assert state["stage"] == "completed", state.get("error")
    cert = client.get(f"/api/v1/investigations/{iid}/certificate").json()
    assert cert["verdict"] == "verified_with_conditions" and len(cert["iterations"]) == 2
    assert state["verdict"] == cert["verdict"]
