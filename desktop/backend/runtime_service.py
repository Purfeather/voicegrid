from __future__ import annotations

import threading
from typing import Any

from app.model_engine import ENGINE

from .module_service import MODULE_SERVICE
from .worker_manager import WORKERS


class RuntimeService:
    """Coordinate mutually exclusive GPU runtimes without importing optional models."""

    def __init__(self) -> None:
        self.lock = threading.RLock()

    def prepare(self, module_id: str) -> None:
        with self.lock:
            if module_id == "speech":
                WORKERS.release()
                return
            if module_id in {"voice_design", "sound_effect"}:
                ENGINE.release()
                return
            raise ValueError("未知的运行模块。")

    def describe(self) -> dict[str, Any]:
        speech = ENGINE.describe()
        optional = WORKERS.describe()
        module_records = MODULE_SERVICE.list()
        models = [
            *speech.get("models", []),
            *[
                {
                    "key": descriptor["id"],
                    "name": descriptor["model_name"],
                    "version": descriptor.get("version", ""),
                    "installed": descriptor["installed"],
                    "enabled": descriptor.get("engine_available", False),
                }
                for descriptor in module_records
                if descriptor["id"] != "speech"
            ],
        ]
        if optional.get("active_module"):
            return {**optional, "models": models}
        active = bool(speech.get("active_model")) or speech.get("state") in {"loading", "loaded", "running", "releasing"}
        return {**speech, "active_module": "speech" if active else None, "models": models}

    def release(self) -> dict[str, Any]:
        with self.lock:
            ENGINE.release()
            WORKERS.release()
        return self.describe()


RUNTIME = RuntimeService()
