from __future__ import annotations

import json
import os
import re
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from app.model_engine import ENGINE, PAUSE_MARKER_PATTERN, TaskCancelled, split_text

from .audio import prepare_trimmed_reference
from .events import EVENTS
from .module_service import MODULE_SERVICE
from .repository import (
    add_output,
    cancel_requested,
    delete_task,
    get_project,
    get_task,
    get_voice,
    insert_task,
    list_outputs,
    now,
    project_output_directory,
    task_payload,
    update_task,
    voice_path,
)
from .runtime_service import RUNTIME
from .worker_manager import WORKERS


SPEED_TOKENS_PER_CHAR = {
    "慢": 3.8,
    "较慢": 3.4,
    "中等": 3.0,
    "较快": 2.65,
    "快": 2.3,
}


def estimate_speed_tokens(text: str, level: str) -> int:
    """Estimate duration-control frames from effective character count and a named speed tier."""
    source = text or ""
    pause_seconds = sum(float(match.group(1)) for match in PAUSE_MARKER_PATTERN.finditer(source))
    spoken_text = PAUSE_MARKER_PATTERN.sub("", source)
    effective_chars = len(re.sub(r"\s+", "", spoken_text))
    factor = SPEED_TOKENS_PER_CHAR.get(level, SPEED_TOKENS_PER_CHAR["中等"])
    spoken_tokens = max(13, int(effective_chars * factor + .5))
    pause_tokens = int(pause_seconds * 12.5 + .5)
    return spoken_tokens + pause_tokens


