from __future__ import annotations

import json
import os
import hashlib
import shutil
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from .events import EVENTS
from .paths import (
    MODULE_STATE_DIR,
    ROOT,
    SOUND_EFFECT_MODEL_DIR,
    SOUND_EFFECT_RUNTIME_DIR,
    MOSS_CODEC_DIR,
    MOSS_MODEL_DIR,
    VOICE_GENERATOR_CODEC_DIR,
    VOICE_GENERATOR_MODEL_DIR,
    VOICE_GENERATOR_RUNTIME_DIR,
)
from .diagnostics import append_diagnostic_log


MODEL_LOCKS: dict[str, dict[str, Any]] = {
    "openmoss/MOSS-TTS-Local-Transformer-v1.5": {
        "revision": "master",
        "file_count": 19,
        "total_bytes": 9_116_899_103,
        "manifest_sha256": "2ec85506d2450ce65beb83164ecedc3cf81fb38bbdedf3c0a5e35c0b49cf5063",
    },
    "openmoss/MOSS-Audio-Tokenizer-v2": {
        "revision": "master",
        "file_count": 15,
        "total_bytes": 8_498_219_117,
        "manifest_sha256": "84fd35a7f8bc745b6c4832d7d7f2d221756ff261c6f6a860d8f40a086a7f48ba",
    },
    "openmoss/MOSS-VoiceGenerator": {
        "revision": "master",
        "file_count": 17,
        "total_bytes": 4_244_249_582,
        "manifest_sha256": "298fbb371515291742daa6e537e5833cd3c7b5eb3a3e09b16aaaeaac0577f318",
    },
    "openmoss/MOSS-Audio-Tokenizer": {
        "revision": "master",
        "file_count": 14,
        "total_bytes": 7_101_116_247,
        "manifest_sha256": "c20df5cbcba8b90d599a5389936ce98d7fcdb9d86556e724b191733f9f6211ac",
    },
    "openmoss/MOSS-SoundEffect-v2.0": {
        "revision": "master",
        "file_count": 18,
        "total_bytes": 11_230_171_166,
        "manifest_sha256": "b50a3034b1abae0bfcc7435e079e5c03705b1a61ee17f22aaae1941126c7daf7",
    },
}


MODULES: dict[str, dict[str, Any]] = {
    "speech": {
        "name": "语音合成",
        "model_name": "MOSS-TTS Local Transformer v1.5 · 4B",
        "model_id": "openmoss/MOSS-TTS-Local-Transformer-v1.5",
        "description": "参考音色克隆、情感表演、长文本切分与工程化交付。",
        "disk_gb": 16.4,
        "runtime_python": "主程序环境",
        "runtime_mode": "host",
        "engine_available": True,
    },
    "voice_design": {
        "name": "音色设计",
        "model_name": "MOSS-VoiceGenerator · 1.7B",
        "model_id": "openmoss/MOSS-VoiceGenerator",
        "codec_id": "openmoss/MOSS-Audio-Tokenizer",
        "description": "无需参考音频，通过自然语言创建可供配音使用的新音色。",
        "disk_gb": 14.0,
        "runtime_python": "Python 3.12（独立环境）",
        "runtime_mode": "isolated",
        "engine_available": True,
    },
    "sound_effect": {
        "name": "音效生成",
        "model_name": "MOSS-SoundEffect v2.0",
        "model_id": "openmoss/MOSS-SoundEffect-v2.0",
        "description": "根据中英文描述生成最长 30 秒的 48 kHz 音效。",
        "disk_gb": 18.0,
        "runtime_python": "Python 3.12（必需）",
        "runtime_mode": "isolated",
        "engine_available": False,
        "engine_message": "界面与安装平台已就绪；真实推理将在音色设计验收后接入。",
    },
}

