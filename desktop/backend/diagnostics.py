from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from .paths import LOGS_DIR


_LOG_LOCK = threading.RLock()


def append_diagnostic_log(name: str, message: str) -> Path:
    safe_name = "".join(character for character in name if character.isalnum() or character in {"-", "_"}) or "diagnostic"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    target = LOGS_DIR / f"{safe_name}.log"
    timestamp = datetime.now().isoformat(timespec="milliseconds")
    with _LOG_LOCK, target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"[{timestamp}] {message.rstrip()}\n")
    return target
