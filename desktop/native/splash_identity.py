from __future__ import annotations

import json
from dataclasses import dataclass

from desktop.native.build_info import DESKTOP_DIR


@dataclass(frozen=True)
class SplashIdentity:
    organization: str
    author: str


def _load() -> SplashIdentity:
    try:
        payload = json.loads((DESKTOP_DIR / "splash-identity.json").read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("splash identity must be an object")
        organization = str(payload.get("organization") or "").strip()
        author = str(payload.get("author") or "").strip()
        if not organization or not author:
            raise ValueError("splash identity is incomplete")
        return SplashIdentity(organization=organization, author=author)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return SplashIdentity(organization="", author="")


SPLASH_IDENTITY = _load()