def normalize_speech_workspace(workspace: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(workspace)
    asset_id = normalized.get("voice_id") or normalized.get("reference_id")
    if not asset_id:
        return normalized
    try:
        voice_path(str(asset_id))
    except (OSError, ValueError):
        normalized["voice_id"] = None
        normalized["reference_id"] = None
        normalized["reference_trim_start"] = 0
        normalized["reference_trim_end"] = None
    return normalized

def build_generation_snapshot(workspace: dict[str, Any]) -> dict[str, Any]:
    style = str(workspace.get("style") or "")
    instruction = str(workspace.get("instruction") or "").strip()
    asset_id = workspace.get("voice_id") or workspace.get("reference_id")
    reference_audio = None
    if asset_id:
        voice = get_voice(str(asset_id))
        reference_audio = {"id": voice["id"], "name": voice["name"], "saved": bool(voice["saved"])}
    return {
        "style": style,
        "instruction": instruction,
        "reference_audio": reference_audio,
        "speed": str(workspace.get("manual_speed_level") or "中等") if workspace.get("manual_speed_enabled") else "自动",
    }


def build_voice_design_snapshot(workspace: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": workspace.get("mode", "composer"),
        "composer": dict(workspace.get("composer") or {}),
        "prompt_preview": str(workspace.get("prompt_preview") or ""),
        "instruction": str(workspace.get("instruction") or "").strip(),
        "text": str(workspace.get("text") or "").strip(),
        "parameters": dict(workspace.get("parameters") or {}),
        "model": "openmoss/MOSS-VoiceGenerator",
        "codec": "openmoss/MOSS-Audio-Tokenizer",
    }


def build_sound_effect_snapshot(workspace: dict[str, Any]) -> dict[str, Any]:
    parameters = dict(workspace.get("parameters") or {})
    return {
        "prompt": str(workspace.get("prompt") or "").strip(),
        "seconds": int(parameters.get("seconds", 10)),
        "num_inference_steps": int(parameters.get("num_inference_steps", 100)),
        "cfg_scale": float(parameters.get("cfg_scale", 4.0)),
        "sigma_shift": float(parameters.get("sigma_shift", 5.0)),
        "seed": int(parameters.get("seed", 2026)),
        "model": "openmoss/MOSS-SoundEffect-v2.0",
        "runtime_precision": "float16",
        "low_vram": True,
    }


def _safe_filename_component(value: str, fallback: str) -> str:
    clean = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", (value or "").strip())
    clean = re.sub(r"\s+", " ", clean).strip(" ._")
    return clean[:80] or fallback


def _next_output_index(output_dir: Path, minimum: int = 1) -> int:
    """Keep the visible sequence monotonic even after history records are cleared."""
    highest = 0
    pattern = re.compile(r"_(\d{3,})_\d{8}_\d{6}\.wav$", re.IGNORECASE)
    for candidate in output_dir.glob("*.wav"):
        match = pattern.search(candidate.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return max(minimum, highest + 1)


def _write_sidecar(path: Path, metadata: dict[str, Any]) -> None:
    target = path.with_suffix(path.suffix + ".json")
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    os.replace(temporary, target)


class TaskService:
    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="moss-task")
        self.lock = threading.RLock()
        self.futures: dict[str, Future] = {}

    def _create(self, project_id: str, module: str, workspace: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        get_project(project_id)
        task_id = uuid.uuid4().hex
        timestamp = now()
        payload = {"project_id": project_id, "module": module, "workspace": workspace, "generation_snapshot": snapshot}
        task = {
            "id": task_id,
            "project_id": project_id,
            "module": module,
            "status": "queued",
            "progress": 0.0,
            "message": "等待执行",
            "payload": payload,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        insert_task(task)
        with self.lock:
            self.futures[task_id] = self.executor.submit(self._run, task_id)
        result = get_task(task_id)
        EVENTS.publish("task.updated", result)
        return result

    def create(self, project_id: str, workspace: dict[str, Any]) -> dict[str, Any]:
        if not MODULE_SERVICE.describe("speech")["installed"]:
            raise FileNotFoundError("请先安装或重新检测 MOSS-TTS v1.5 4B 与 MOSS-Audio-Tokenizer-v2。")
        workspace = normalize_speech_workspace(workspace)
        return self._create(project_id, "speech", workspace, build_generation_snapshot(workspace))

    def create_voice_design(self, project_id: str, workspace: dict[str, Any]) -> dict[str, Any]:
        if not MODULE_SERVICE.describe("voice_design")["installed"]:
            raise FileNotFoundError("请先安装或重新检测 MOSS-VoiceGenerator 与独立运行环境。")
        return self._create(project_id, "voice_design", workspace, build_voice_design_snapshot(workspace))

    def create_sound_effect(self, project_id: str, workspace: dict[str, Any]) -> dict[str, Any]:
        descriptor = MODULE_SERVICE.describe("sound_effect")
        if not descriptor["installed"]:
            raise FileNotFoundError("请先安装或重新检测 MOSS-SoundEffect v2.0 与独立运行环境。")
        if not descriptor.get("engine_available"):
            raise RuntimeError(descriptor.get("engine_message") or "音效生成引擎不可用。")
        return self._create(project_id, "sound_effect", workspace, build_sound_effect_snapshot(workspace))

    def cancel(self, task_id: str) -> dict[str, Any]:
        task = get_task(task_id)
        if task["status"] not in {"queued", "running"}:
            return task
        with self.lock:
            future = self.futures.get(task_id)
            cancelled = bool(future and future.cancel())
        if cancelled or task["status"] == "queued":
            updated = self._publish_task(task_id, status="cancelled", message="任务已取消", cancel_requested=1)
            with self.lock:
                self.futures.pop(task_id, None)
        else:
            message = "正在停止，结束后自动移除" if task.get("remove_after_stop") else "正在安全停止"
            updated = self._publish_task(task_id, message=message, cancel_requested=1)
        return updated

    def remove(self, task_id: str) -> dict[str, Any]:
        task = get_task(task_id)
        if task["status"] in {"queued", "running"}:
            update_task(task_id, remove_after_stop=1, message="正在安全停止，结束后自动移除")
            task = self.cancel(task_id)
            return {"task_id": task_id, "pending": task["status"] in {"queued", "running"}, "task": task}
        delete_task(task_id)
        EVENTS.publish("task.removed", {"id": task_id, "project_id": task["project_id"], "module": task["module"]})
        return {"task_id": task_id, "pending": False, "task": None}

    def _publish_task(self, task_id: str, **changes: Any) -> dict[str, Any]:
        task = update_task(task_id, **changes)
        EVENTS.publish("task.updated", task)
        if task.get("remove_after_stop") and task["status"] not in {"queued", "running"}:
            delete_task(task_id)
            EVENTS.publish("task.removed", {"id": task_id, "project_id": task["project_id"], "module": task["module"]})
        return task

    def _runtime_progress(self, task_id: str, value: float, message: str) -> None:
        self._publish_task(task_id, progress=max(.01, min(.94, value * .94)), message=message)
        EVENTS.publish("runtime.updated", RUNTIME.describe())

    def _run_speech(self, task_id: str, payload: dict[str, Any]) -> None:
        temporary_reference: Path | None = None
        temporary_raw: Path | None = None
        project = get_project(payload["project_id"])
        workspace = payload["workspace"]
        generation_snapshot = payload.get("generation_snapshot") or build_generation_snapshot(workspace)
        try:
            RUNTIME.prepare("speech")
            EVENTS.publish("runtime.updated", RUNTIME.describe())
            asset_id = workspace.get("voice_id") or workspace.get("reference_id")
            reference_path = voice_path(asset_id) if asset_id else None
            if reference_path is not None:
                source_reference = reference_path
                reference_path = prepare_trimmed_reference(
                    source_reference,
                    float(workspace.get("reference_trim_start") or 0),
                    workspace.get("reference_trim_end"),
                )
                if reference_path != source_reference:
                    temporary_reference = reference_path
            segment_target_tokens = None
            if bool(workspace.get("manual_speed_enabled")):
                segments = split_text(workspace["text"], int(workspace["parameters"]["segment_chars"]))
                level = str(workspace.get("manual_speed_level") or "中等")
                segment_target_tokens = [estimate_speed_tokens(segment, level) for segment in segments]
            model_payload = {
                "text": workspace["text"],
                "language": workspace.get("language", "Chinese"),
                "instruction": str(workspace.get("instruction") or "").strip(),
                "parameters": workspace["parameters"],
                "reference_path": str(reference_path) if reference_path else None,
                "segment_target_tokens": segment_target_tokens,
            }
            raw = ENGINE.synthesize(
                model_payload,
                lambda value, message: self._runtime_progress(task_id, value, message),
                lambda: cancel_requested(task_id),
            )
            temporary_raw = Path(raw["source_path"])
            self._publish_task(task_id, progress=.96, message="正在执行输出工程")
            profile = dict(workspace["output_profile"])
            index = len(list_outputs(payload["project_id"], "speech")) + 1
            voice_name = project.get("voice") or "无参考音色"
            from .output_engineering import render_output
            output_directory = project_output_directory(payload["project_id"], "speech", create=True)
            metadata = render_output(raw["source_path"], profile, output_directory, project["name"], voice_name, index)
            metadata.update({
                "voice": voice_name,
                "text": workspace["text"],
                "language": workspace.get("language", ""),
                "preset": workspace.get("preset", "标准"),
                "generation_snapshot": generation_snapshot,
            })
            record = add_output(payload["project_id"], task_id, metadata, "speech", "speech_output")
            self._publish_task(task_id, status="completed", progress=1.0, message="生成完成", result_id=record["id"])
            EVENTS.publish("project.saved", {"id": payload["project_id"], "module": "speech"})
        finally:
            if temporary_reference is not None:
                temporary_reference.unlink(missing_ok=True)
            if temporary_raw is not None:
                temporary_raw.unlink(missing_ok=True)

    def _run_voice_design(self, task_id: str, payload: dict[str, Any]) -> None:
        project = get_project(payload["project_id"])
        workspace = payload["workspace"]
        generation_snapshot = payload.get("generation_snapshot") or build_voice_design_snapshot(workspace)
        output_dir = project_output_directory(payload["project_id"], "voice_design", create=True)
        index = _next_output_index(output_dir, len(list_outputs(payload["project_id"], "voice_design")) + 1)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_name = _safe_filename_component(project["name"], "未命名项目")
        filename = f"{project_name}_音色设计_{index:03d}_{timestamp}.wav"
        output_path = output_dir / filename
        partial_path = output_dir / f".{filename}.partial.wav"
        partial_sidecar = partial_path.with_suffix(partial_path.suffix + ".json")
        final_sidecar = output_path.with_suffix(output_path.suffix + ".json")
        record_registered = False
        partial_path.unlink(missing_ok=True)
        partial_sidecar.unlink(missing_ok=True)
        RUNTIME.prepare("voice_design")
        EVENTS.publish("runtime.updated", RUNTIME.describe())
        try:
            generated = WORKERS.request_voice_design(
                {
                    "text": workspace["text"],
                    "instruction": workspace["instruction"],
                    "parameters": workspace["parameters"],
                    "output_path": str(partial_path),
                },
                lambda value, message: self._runtime_progress(task_id, value, message),
                lambda: cancel_requested(task_id),
            )
            if not partial_path.is_file() or partial_path.stat().st_size <= 44:
                raise RuntimeError("音色设计输出未完整写入。")
            os.replace(partial_path, output_path)
            metadata = {
                "path": str(output_path),
                "filename": filename,
                "created_at": now(),
                "duration": round(float(generated["duration"]), 3),
                "sample_rate": int(generated["sample_rate"]),
                "channels": int(generated["channels"]),
                "bit_depth": 24,
                "format": "WAV",
                "voice": "设计音色",
                "text": workspace["text"],
                "instruction": workspace["instruction"],
                "runtime_precision": generated.get("runtime_precision", ""),
                "precision_report": generated.get("precision_report", {}),
                "cuda_peak_allocated_mib": generated.get("cuda_peak_allocated_mib"),
                "cuda_peak_reserved_mib": generated.get("cuda_peak_reserved_mib"),
                "generation_snapshot": generation_snapshot,
            }
            _write_sidecar(output_path, metadata)
            try:
                record = add_output(payload["project_id"], task_id, metadata, "voice_design", "voice_design_output")
                record_registered = True
            except Exception:
                output_path.unlink(missing_ok=True)
                final_sidecar.unlink(missing_ok=True)
                raise
            self._publish_task(task_id, status="completed", progress=1.0, message="音色设计完成", result_id=record["id"])
            EVENTS.publish("project.saved", {"id": payload["project_id"], "module": "voice_design"})
        except Exception:
            partial_path.unlink(missing_ok=True)
            partial_sidecar.unlink(missing_ok=True)
            if output_path.is_file() and not record_registered:
                output_path.unlink(missing_ok=True)
                final_sidecar.unlink(missing_ok=True)
            raise

    def _run_sound_effect(self, task_id: str, payload: dict[str, Any]) -> None:
        project = get_project(payload["project_id"])
        workspace = payload["workspace"]
        generation_snapshot = payload.get("generation_snapshot") or build_sound_effect_snapshot(workspace)
        parameters = dict(workspace.get("parameters") or {})
        output_dir = project_output_directory(payload["project_id"], "sound_effect", create=True)
        index = _next_output_index(output_dir, len(list_outputs(payload["project_id"], "sound_effect")) + 1)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_name = _safe_filename_component(project["name"], "未命名项目")
        filename = f"{project_name}_音效_{index:03d}_{timestamp}.wav"
        output_path = output_dir / filename
        partial_path = output_dir / f".{filename}.partial.wav"
        partial_sidecar = partial_path.with_suffix(partial_path.suffix + ".json")
        final_sidecar = output_path.with_suffix(output_path.suffix + ".json")
        record_registered = False
        partial_path.unlink(missing_ok=True)
        partial_sidecar.unlink(missing_ok=True)
        RUNTIME.prepare("sound_effect")
        EVENTS.publish("runtime.updated", RUNTIME.describe())
        try:
            generated = WORKERS.request_sound_effect(
                {
                    "prompt": workspace["prompt"],
                    "seconds": int(parameters.get("seconds", 10)),
                    "num_inference_steps": int(parameters.get("num_inference_steps", 100)),
                    "cfg_scale": float(parameters.get("cfg_scale", 4.0)),
                    "sigma_shift": float(parameters.get("sigma_shift", 5.0)),
                    "seed": int(parameters.get("seed", 2026)),
                    "output_path": str(partial_path),
                },
                lambda value, message: self._runtime_progress(task_id, value, message),
                lambda: cancel_requested(task_id),
            )
            if not partial_path.is_file() or partial_path.stat().st_size <= 44:
                raise RuntimeError("音效输出未完整写入。")
            os.replace(partial_path, output_path)
            generation_snapshot.update({
                "runtime_precision": generated.get("runtime_precision", "float16"),
                "low_vram": bool(generated.get("low_vram", True)),
            })
            metadata = {
                "path": str(output_path),
                "filename": filename,
                "created_at": now(),
                "duration": round(float(generated["duration"]), 3),
                "sample_rate": int(generated["sample_rate"]),
                "channels": int(generated["channels"]),
                "bit_depth": int(generated.get("bit_depth", 24)),
                "format": "WAV",
                "voice": "项目音效",
                "text": workspace["prompt"],
                "prompt": workspace["prompt"],
                "favorite": False,
                "runtime_precision": generated.get("runtime_precision", "float16"),
                "low_vram": bool(generated.get("low_vram", True)),
                "cuda_peak_allocated_mib": generated.get("cuda_peak_allocated_mib"),
                "cuda_peak_reserved_mib": generated.get("cuda_peak_reserved_mib"),
                "generation_snapshot": generation_snapshot,
            }
            _write_sidecar(output_path, metadata)
            try:
                record = add_output(payload["project_id"], task_id, metadata, "sound_effect", "sound_effect_output")
                record_registered = True
            except Exception:
                output_path.unlink(missing_ok=True)
                final_sidecar.unlink(missing_ok=True)
                raise
            self._publish_task(task_id, status="completed", progress=1.0, message="音效生成完成", result_id=record["id"])
            EVENTS.publish("project.saved", {"id": payload["project_id"], "module": "sound_effect"})
        except Exception:
            partial_path.unlink(missing_ok=True)
            partial_sidecar.unlink(missing_ok=True)
            if output_path.is_file() and not record_registered:
                output_path.unlink(missing_ok=True)
                final_sidecar.unlink(missing_ok=True)
            raise

    def _run(self, task_id: str) -> None:
        if cancel_requested(task_id):
            self._publish_task(task_id, status="cancelled", message="任务已取消")
            with self.lock:
                self.futures.pop(task_id, None)
            return
        self._publish_task(task_id, status="running", progress=.01, message="正在准备任务")
        payload = task_payload(task_id)
        module = str(payload.get("module") or get_task(task_id).get("module") or "speech")
        try:
            if module == "speech":
                self._run_speech(task_id, payload)
            elif module == "voice_design":
                self._run_voice_design(task_id, payload)
            elif module == "sound_effect":
                self._run_sound_effect(task_id, payload)
            else:
                raise ValueError("当前模块尚未接入生成引擎。")
            EVENTS.publish("runtime.updated", RUNTIME.describe())
        except TaskCancelled as exc:
            self._publish_task(task_id, status="cancelled", message=str(exc), error=None)
            EVENTS.publish("runtime.updated", RUNTIME.describe())
        except Exception as exc:
            if module == "speech":
                ENGINE.state = "error"
                ENGINE.message = "任务失败，正在释放模型"
                ENGINE.release()
            else:
                WORKERS.release()
            self._publish_task(task_id, status="failed", message="生成失败", error=str(exc))
            EVENTS.publish("runtime.updated", RUNTIME.describe())
        finally:
            with self.lock:
                self.futures.pop(task_id, None)

    def release_runtime(self) -> dict[str, Any]:
        snapshot = RUNTIME.release()
        EVENTS.publish("runtime.updated", snapshot)
        return snapshot

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
        RUNTIME.release()


TASKS = TaskService()
