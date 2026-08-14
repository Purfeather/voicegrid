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
from .module_integrity import runtime_python
from .paths import (
    ROOT,
    SOUND_EFFECT_MODEL_DIR,
    SOUND_EFFECT_RUNTIME_DIR,
    VOICE_GENERATOR_CODEC_DIR,
    VOICE_GENERATOR_MODEL_DIR,
    VOICE_GENERATOR_RUNTIME_DIR,
)


PROTOCOL_PREFIX = "VOICEGRID_EVENT "


def _append_worker_log(message: str) -> None:
    append_diagnostic_log("optional-model-worker", message)


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
        self.sampling_dtype = ""
        self.attention = ""
        self.compute_capability = ""
        self.precision = ""
        self.projection_dtype = ""
        self.precision_extra_mib = 0.0
        self.low_vram = False
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
        python = runtime_python(VOICE_GENERATOR_RUNTIME_DIR)
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

    def _start_sound_effect(self) -> None:
        python = runtime_python(SOUND_EFFECT_RUNTIME_DIR)
        if not python.is_file():
            raise FileNotFoundError("音效生成 Python 3.12 独立运行环境尚未安装。")
        if not SOUND_EFFECT_MODEL_DIR.is_dir():
            raise FileNotFoundError("MOSS-SoundEffect v2.0 模型尚未完整安装。")
        self.release()
        while True:
            try:
                self.messages.get_nowait()
            except queue.Empty:
                break
        self.diagnostic_tail = []
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        env = os.environ.copy()
        env.update({
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TORCHDYNAMO_DISABLE": "1",
            "TORCH_COMPILE_DISABLE": "1",
            "TORCHINDUCTOR_DISABLE": "1",
            "DISABLE_TORCH_COMPILE": "1",
            "TRITON_DISABLE": "1",
        })
        command = [
            str(python),
            str(ROOT / "desktop" / "workers" / "sound_effect_worker.py"),
            "--model",
            str(SOUND_EFFECT_MODEL_DIR),
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
        self.active_module = "sound_effect"
        self.state = "loading"
        self.message = "正在启动 MOSS-SoundEffect v2.0"
        self.reader = threading.Thread(target=self._reader_loop, args=(process,), name="sound-effect-worker-reader", daemon=True)
        self.reader.start()
        deadline = time.monotonic() + 15
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    detail = "\n".join(self.diagnostic_tail[-4:])
                    raise RuntimeError(f"音效生成工作进程启动失败。{(' ' + detail) if detail else ''}")
                try:
                    message = self.messages.get(timeout=.2)
                except queue.Empty:
                    continue
                if message.get("event") == "ready":
                    return
            raise TimeoutError("音效生成工作进程启动超时。")
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
                    self.sampling_dtype = str(message.get("sampling_dtype") or self.sampling_dtype)
                    self.attention = str(message.get("attention") or self.attention)
                    self.compute_capability = str(message.get("compute_capability") or self.compute_capability)
                    self.precision = str(message.get("precision") or self.precision)
                    self.projection_dtype = str(message.get("projection_dtype") or self.projection_dtype)
                    self.precision_extra_mib = float(message.get("precision_extra_mib") or self.precision_extra_mib)
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

    def request_sound_effect(
        self,
        payload: dict[str, Any],
        progress: Callable[[float, str], None],
        cancelled: Callable[[], bool],
    ) -> dict[str, Any]:
        required = {
            "prompt", "seconds", "num_inference_steps", "cfg_scale",
            "sigma_shift", "seed", "output_path",
        }
        missing = sorted(required.difference(payload))
        if missing:
            raise ValueError(f"音效任务缺少参数：{', '.join(missing)}")
        with self.request_lock:
            with self.lock:
                if self.process is None or self.process.poll() is not None or self.active_module != "sound_effect":
                    self._start_sound_effect()
                process = self.process
            assert process is not None and process.stdin is not None
            request_id = uuid.uuid4().hex
            process.stdin.write(json.dumps({"request_id": request_id, "action": "generate", **payload}, ensure_ascii=False) + "\n")
            process.stdin.flush()
            self.state = "running"
            self.message = "正在生成音效"
            while True:
                if cancelled():
                    self.release()
                    raise TaskCancelled("音效生成任务已停止。")
                if process.poll() is not None:
                    self.state = "error"
                    self.message = "音效生成工作进程异常退出"
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
                    self.compute_capability = str(message.get("compute_capability") or self.compute_capability)
                    self.precision = str(message.get("precision") or self.precision)
                    self.low_vram = bool(message.get("low_vram", self.low_vram))
                    self.message = str(message.get("message") or self.message)
                    progress(float(message.get("progress", .5)), self.message)
                    continue
                if message.get("request_id") != request_id:
                    continue
                if event == "result":
                    result = dict(message["result"])
                    expected = {
                        "duration", "sample_rate", "channels", "bit_depth", "runtime_precision",
                        "low_vram", "cuda_peak_allocated_mib", "cuda_peak_reserved_mib",
                    }
                    absent = sorted(expected.difference(result))
                    if absent:
                        raise RuntimeError(f"音效工作进程返回不完整：{', '.join(absent)}")
                    self.state = "loaded"
                    self.message = "MOSS-SoundEffect v2.0 已就绪（显存已释放）"
                    return result
                if event == "error":
                    self.state = "error"
                    self.message = str(message.get("message") or "音效生成失败")
                    raise RuntimeError(self.message)

    def describe(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "active_model": (
                "MOSS-VoiceGenerator · 1.7B" if self.active_module == "voice_design"
                else "MOSS-SoundEffect v2.0" if self.active_module == "sound_effect"
                else None
            ),
            "active_module": self.active_module,
            "message": self.message,
            "device": self.device,
            "dtype": self.dtype,
            "sampling_dtype": self.sampling_dtype,
            "attention": self.attention,
            "compute_capability": self.compute_capability,
            "precision": self.precision,
            "projection_dtype": self.projection_dtype,
            "precision_extra_mib": self.precision_extra_mib,
            "low_vram": self.low_vram,
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
        self.sampling_dtype = ""
        self.attention = ""
        self.compute_capability = ""
        self.precision = ""
        self.projection_dtype = ""
        self.precision_extra_mib = 0.0
        self.low_vram = False


WORKERS = WorkerManager()
