from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from typing import Any, Callable

from app.model_engine import TaskCancelled

from .diagnostics import append_diagnostic_log
from .paths import ROOT, VOICE_GENERATOR_CODEC_DIR, VOICE_GENERATOR_MODEL_DIR, VOICE_GENERATOR_RUNTIME_DIR


PROTOCOL_PREFIX = "VOICEGRID_EVENT "


def _append_worker_log(message: str) -> None:
    append_diagnostic_log("voice-design-worker", message)


class WorkerManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.request_lock = threading.RLock()
        self.process: subprocess.Popen[str] | None = None
        self.reader: threading.Thread | None = None
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=256)
        self.active_module: str | None = None
        self.state = "idle"
        self.message = "可选模型未加载"
        self.device = ""
        self.dtype = ""
        self.attention = ""
        self.diagnostic_tail: list[str] = []

    def _reader_loop(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            _append_worker_log(line.rstrip("\r\n"))
            if not line.startswith(PROTOCOL_PREFIX):
                clean = line.strip()
                if clean:
                    self.diagnostic_tail = [*self.diagnostic_tail[-19:], clean]
                continue
            try:
                self.messages.put(json.loads(line[len(PROTOCOL_PREFIX):]), timeout=1)
            except Exception:
                continue

    def _start_voice_design(self) -> None:
        python = VOICE_GENERATOR_RUNTIME_DIR / "Scripts" / "python.exe"
        if not python.is_file():
            raise FileNotFoundError("音色设计运行环境尚未安装。")
        if not VOICE_GENERATOR_MODEL_DIR.is_dir() or not VOICE_GENERATOR_CODEC_DIR.is_dir():
            raise FileNotFoundError("音色设计模型尚未完整安装。")
        self.release()
        while True:
            try:
                self.messages.get_nowait()
            except queue.Empty:
                break
        self.diagnostic_tail = []
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        env = os.environ.copy()
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        command = [
            str(python),
            str(ROOT / "desktop" / "workers" / "voice_generator_worker.py"),
            "--model",
            str(VOICE_GENERATOR_MODEL_DIR),
            "--codec",
            str(VOICE_GENERATOR_CODEC_DIR),
        ]
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )
        _append_worker_log(f"WORKER START pid={process.pid} command={subprocess.list2cmdline(command)}")
        self.process = process
        self.active_module = "voice_design"
        self.state = "loading"
        self.message = "正在启动 MOSS-VoiceGenerator"
        self.reader = threading.Thread(target=self._reader_loop, args=(process,), name="voice-design-worker-reader", daemon=True)
        self.reader.start()
        deadline = time.monotonic() + 15
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    detail = "\n".join(self.diagnostic_tail[-4:])
                    raise RuntimeError(f"音色设计工作进程启动失败。{(' ' + detail) if detail else ''}")
                try:
                    message = self.messages.get(timeout=.2)
                except queue.Empty:
                    continue
                if message.get("event") == "ready":
                    return
            raise TimeoutError("音色设计工作进程启动超时。")
        except Exception:
            self.release()
            raise

    def request_voice_design(
        self,
        payload: dict[str, Any],
        progress: Callable[[float, str], None],
        cancelled: Callable[[], bool],
    ) -> dict[str, Any]:
        with self.request_lock:
            with self.lock:
                if self.process is None or self.process.poll() is not None or self.active_module != "voice_design":
                    self._start_voice_design()
                process = self.process
            assert process is not None and process.stdin is not None
            request_id = uuid.uuid4().hex
            command = {"request_id": request_id, "action": "generate", **payload}
            process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            process.stdin.flush()
            self.state = "running"
            self.message = "正在生成设计音色"
            while True:
                if cancelled():
                    self.release()
                    raise TaskCancelled("音色设计任务已停止。")
                if process.poll() is not None:
                    self.state = "error"
                    self.message = "音色设计工作进程异常退出"
                    detail = "\n".join(self.diagnostic_tail[-4:])
                    raise RuntimeError(f"{self.message}。{detail}" if detail else self.message)
                try:
                    message = self.messages.get(timeout=.2)
                except queue.Empty:
                    continue
                event = message.get("event")
                if event in {"progress", "loaded"}:
                    self.device = str(message.get("device") or self.device)
                    self.dtype = str(message.get("dtype") or self.dtype)
                    self.attention = str(message.get("attention") or self.attention)
                    self.message = str(message.get("message") or self.message)
                    progress(float(message.get("progress", .5)), self.message)
                    continue
                if message.get("request_id") != request_id:
                    continue
                if event == "result":
                    self.state = "loaded"
                    self.message = "MOSS-VoiceGenerator 已就绪（显存已释放）"
                    return dict(message["result"])
                if event == "error":
                    self.state = "error"
                    self.message = str(message.get("message") or "音色设计生成失败")
                    raise RuntimeError(self.message)

    def describe(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "active_model": "MOSS-VoiceGenerator · 1.7B" if self.active_module == "voice_design" else None,
            "active_module": self.active_module,
            "message": self.message,
            "device": self.device,
            "dtype": self.dtype,
            "attention": self.attention,
        }

    def release(self) -> None:
        with self.lock:
            process = self.process
            self.process = None
            self.active_module = None
        if process is not None:
            if process.poll() is None:
                try:
                    if process.stdin is not None:
                        process.stdin.write(json.dumps({"request_id": uuid.uuid4().hex, "action": "shutdown"}) + "\n")
                        process.stdin.flush()
                    process.wait(timeout=2)
                except Exception:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except Exception:
                        process.kill()
                        process.wait(timeout=3)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            _append_worker_log(f"WORKER STOP pid={process.pid} exit={process.returncode}")
        reader = self.reader
        self.reader = None
        if reader is not None and reader.is_alive() and reader is not threading.current_thread():
            reader.join(timeout=2)
        self.state = "idle"
        self.message = "可选模型未加载"
        self.device = ""
        self.dtype = ""
        self.attention = ""


WORKERS = WorkerManager()
