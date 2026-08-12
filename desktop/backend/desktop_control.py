from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable


class DesktopControl:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.handler: Callable[[str], str] | None = None
        self.status_provider: Callable[[], dict[str, Any]] | None = None

    def register(
        self,
        handler: Callable[[str], str] | None,
        status_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        with self.lock:
            self.handler = handler
            self.status_provider = status_provider

    def command(self, action: str) -> str:
        with self.lock:
            if self.handler is None:
                raise RuntimeError("桌面宿主尚未连接。")
            return self.handler(action)

    def status(self) -> dict[str, Any]:
        with self.lock:
            if self.status_provider is None:
                return {"native": self.handler is not None, "ready": False, "phase": "api"}
            return {"native": self.handler is not None, **self.status_provider()}


DESKTOP = DesktopControl()
