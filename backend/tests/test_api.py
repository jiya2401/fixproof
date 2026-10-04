from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_and_get_investigation() -> None:
    created = client.post(
        "/api/v1/investigations",
        json={
            "repo_url": "https://github.com/example/project",
            "issue": "Refresh token returns 401 after access token expiry.",
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["stage"] == "created"

    fetched = client.get(f"/api/v1/investigations/{payload['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["issue"] == payload["issue"]
