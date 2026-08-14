from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from .diagnostics import append_diagnostic_log
from .events import EVENTS
from .module_catalog import (
    MODEL_LOCKS,
    MODULES,
    RUNTIME_IMPORT_CHECKS,
    RUNTIME_PYTHON_LOCKS,
    RUNTIME_VERSION_LOCKS,
    SOUND_EFFECT_SOURCE_REVISION,
    SOUND_EFFECT_SOURCE_TREE_SHA256,
    manual_paths,
    model_ids,
    model_jobs,
    runtime_dir,
)
from .module_integrity import (
    detect_module,
    model_complete,
    python312_venv_command,
    requirements_sha256,
    runtime_complete,
    runtime_python,
    sound_effect_source_dir,
)
from .paths import (
    MODULE_STATE_DIR,
    ROOT,
    SOUND_EFFECT_SOURCE_DIR,
)


def _append_module_log(module_id: str, message: str) -> None:
    append_diagnostic_log(f"module-install-{module_id}", message)


_model_complete = model_complete


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
        return detect_module(module_id, _append_module_log)

    def _runtime_complete(self, runtime: Path, module_id: str) -> bool:
        return runtime_complete(runtime, module_id, _append_module_log)

    def _has_partial_install(
        self,
        module_id: str,
        model_ready: bool,
        runtime_ready: bool,
        missing: list[str],
    ) -> bool:
        model_count = len(self._model_ids(module_id))
        missing_models = sum(path.startswith("optional-models") for path in missing)
        any_model_present = model_ready or missing_models < model_count
        isolated_runtime_present = runtime_dir(module_id) is not None and runtime_ready
        return any_model_present or isolated_runtime_present

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
        partial = self._has_partial_install(module_id, model_ready, runtime_ready, missing)
        status = "installing" if installing else "ready" if installed else "repair_required" if partial else "not_installed"
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
        partial = self._has_partial_install(module_id, model_ready, runtime_ready, missing)
        self._save_state(
            module_id,
            installed=installed,
            model_ready=model_ready,
            runtime_ready=runtime_ready,
            missing=missing,
            status="ready" if installed else "repair_required" if partial else "not_installed",
            phase="validated" if installed else "idle",
            progress=1.0 if installed else 0.0,
            message="模型与运行环境已就绪" if installed else "未检测到完整安装",
            error="",
        )
        return self.describe(module_id)

    def _manual_paths(self, module_id: str) -> list[str]:
        return manual_paths(module_id)

    def _model_ids(self, module_id: str) -> list[str]:
        return model_ids(module_id)

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
            runtime = runtime_dir(module_id)
            requirements = ROOT / "desktop" / "workers" / f"requirements-{module_id}.txt"
            if runtime is not None:
                runtime.parent.mkdir(parents=True, exist_ok=True)
            if runtime is not None and not self._runtime_complete(runtime, module_id):
                staging_runtime = runtime.parent / f".{runtime.name}.partial"
                previous_runtime = runtime.parent / f".{runtime.name}.previous"
                if staging_runtime.exists():
                    shutil.rmtree(staging_runtime)
                self._run_step(
                    module_id,
                    python312_venv_command(staging_runtime),
                    "runtime",
                    "正在创建 Python 3.12 独立运行环境",
                    0.06,
                )
                staging_python = str(runtime_python(staging_runtime))
                self._run_step(
                    module_id,
                    [staging_python, "-m", "pip", "install", "--extra-index-url", "https://download.pytorch.org/whl/cu128", "-r", str(requirements)],
                    "dependencies",
                    "正在安装锁定依赖",
                    0.18,
                )
                if module_id == "sound_effect":
                    source = sound_effect_source_dir()
                    if source is None:
                        self._run_step(
                            module_id,
                            [
                                sys.executable,
                                str(ROOT / "desktop" / "workers" / "source_downloader.py"),
                                "--repository", "OpenMOSS/MOSS-TTS",
                                "--revision", SOUND_EFFECT_SOURCE_REVISION,
                                "--subdirectory", "moss_soundeffect_v2",
                                "--destination", str(SOUND_EFFECT_SOURCE_DIR / "moss_soundeffect_v2"),
                                "--tree-sha256", SOUND_EFFECT_SOURCE_TREE_SHA256,
                            ],
                            "runtime-source-download",
                            "正在下载锁定版本的官方推理源码",
                            0.34,
                            0.02,
                        )
                        source = sound_effect_source_dir()
                    if source is None:
                        raise RuntimeError("官方 MOSS-SoundEffect v2 推理源码下载或校验失败。")
                    self._run_step(
                        module_id,
                        [staging_python, "-m", "pip", "install", "--no-deps", str(source)],
                        "runtime-source",
                        "正在安装本地官方 MOSS-SoundEffect v2.0 推理源码",
                        0.36,
                    )
                (staging_runtime / ".voicegrid-runtime.json").write_text(
                    json.dumps(
                        {
                            "module": module_id,
                            "requirements_sha256": requirements_sha256(requirements),
                            "source_revision": SOUND_EFFECT_SOURCE_REVISION if module_id == "sound_effect" else None,
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
            python = sys.executable if runtime is None else str(runtime_python(runtime))
            for index, (model_id, destination) in enumerate(model_jobs(module_id)):
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
