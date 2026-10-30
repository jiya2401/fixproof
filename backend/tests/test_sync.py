"""Tests for Feature 1: The 'Kill Switch' Live Local File Sync.

Covers:
  1. sync_worker.py ignore filter and debouncer
  2. POST /api/v1/project/sync endpoint:
     - writing file content to project workspace
     - deleting file from workspace
     - path traversal protection (boundary security)
     - invoking SandboxRunner to re-run tests
  3. WebSocket /api/v1/ws/sync connection and live event broadcasting
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.routes import SyncConnectionManager
from app.main import app
from app.projects import ProjectInfo, ProjectStore

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sync_worker import DebouncedChangeHandler

# ---------------------------------------------------------------------------
# 1. sync_worker.py Tests
# ---------------------------------------------------------------------------


class TestSyncWorkerFilter:
    def test_should_ignore_systemic_directories(self, tmp_path):
        handler = DebouncedChangeHandler(root_dir=tmp_path, sync_url="http://test/sync")

        assert handler._should_ignore(str(tmp_path / ".git" / "config")) is True
        assert handler._should_ignore(str(tmp_path / "__pycache__" / "mod.pyc")) is True
        assert handler._should_ignore(str(tmp_path / "node_modules" / "pkg" / "index.js")) is True
        assert handler._should_ignore(str(tmp_path / ".venv" / "lib" / "site.py")) is True
        ignored_proj = str(tmp_path / ".fixproof_projects" / "slot" / "a.py")
        assert handler._should_ignore(ignored_proj) is True

    def test_should_ignore_temp_and_hidden_files(self, tmp_path):
        handler = DebouncedChangeHandler(root_dir=tmp_path, sync_url="http://test/sync")

        assert handler._should_ignore(str(tmp_path / ".DS_Store")) is True
        assert handler._should_ignore(str(tmp_path / "file.tmp")) is True
        assert handler._should_ignore(str(tmp_path / "main.py~")) is True
        assert handler._should_ignore(str(tmp_path / ".swp")) is True

    def test_should_accept_valid_source_files(self, tmp_path):
        handler = DebouncedChangeHandler(root_dir=tmp_path, sync_url="http://test/sync")

        assert handler._should_ignore(str(tmp_path / "src" / "main.py")) is False
        assert handler._should_ignore(str(tmp_path / "index.ts")) is False
        assert handler._should_ignore(str(tmp_path / "pkg" / "calc_test.go")) is False

    def test_debounce_coalesces_rapid_events(self, tmp_path):
        """Rapid modifications to the same file should coalesce into one dispatch."""
        sent_payloads = []

        handler = DebouncedChangeHandler(
            root_dir=tmp_path,
            sync_url="http://test/sync",
            project_id="test12345678",
            debounce_seconds=0.05,
        )
        handler._send_payload = lambda payload: sent_payloads.append(payload)

        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1\n", encoding="utf-8")

        # Fire 3 rapid events
        handler._schedule_sync(str(test_file), event_type="modified")
        handler._schedule_sync(str(test_file), event_type="modified")
        handler._schedule_sync(str(test_file), event_type="modified")

        # Before debounce expires, nothing should be sent
        assert len(sent_payloads) == 0

        # Wait for debounce timer to fire
        time.sleep(0.12)

        assert len(sent_payloads) == 1
        assert sent_payloads[0]["file_path"] == "app.py"
        assert sent_payloads[0]["project_id"] == "test12345678"
        assert "x = 1" in sent_payloads[0]["content"]

    def test_missing_watchdog_does_not_crash_import(self):
        import sync_worker

        assert hasattr(sync_worker, "HAS_WATCHDOG")

    def test_main_exits_with_clear_message_if_watchdog_missing(self, monkeypatch):
        import sync_worker

        monkeypatch.setattr(sync_worker, "HAS_WATCHDOG", False)
        with pytest.raises(SystemExit) as exc:
            sync_worker.main()
        assert "pip install watchdog" in str(exc.value)


# ---------------------------------------------------------------------------
# 2. POST /api/v1/project/sync Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def test_project(tmp_path):
    """Creates a temporary ProjectStore slot with a Python stub."""
    store_dir = tmp_path / "store"
    store = ProjectStore(root=store_dir)
    info = ProjectInfo(name="live_sync_demo", origin="local")
    slot = store_dir / info.id
    src = slot / "src"
    src.mkdir(parents=True)
    (src / "calc.py").write_text("def add(a, b): return a + b\n")
    (src / "test_calc.py").write_text(
        "from calc import add\ndef test_add(): assert add(1, 2) == 3\n"
    )
    store._finish(info)
    return info, src, store


class TestProjectSyncEndpoint:
    def test_sync_modifies_file_and_runs_tests(self, test_project):
        info, src, store = test_project
        client = TestClient(app)

        mock_result = {
            "total_tests": 1,
            "passed": 1,
            "failed": 0,
            "errors": 0,
            "duration_seconds": 0.1,
            "timed_out": False,
            "failures": [],
        }

        with (
            patch("app.api.routes._store", return_value=store),
            patch("app.api.routes.get_sandbox") as mock_get_sandbox,
            patch("app.api.routes._run_sync_tests", return_value=mock_result),
        ):
            mock_get_sandbox.return_value = MagicMock()

            resp = client.post(
                "/api/v1/project/sync",
                json={
                    "project_id": info.id,
                    "file_path": "calc.py",
                    "content": "def add(a, b): return a + b + 0\n",
                    "event_type": "modified",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["project_id"] == info.id
            assert data["file_path"] == "calc.py"
            assert data["language"] == "python"
            assert data["test_result"]["passed"] == 1

            # Verify file was actually written on disk
            content = (src / "calc.py").read_text(encoding="utf-8")
            assert content == "def add(a, b): return a + b + 0\n"

    def test_sync_handles_file_deletion(self, test_project):
        info, src, store = test_project
        client = TestClient(app)

        target_file = src / "to_delete.py"
        target_file.write_text("x = 1\n", encoding="utf-8")
        assert target_file.exists()

        mock_result = {
            "total_tests": 1,
            "passed": 1,
            "failed": 0,
            "errors": 0,
            "duration_seconds": 0.1,
            "timed_out": False,
            "failures": [],
        }

        with (
            patch("app.api.routes._store", return_value=store),
            patch("app.api.routes.get_sandbox"),
            patch("app.api.routes._run_sync_tests", return_value=mock_result),
        ):
            resp = client.post(
                "/api/v1/project/sync",
                json={
                    "project_id": info.id,
                    "file_path": "to_delete.py",
                    "event_type": "deleted",
                },
            )

            assert resp.status_code == 200
            assert not target_file.exists()

    def test_sync_blocks_path_traversal(self, test_project):
        info, src, store = test_project
        client = TestClient(app)

        with patch("app.api.routes._store", return_value=store):
            resp = client.post(
                "/api/v1/project/sync",
                json={
                    "project_id": info.id,
                    "file_path": "../../secret.txt",
                    "content": "malicious",
                    "event_type": "modified",
                },
            )
            assert resp.status_code == 400
            detail = resp.json()["detail"]
            assert "Invalid relative" in detail or "traversal" in detail


# ---------------------------------------------------------------------------
# 3. WebSocket Connection & Broadcast Tests
# ---------------------------------------------------------------------------


class TestWebSocketSync:
    def test_websocket_sync_endpoint_connects(self):
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/sync") as websocket:
            websocket.send_text("ping")
            # Connection stays open without crashing

    @pytest.mark.anyio
    async def test_sync_connection_manager_broadcast(self):
        manager = SyncConnectionManager()
        ws_mock = AsyncMock()
        await manager.connect(ws_mock)

        assert len(manager.active_connections) == 1

        payload = {"event": "TESTS_RE_RUNNING", "file_path": "test.py"}
        await manager.broadcast(payload)

        ws_mock.send_json.assert_awaited_once_with(payload)

        manager.disconnect(ws_mock)
        assert len(manager.active_connections) == 0