RUNTIME_IMPORT_CHECKS = {
    "voice_design": "import torch, torchaudio, transformers, modelscope, modelscope_hub, soundfile, librosa, tiktoken, accelerate, safetensors, orjson, tqdm, yaml, einops, scipy, psutil, packaging",
    "sound_effect": "import torch, torchaudio, torchvision, transformers, modelscope_hub, soundfile, diffusers, audiotools",
}
RUNTIME_VERSION_LOCKS = {
    "voice_design": {
        "torch": "2.9.1+cu128",
        "torchaudio": "2.9.1+cu128",
        "transformers": "5.0.0",
        "modelscope": "1.39.1",
        "modelscope-hub": "0.2.0",
        "accelerate": "1.14.0",
        "safetensors": "0.6.2",
        "numpy": "2.1.0",
        "orjson": "3.11.4",
        "tqdm": "4.67.1",
        "PyYAML": "6.0.3",
        "einops": "0.8.1",
        "scipy": "1.16.2",
        "librosa": "0.11.0",
        "tiktoken": "0.12.0",
        "soundfile": "0.14.0",
        "psutil": "7.2.2",
        "packaging": "26.3",
    },
    "sound_effect": {
        "torch": "2.9.0+cu128",
        "torchaudio": "2.9.0+cu128",
        "torchvision": "0.24.0+cu128",
        "transformers": "4.57.1",
        "safetensors": "0.7.0",
        "numpy": "1.26.4",
        "diffusers": "0.37.1",
    },
}
RUNTIME_PYTHON_LOCKS = {
    "voice_design": (3, 12),
    "sound_effect": (3, 12),
}


def _append_module_log(module_id: str, message: str) -> None:
    append_diagnostic_log(f"module-install-{module_id}", message)


def _runtime_python(runtime: Path) -> Path:
    return runtime / "Scripts" / "python.exe"


def _safe_manifest_file(root: Path, relative: str) -> Path | None:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        return None
    return candidate


def _lock_for_model_path(path: Path) -> dict[str, Any] | None:
    repo_id = {
        "MOSS-TTS-Local-Transformer-v1.5": "openmoss/MOSS-TTS-Local-Transformer-v1.5",
        "MOSS-Audio-Tokenizer-v2": "openmoss/MOSS-Audio-Tokenizer-v2",
        "MOSS-VoiceGenerator": "openmoss/MOSS-VoiceGenerator",
        "MOSS-Audio-Tokenizer": "openmoss/MOSS-Audio-Tokenizer",
        "MOSS-SoundEffect-v2.0": "openmoss/MOSS-SoundEffect-v2.0",
    }.get(path.name)
    return MODEL_LOCKS.get(repo_id or "")


def _model_complete(path: Path, module_id: str) -> bool:
    if not path.is_dir():
        return False
    marker = path / ".voicegrid-install.json"
    if marker.is_file():
        try:
            state = json.loads(marker.read_text(encoding="utf-8"))
            lock = MODEL_LOCKS.get(str(state.get("repo_id")))
            if lock and state.get("manifest_sha256") == lock["manifest_sha256"]:
                files = list(state.get("files") or [])
                if len(files) != int(lock["file_count"]) or sum(int(item.get("size", 0)) for item in files) != int(lock["total_bytes"]):
                    return False
                for item in files:
                    candidate = _safe_manifest_file(path, str(item.get("path") or ""))
                    if candidate is None or not candidate.is_file() or candidate.stat().st_size != int(item.get("size", -1)):
                        return False
                return True
        except Exception:
            return False
    required = "model_index.json" if module_id == "sound_effect" else "config.json"
    config = path / required
    weights = list(path.rglob("*.safetensors"))
    lock = _lock_for_model_path(path)
    content_files = [
        item for item in path.rglob("*")
        if item.is_file() and item.name != ".voicegrid-install.json" and ".cache" not in item.parts
    ]
    return bool(
        lock
        and config.is_file()
        and config.stat().st_size > 0
        and weights
        and all(item.stat().st_size > 0 for item in weights)
        and len(content_files) == int(lock["file_count"])
        and sum(item.stat().st_size for item in content_files) == int(lock["total_bytes"])
    )


