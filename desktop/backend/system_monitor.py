from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
from datetime import datetime
from typing import Any

import psutil


def _empty_snapshot() -> dict[str, Any]:
    return {
        "cpu_percent": 0.0,
        "memory_used_gb": 0.0,
        "memory_total_gb": 0.0,
        "memory_percent": 0.0,
        "gpu_name": "",
        "gpu_percent": None,
        "vram_used_gb": None,
        "vram_total_gb": None,
        "python_version": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "timestamp": "",
    }


def _gpu_metrics() -> dict[str, Any]:
    if os.environ.get("MOSS_TTS_FAULT") == "hardware_failure":
        raise RuntimeError("startup-lab hardware fault")
    command = [
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=2,
        check=True,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    values = [part.strip() for part in result.stdout.splitlines()[0].split(",")]
    return {
        "gpu_name": values[0],
        "gpu_percent": float(values[1]),
        "vram_used_gb": round(float(values[2]) / 1024, 2),
        "vram_total_gb": round(float(values[3]) / 1024, 2),
    }


class HardwareMonitor:
    def __init__(self, interval: float = 2.0) -> None:
        self.interval = interval
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.cached = _empty_snapshot()

    def start(self) -> None:
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, name="hardware-monitor", daemon=True)
            self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                memory = psutil.virtual_memory()
                try:
                    gpu = _gpu_metrics()
                except Exception:
                    gpu = {"gpu_name": "", "gpu_percent": None, "vram_used_gb": None, "vram_total_gb": None}
                value = {
                    "cpu_percent": float(psutil.cpu_percent(interval=None)),
                    "memory_used_gb": round((memory.total - memory.available) / 1024**3, 2),
                    "memory_total_gb": round(memory.total / 1024**3, 2),
                    "memory_percent": float(memory.percent),
                    **gpu,
                    "python_version": platform.python_version(),
                    "platform": f"{platform.system()} {platform.release()}",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }
                with self.lock:
                    self.cached = value
            except Exception:
                pass
            finally:
                self.stop_event.wait(self.interval)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.cached)

    def stop(self) -> None:
        self.stop_event.set()
        thread = self.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.5)
        self.thread = None


MONITOR = HardwareMonitor()


def snapshot() -> dict[str, Any]:
    return MONITOR.snapshot()
