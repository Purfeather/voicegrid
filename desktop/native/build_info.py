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
    brand: str
    product: str
    author: str
    version: str
    build_id: str

    @property
    def display_version(self) -> str:
        core = self.version.split("-", 1)[0]
        parts = core.split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else core

    @property
    def window_title(self) -> str:
        return f"{self.product} {self.display_version}"


def _read_manifest() -> dict[str, Any]:
    try:
        payload = json.loads((ROOT / "build.json").read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


_manifest = _read_manifest()
BUILD_INFO = BuildInfo(
    brand=str(_manifest.get("brand") or "龙融影业"),
    product=str(_manifest.get("product") or "声格 VoiceGrid"),
    author=str(_manifest.get("author") or "Wang Xiaohan"),
    version=str(_manifest.get("version") or "2.0.0-dev"),
    build_id=str(_manifest.get("build_id") or "development"),
)

