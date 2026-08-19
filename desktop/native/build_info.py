from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DESKTOP_DIR = ROOT / "desktop"
ASSETS_DIR = DESKTOP_DIR / "assets"


@dataclass(frozen=True)
class BuildInfo:
    product: str
    version: str
    build_id: str

    @property
    def display_version(self) -> str:
        core = self.version.split("-", 1)[0]
        parts = core.split(".")
        if len(parts) >= 3:
            return core
        return ".".join(parts[:2]) if len(parts) >= 2 else core

    @property
    def window_title(self) -> str:
        return self.product


def _read_manifest() -> dict[str, Any]:
    try:
        payload = json.loads((ROOT / "build.json").read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


_manifest = _read_manifest()
BUILD_INFO = BuildInfo(
    product=str(_manifest.get("product") or "声格 VoiceGrid"),
    version=str(_manifest.get("version") or "1.0.2"),
    build_id=str(_manifest.get("build_id") or "VOICEGRID-1.0.2"),
)
