from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from desktop.native.build_info import ROOT


STARTED_AT = time.perf_counter()
LOGS_DIR = Path(os.environ.get("MOSS_TTS_LOGS_DIR", ROOT / "data" / "logs")).resolve()
STARTUP_LOG = LOGS_DIR / "desktop-startup.log"
TRACE_PATH = Path(os.environ.get("MOSS_TTS_TRACE_PATH", LOGS_DIR / "startup-trace-latest.jsonl")).resolve()


class StartupTrace:
    def __init__(self, path: Path, started_at: float = STARTED_AT) -> None:
        self.path = path
        self.started_at = started_at
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def record(self, event: str, phase: str, message: str = "", **extra: Any) -> None:
        payload = {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "elapsed_ms": round((time.perf_counter() - self.started_at) * 1000),
            "event": event,
            "phase": phase,
            "message": message,
            "pid": os.getpid(),
            "thread": threading.current_thread().name,
            **extra,
        }
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")


def startup_log(message: str, reset: bool = False) -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        mode = "w" if reset else "a"
        with STARTUP_LOG.open(mode, encoding="utf-8", newline="\n") as handle:
            handle.write(f"[{datetime.now().isoformat(timespec='milliseconds')}] {message}\n")
    except OSError:
        # Logging is diagnostic only. A locked or read-only log directory must
        # never block startup, shutdown, or the recovery handshake.
        return


def json_request(host: str, port: int, path: str, method: str = "GET", timeout: float = .6) -> dict[str, Any] | None:
    request = urllib.request.Request(f"http://{host}:{port}{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