def _requirements_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ModuleService:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.install_threads: dict[str, threading.Thread] = {}
        self.install_processes: dict[str, subprocess.Popen[str]] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self._load_states()

    def _load_states(self) -> None:
        MODULE_STATE_DIR.mkdir(parents=True, exist_ok=True)
        for module_id in MODULES:
            path = MODULE_STATE_DIR / f"{module_id}.json"
            try:
                self.states[module_id] = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self.states[module_id] = {}

    def _save_state(self, module_id: str, **changes: Any) -> None:
        with self.lock:
            state = self.states.setdefault(module_id, {})
            state.update(changes, updated_at=datetime.now().isoformat(timespec="seconds"))
            target = MODULE_STATE_DIR / f"{module_id}.json"
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
            os.replace(temporary, target)
        EVENTS.publish("module.updated", self.describe(module_id))

    def _detected(self, module_id: str) -> tuple[bool, bool, list[str]]:
        if module_id == "speech":
            model_ready = _model_complete(MOSS_MODEL_DIR, module_id) and _model_complete(MOSS_CODEC_DIR, module_id)
            missing = []
            if not _model_complete(MOSS_MODEL_DIR, module_id):
                missing.append(str(MOSS_MODEL_DIR.relative_to(ROOT)))
            if not _model_complete(MOSS_CODEC_DIR, module_id):
                missing.append(str(MOSS_CODEC_DIR.relative_to(ROOT)))
            return model_ready, True, missing
        if module_id == "voice_design":
            generator_ready = _model_complete(VOICE_GENERATOR_MODEL_DIR, module_id)
            codec_ready = _model_complete(VOICE_GENERATOR_CODEC_DIR, module_id)
            model_ready = generator_ready and codec_ready
            runtime_ready = self._runtime_complete(VOICE_GENERATOR_RUNTIME_DIR, module_id)
            missing = []
            if not generator_ready:
                missing.append(str(VOICE_GENERATOR_MODEL_DIR.relative_to(ROOT)))
            if not codec_ready:
                missing.append(str(VOICE_GENERATOR_CODEC_DIR.relative_to(ROOT)))
            if not runtime_ready:
                missing.append(str(VOICE_GENERATOR_RUNTIME_DIR.relative_to(ROOT)))
            return model_ready, runtime_ready, missing
        model_ready = _model_complete(SOUND_EFFECT_MODEL_DIR, module_id)
        runtime_ready = self._runtime_complete(SOUND_EFFECT_RUNTIME_DIR, module_id)
        missing = []
        if not model_ready:
            missing.append(str(SOUND_EFFECT_MODEL_DIR.relative_to(ROOT)))
        if not runtime_ready:
            missing.append(str(SOUND_EFFECT_RUNTIME_DIR.relative_to(ROOT)))
        return model_ready, runtime_ready, missing

    def _runtime_complete(self, runtime: Path, module_id: str) -> bool:
        python = _runtime_python(runtime)
        marker = runtime / ".voicegrid-runtime.json"
        requirements = ROOT / "desktop" / "workers" / f"requirements-{module_id}.txt"
        if not python.is_file() or not requirements.is_file():
            return False
        try:
            if marker.is_file():
                state = json.loads(marker.read_text(encoding="utf-8"))
                if state.get("requirements_sha256") != _requirements_sha256(requirements):
                    return False
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            package_names = list(RUNTIME_VERSION_LOCKS[module_id])
            version_script = (
                "import importlib.metadata,json,sys;"
                f"names={package_names!r};"
                "print(json.dumps({'python':[sys.version_info.major,sys.version_info.minor],"
                "'packages':{name:importlib.metadata.version(name) for name in names}}))"
            )
            result = subprocess.run(
                [str(python), "-c", RUNTIME_IMPORT_CHECKS[module_id] + ";" + version_script],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                creationflags=creationflags,
            )
            if result.returncode != 0:
                _append_module_log(
                    module_id,
                    "RUNTIME CHECK FAILED\n" + (result.stdout or "") + (result.stderr or ""),
                )
                return False
            probe = json.loads(result.stdout.strip().splitlines()[-1])
            versions = dict(probe.get("packages") or {})
            python_lock = RUNTIME_PYTHON_LOCKS.get(module_id)
            if python_lock and tuple(probe.get("python") or ()) != python_lock:
                _append_module_log(module_id, f"PYTHON VERSION MISMATCH: expected={python_lock} actual={probe.get('python')}")
                return False
            mismatches = {
                name: {"expected": version, "actual": versions.get(name)}
                for name, version in RUNTIME_VERSION_LOCKS[module_id].items()
                if versions.get(name) != version
            }
            if mismatches:
                _append_module_log(module_id, f"PACKAGE VERSION MISMATCH: {json.dumps(mismatches, ensure_ascii=False)}")
                return False
            if module_id == "voice_design":
                audio_probe = subprocess.run(
                    [str(python), str(ROOT / "desktop" / "workers" / "runtime_audio_probe.py")],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                    creationflags=creationflags,
                )
                if audio_probe.returncode != 0:
                    _append_module_log(
                        module_id,
                        "AUDIO PROBE FAILED\n" + (audio_probe.stdout or "") + (audio_probe.stderr or ""),
                    )
                    return False
                audio_result = json.loads(audio_probe.stdout.strip().splitlines()[-1])
                if audio_result.get("format") != "WAV" or audio_result.get("subtype") != "PCM_24":
                    _append_module_log(module_id, f"AUDIO PROBE MISMATCH: {json.dumps(audio_result, ensure_ascii=False)}")
                    return False
            if not marker.is_file():
                marker.write_text(
                    json.dumps(
                        {
                            "module": module_id,
                            "requirements_sha256": _requirements_sha256(requirements),
                            "adopted_at": datetime.now().isoformat(timespec="seconds"),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                    newline="\n",
                )
            return True
        except Exception:
            _append_module_log(module_id, "RUNTIME CHECK EXCEPTION\n" + traceback.format_exc())
            return False

    def describe(self, module_id: str, inspect: bool = False) -> dict[str, Any]:
        if module_id not in MODULES:
            raise ValueError("未知模块。")
        state = dict(self.states.get(module_id) or {})
        if inspect:
            model_ready, runtime_ready, missing = self._detected(module_id)
        else:
            model_ready = bool(state.get("model_ready", False))
            runtime_ready = bool(state.get("runtime_ready", False))
            missing = list(state["missing"]) if "missing" in state else self._manual_paths(module_id)
        installing = bool(self.install_threads.get(module_id) and self.install_threads[module_id].is_alive())
        installed = model_ready and runtime_ready
        status = "installing" if installing else "ready" if installed else "repair_required" if model_ready or runtime_ready else "not_installed"
        interrupted = state.get("status") == "installing" and not installing and not installed
        if interrupted:
            status = "repair_required"
        if state.get("status") == "failed" and not installing and not installed:
            status = "failed"
        descriptor = MODULES[module_id]
        download_bytes = sum(int(MODEL_LOCKS[model_id]["total_bytes"]) for model_id in self._model_ids(module_id))
        peak_disk_gb = max(float(descriptor["disk_gb"]) * 2.15 + 6.0, float(descriptor["disk_gb"]) + 12.0)
        return {
            "id": module_id,
            **descriptor,
            "installed": installed,
            "model_ready": model_ready,
            "runtime_ready": runtime_ready,
            "install_state": status,
            "install_phase": state.get("phase", "idle"),
            "install_progress": float(state.get("progress", 0.0)),
            "install_message": "上次安装已中断，可以继续安装 / 修复" if interrupted else state.get("message", "已安装" if installed else "尚未安装"),
            "error": state.get("error", ""),
            "missing": missing,
            "manual_paths": self._manual_paths(module_id),
            "preview_available": True,
            "model_locks": [MODEL_LOCKS[model_id] | {"model_id": model_id} for model_id in self._model_ids(module_id)],
            "download_gb": round(download_bytes / 1024**3, 1),
            "required_disk_gb": round(peak_disk_gb, 1),
        }

    def list(self) -> list[dict[str, Any]]:
        return [self.describe(module_id) for module_id in MODULES]

    def detect(self, module_id: str) -> dict[str, Any]:
        if module_id not in MODULES:
            raise ValueError("未知模块。")
        model_ready, runtime_ready, missing = self._detected(module_id)
        installed = model_ready and runtime_ready
        self._save_state(
            module_id,
            installed=installed,
            model_ready=model_ready,
            runtime_ready=runtime_ready,
            missing=missing,
            status="ready" if installed else "repair_required" if model_ready or runtime_ready else "not_installed",
            phase="validated" if installed else "idle",
            progress=1.0 if installed else 0.0,
            message="模型与运行环境已就绪" if installed else "未检测到完整安装",
            error="",
        )
        return self.describe(module_id)

    def _manual_paths(self, module_id: str) -> list[str]:
        if module_id == "speech":
            return [str(MOSS_MODEL_DIR.relative_to(ROOT)), str(MOSS_CODEC_DIR.relative_to(ROOT))]
        if module_id == "voice_design":
            return [
                str(VOICE_GENERATOR_MODEL_DIR.relative_to(ROOT)),
                str(VOICE_GENERATOR_CODEC_DIR.relative_to(ROOT)),
                str(VOICE_GENERATOR_RUNTIME_DIR.relative_to(ROOT)),
            ]
        if module_id == "sound_effect":
            return [str(SOUND_EFFECT_MODEL_DIR.relative_to(ROOT)), str(SOUND_EFFECT_RUNTIME_DIR.relative_to(ROOT))]
        return []

    def _model_ids(self, module_id: str) -> list[str]:
        if module_id == "speech":
            return ["openmoss/MOSS-TTS-Local-Transformer-v1.5", "openmoss/MOSS-Audio-Tokenizer-v2"]
        if module_id == "voice_design":
            return ["openmoss/MOSS-VoiceGenerator", "openmoss/MOSS-Audio-Tokenizer"]
        if module_id == "sound_effect":
            return ["openmoss/MOSS-SoundEffect-v2.0"]
        return []

    def install(self, module_id: str, confirmed: bool) -> dict[str, Any]:
        if module_id not in MODULES:
            raise ValueError("未知模块。")
        if not confirmed:
            raise ValueError("必须确认磁盘空间和下载目录后才能安装。")
        self._assert_install_safe(module_id)
        free_gb = shutil.disk_usage(ROOT).free / 1024**3
        required_gb = float(MODULES[module_id]["disk_gb"])
        # Downloads are staged and existing installs are retained until verification succeeds.
        # Include the runtime, package cache and rollback copy in the peak-space budget.
        required_gb = max(required_gb * 2.15 + 6.0, required_gb + 12.0)
        if free_gb < required_gb:
            raise OSError(f"磁盘可用空间仅 {free_gb:.1f} GB，安装至少需要 {required_gb:.0f} GB。")
        with self.lock:
            existing = self.install_threads.get(module_id)
            if existing and existing.is_alive():
                return self.describe(module_id)
            thread = threading.Thread(target=self._install, args=(module_id,), name=f"module-install-{module_id}", daemon=True)
            self.install_threads[module_id] = thread
            thread.start()
        return self.describe(module_id)

    def _assert_install_safe(self, module_id: str) -> None:
        if module_id != "speech":
            return
        from app.model_engine import ENGINE
        from .database import DB

        runtime = ENGINE.describe()
        active = bool(runtime.get("active_model")) or runtime.get("state") in {"loading", "loaded", "running", "releasing"}
        task = DB.one("SELECT id FROM tasks WHERE module='speech' AND status IN ('queued','running') LIMIT 1")
        if active or task is not None:
            raise RuntimeError("语音模型正在使用中。请先安全停止任务并释放模型，再执行安装或修复。")

    def _run_step(
        self,
        module_id: str,
        command: list[str],
        phase: str,
        message: str,
        progress: float,
        progress_span: float = 0.0,
    ) -> None:
        self._save_state(module_id, status="installing", phase=phase, message=message, progress=progress, error="")
        _append_module_log(module_id, f"START {phase}: {subprocess.list2cmdline(command)}")
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        with self.lock:
            self.install_processes[module_id] = process
        tail: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            clean = line.strip()
            if clean:
                _append_module_log(module_id, f"{phase}: {clean}")
                if clean.startswith("VOICEGRID_INSTALL_PROGRESS "):
                    try:
                        update = json.loads(clean.removeprefix("VOICEGRID_INSTALL_PROGRESS "))
                        completed = int(update.get("downloaded", 0))
                        total = max(1, int(update.get("total", 1)))
                        current_file = str(update.get("file") or "模型文件")
                        actual_progress = min(1.0, max(0.0, completed / total))
                        self._save_state(
                            module_id,
                            status="installing",
                            phase=phase,
                            message=f"正在下载 {current_file} · {completed / 1024**3:.1f}/{total / 1024**3:.1f} GB",
                            progress=progress + actual_progress * progress_span,
                            error="",
                        )
                        continue
                    except Exception:
                        pass
                tail.append(clean)
                tail = tail[-8:]
                self._save_state(module_id, status="installing", phase=phase, message=clean[:240], progress=progress, error="")
        code = process.wait()
        with self.lock:
            self.install_processes.pop(module_id, None)
        _append_module_log(module_id, f"END {phase}: exit={code}")
        if code:
            raise RuntimeError("\n".join(tail) or f"安装步骤退出，代码 {code}")

    def _install(self, module_id: str) -> None:
        _append_module_log(module_id, "INSTALL BEGIN")
        try:
            self._assert_install_safe(module_id)
            runtime = None if module_id == "speech" else VOICE_GENERATOR_RUNTIME_DIR if module_id == "voice_design" else SOUND_EFFECT_RUNTIME_DIR
            requirements = ROOT / "desktop" / "workers" / f"requirements-{module_id}.txt"
            if runtime is not None:
                runtime.parent.mkdir(parents=True, exist_ok=True)
            if runtime is not None and not self._runtime_complete(runtime, module_id):
                staging_runtime = runtime.parent / f".{runtime.name}.partial"
                previous_runtime = runtime.parent / f".{runtime.name}.previous"
                if staging_runtime.exists():
                    shutil.rmtree(staging_runtime)
                self._run_step(module_id, [sys.executable, "-m", "venv", str(staging_runtime)], "runtime", "正在创建独立运行环境", 0.06)
                staging_python = str(_runtime_python(staging_runtime))
                self._run_step(
                    module_id,
                    [staging_python, "-m", "pip", "install", "--extra-index-url", "https://download.pytorch.org/whl/cu128", "-r", str(requirements)],
                    "dependencies",
                    "正在安装锁定依赖",
                    0.18,
                )
                (staging_runtime / ".voicegrid-runtime.json").write_text(
                    json.dumps(
                        {
                            "module": module_id,
                            "requirements_sha256": _requirements_sha256(requirements),
                            "completed_at": datetime.now().isoformat(timespec="seconds"),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                    newline="\n",
                )
                if not self._runtime_complete(staging_runtime, module_id):
                    raise RuntimeError("独立运行环境校验未通过。")
                if previous_runtime.exists():
                    shutil.rmtree(previous_runtime)
                if runtime.exists():
                    os.replace(runtime, previous_runtime)
                try:
                    os.replace(staging_runtime, runtime)
                except Exception:
                    if previous_runtime.exists() and not runtime.exists():
                        os.replace(previous_runtime, runtime)
                    raise
                if previous_runtime.exists():
                    shutil.rmtree(previous_runtime)
            python = sys.executable if runtime is None else str(_runtime_python(runtime))
            if module_id == "speech":
                jobs = [("openmoss/MOSS-TTS-Local-Transformer-v1.5", MOSS_MODEL_DIR), ("openmoss/MOSS-Audio-Tokenizer-v2", MOSS_CODEC_DIR)]
            elif module_id == "voice_design":
                jobs = [("openmoss/MOSS-VoiceGenerator", VOICE_GENERATOR_MODEL_DIR), ("openmoss/MOSS-Audio-Tokenizer", VOICE_GENERATOR_CODEC_DIR)]
            else:
                jobs = [("openmoss/MOSS-SoundEffect-v2.0", SOUND_EFFECT_MODEL_DIR)]
            for index, (model_id, destination) in enumerate(jobs):
                lock = MODEL_LOCKS[model_id]
                if _model_complete(destination, module_id):
                    continue
                self._run_step(
                    module_id,
                    [
                        python,
                        str(ROOT / "desktop" / "workers" / "module_downloader.py"),
                        "--repo-id",
                        model_id,
                        "--revision",
                        str(lock["revision"]),
                        "--manifest-sha256",
                        str(lock["manifest_sha256"]),
                        "--destination",
                        str(destination),
                    ],
                    "models",
                    f"正在从 ModelScope 下载 {model_id}",
                    0.42 + index * 0.26,
                    0.22,
                )
            descriptor = self.detect(module_id)
            if not descriptor["installed"]:
                raise RuntimeError("下载完成，但模型或运行环境完整性检查未通过。")
            _append_module_log(module_id, "INSTALL COMPLETE")
        except Exception as exc:
            _append_module_log(module_id, "INSTALL FAILED\n" + traceback.format_exc())
            self._save_state(module_id, status="failed", phase="failed", message="安装未完成，可稍后继续或修复", progress=0.0, error=str(exc))

    def shutdown(self) -> None:
        with self.lock:
            processes = list(self.install_processes.values())
            threads = list(self.install_threads.values())
        for process in processes:
            if os.name == "nt":
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=8,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                except Exception:
                    pass
            elif process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for thread in threads:
            thread.join(timeout=5)


MODULE_SERVICE = ModuleService()
