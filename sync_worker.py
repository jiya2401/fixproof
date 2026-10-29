#!/usr/bin/env python3
"""FixProof Live Local File Sync Worker ("Kill Switch").

Watches a local development directory for file modifications, creations, and deletions,
debounces burst saves (300ms), and hot-syncs changes to the FixProof backend to trigger
real-time multi-language test execution passes.

Usage:
    python sync_worker.py
    python sync_worker.py --dir /path/to/project --project-id abc123def456
    python sync_worker.py --url http://localhost:8000/api/v1/project/sync
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    sys.exit(
        "ERROR: 'watchdog' package is required by sync_worker.py.\n"
        "Please install it using:\n"
        "    pip install watchdog\n"
    )

# Systemic paths and directories to ignore completely
IGNORE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".fixproof_projects",
        "node_modules",
        ".venv",
        "venv",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "coverage",
        ".nyc_output",
        "fixproof_adv",
    }
)

IGNORE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".tmp",
        ".swp",
        ".swo",
        "~",
        ".DS_Store",
        ".crdownload",
    }
)


class DebouncedChangeHandler(FileSystemEventHandler):
    """Watches filesystem events and coalesces rapid saves with a 300ms debounce buffer."""

    def __init__(
        self,
        root_dir: Path,
        sync_url: str,
        project_id: str | None = None,
        debounce_seconds: float = 0.3,
    ) -> None:
        super().__init__()
        self.root_dir = root_dir.resolve()
        self.sync_url = sync_url
        self.project_id = project_id
        self.debounce_seconds = debounce_seconds

        self._lock = threading.Lock()
        self._pending_timers: dict[str, threading.Timer] = {}

    def _should_ignore(self, path_str: str) -> bool:
        """Return True if path should be ignored by the sync worker."""
        p = Path(path_str)
        try:
            rel = p.relative_to(self.root_dir)
        except ValueError:
            return True

        for part in rel.parts:
            if part in IGNORE_DIRS:
                return True

        if p.name.startswith((".", "~")):
            return True

        if any(p.name.endswith(suffix) for suffix in IGNORE_SUFFIXES):
            return True

        return False

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._schedule_sync(event.src_path, event_type="modified")

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._schedule_sync(event.src_path, event_type="created")

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._schedule_sync(event.src_path, event_type="deleted")

    def _schedule_sync(self, src_path: str, event_type: str) -> None:
        if self._should_ignore(src_path):
            return

        with self._lock:
            if src_path in self._pending_timers:
                self._pending_timers[src_path].cancel()

            timer = threading.Timer(
                self.debounce_seconds,
                self._dispatch_sync,
                args=(src_path, event_type),
            )
            self._pending_timers[src_path] = timer
            timer.start()

    def _dispatch_sync(self, src_path: str, event_type: str) -> None:
        with self._lock:
            self._pending_timers.pop(src_path, None)

        abs_path = Path(src_path)
        try:
            rel_path = abs_path.relative_to(self.root_dir)
            rel_posix = PurePosixPath(rel_path.as_posix())
        except ValueError:
            return

        content = None
        if event_type != "deleted":
            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                print(f"[!] Warning: Could not read {rel_posix}: {exc}")
                return

        payload = {
            "project_id": self.project_id,
            "file_path": str(rel_posix),
            "content": content,
            "event_type": event_type,
        }

        self._send_payload(payload)

    def _send_payload(self, payload: dict) -> None:
        file_path = payload.get("file_path", "")
        event_type = payload.get("event_type", "modified")
        print(f"\n[⚡ Hot-Sync] {event_type.upper()}: {file_path} -> sending to FixProof...")

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.sync_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                elapsed = time.monotonic() - t0
                body = json.loads(resp.read().decode("utf-8"))
                self._log_response(body, elapsed)
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            print(f"[✗ HTTP {exc.code} Error] Failed to sync {file_path}: {err_body}")
        except Exception as exc:
            print(f"[✗ Connection Error] Could not connect to {self.sync_url}: {exc}")

    def _log_response(self, response: dict, elapsed: float) -> None:
        lang = response.get("language", "unknown").upper()
        res = response.get("test_result") or {}
        total = res.get("total_tests", 0)
        passed = res.get("passed", 0)
        failed = res.get("failed", 0)
        errors = res.get("errors", 0)
        dur = res.get("duration_seconds", 0.0)

        if failed == 0 and errors == 0:
            status_str = f"✓ ALL {passed}/{total} TESTS PASSED"
        else:
            status_str = f"✗ TESTS FAILED ({failed} failed, {errors} errors, {passed} passed)"

        print(f"[{status_str}] {lang} | Test: {dur:.2f}s | Roundtrip: {elapsed:.2f}s")
        failures = res.get("failures") or []
        for f in failures[:5]:
            tname = f.get("test_name", "test")
            msg = f.get("message", "").strip().splitlines()
            first_line = msg[0] if msg else "failed"
            print(f"    - {tname}: {first_line[:120]}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FixProof Live Local File Sync Worker ('Kill Switch')"
    )
    parser.add_argument(
        "--dir",
        "-d",
        default=".",
        help="Local directory to monitor (default: current working directory)",
    )
    parser.add_argument(
        "--url",
        "-u",
        default="http://localhost:8000/api/v1/project/sync",
        help="Backend sync endpoint URL (default: http://localhost:8000/api/v1/project/sync)",
    )
    parser.add_argument(
        "--project-id",
        "-p",
        default=None,
        help="FixProof project ID (optional; defaults to the active project in memory)",
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=0.3,
        help="Debounce interval in seconds (default: 0.3 = 300ms)",
    )

    args = parser.parse_args()

    watch_path = Path(args.dir).resolve()
    if not watch_path.is_dir():
        sys.exit(f"ERROR: Specified watch directory does not exist: {watch_path}")

    print("=================================================================")
    print("      FixProof Live Local File Sync ('Kill Switch') Active       ")
    print("=================================================================")
    print(f"Watching directory : {watch_path}")
    print(f"Sync Endpoint      : {args.url}")
    print(f"Debounce interval  : {int(args.debounce * 1000)}ms")
    if args.project_id:
        print(f"Target Project ID  : {args.project_id}")
    else:
        print("Target Project ID  : Auto-detecting active project in memory")
    print("Ignore list        : .git, node_modules, __pycache__, .venv, etc.")
    print("\n[Ctrl + S in your editor will immediately re-run tests on FixProof]")
    print("Press Ctrl + C to stop watching.\n")

    handler = DebouncedChangeHandler(
        root_dir=watch_path,
        sync_url=args.url,
        project_id=args.project_id,
        debounce_seconds=args.debounce,
    )

    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping FixProof live file sync worker...")
        observer.stop()
    observer.join()
    print("Live file sync worker stopped.")


if __name__ == "__main__":
    main()
