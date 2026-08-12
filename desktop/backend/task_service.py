from __future__ import annotations

import threading
import uuid
import re
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.model_engine import ENGINE, TaskCancelled, split_text

from .audio import prepare_trimmed_reference
from .events import EVENTS
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
    task_payload,
    update_task,
    voice_path,
)


SPEED_TOKENS_PER_CHAR = {
    "慢": 3.8,
    "较慢": 3.4,
    "中等": 3.0,
    "较快": 2.65,
    "快": 2.3,
}


def estimate_speed_tokens(text: str, level: str) -> int:
    """Estimate duration-control frames from effective character count and a named speed tier."""
    effective_chars = len(re.sub(r"\s+", "", text or ""))
    factor = SPEED_TOKENS_PER_CHAR.get(level, SPEED_TOKENS_PER_CHAR["中等"])
    return max(13, int(effective_chars * factor + .5))


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


class TaskService:
    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="moss-task")
        self.lock = threading.RLock()
        self.futures: dict[str, Future] = {}

    def create(self, project_id: str, workspace: dict[str, Any]) -> dict[str, Any]:
        get_project(project_id)
        task_id = uuid.uuid4().hex
        timestamp = now()
        payload = {"project_id": project_id, "workspace": workspace, "generation_snapshot": build_generation_snapshot(workspace)}
        task = {"id": task_id, "project_id": project_id, "status": "queued", "progress": 0.0, "message": "等待执行", "payload": payload, "created_at": timestamp, "updated_at": timestamp}
        insert_task(task)
        with self.lock:
            self.futures[task_id] = self.executor.submit(self._run, task_id)
        result = get_task(task_id)
        EVENTS.publish("task.updated", result)
        return result

    def cancel(self, task_id: str) -> dict[str, Any]:
        task = get_task(task_id)
        if task["status"] not in {"queued", "running"}:
            return task
        with self.lock:
            future = self.futures.get(task_id)
            cancelled = bool(future and future.cancel())
        if cancelled or task["status"] == "queued":
            updated = self._publish_task(task_id, status="cancelled", message="任务已取消", cancel_requested=1)
        else:
            message = "将在当前文本段结束后停止并移除" if task.get("remove_after_stop") else "将在当前文本段结束后停止"
            updated = self._publish_task(task_id, message=message, cancel_requested=1)
        return updated

    def remove(self, task_id: str) -> dict[str, Any]:
        task = get_task(task_id)
        if task["status"] in {"queued", "running"}:
            update_task(task_id, remove_after_stop=1, message="正在安全停止，结束后自动移除")
            task = self.cancel(task_id)
            return {"task_id": task_id, "pending": task["status"] in {"queued", "running"}, "task": task}
        delete_task(task_id)
        EVENTS.publish("task.removed", {"id": task_id, "project_id": task["project_id"]})
        return {"task_id": task_id, "pending": False, "task": None}

    def _publish_task(self, task_id: str, **changes: Any) -> dict[str, Any]:
        task = update_task(task_id, **changes)
        EVENTS.publish("task.updated", task)
        if task.get("remove_after_stop") and task["status"] not in {"queued", "running"}:
            delete_task(task_id)
            EVENTS.publish("task.removed", {"id": task_id, "project_id": task["project_id"]})
        return task

    def _run(self, task_id: str) -> None:
        if cancel_requested(task_id):
            return
        temporary_reference: Path | None = None
        temporary_raw: Path | None = None
        self._publish_task(task_id, status="running", progress=.01, message="正在准备任务")
        payload = task_payload(task_id)
        project = get_project(payload["project_id"])
        workspace = payload["workspace"]
        generation_snapshot = payload.get("generation_snapshot") or build_generation_snapshot(workspace)

        def progress(value: float, message: str) -> None:
            self._publish_task(task_id, progress=max(.01, min(.94, value * .94)), message=message)
            EVENTS.publish("runtime.updated", ENGINE.describe())

        try:
            asset_id = workspace.get("voice_id") or workspace.get("reference_id")
            reference_path = voice_path(asset_id) if asset_id else None
            if reference_path is not None:
                source_reference = reference_path
                reference_path = prepare_trimmed_reference(source_reference, float(workspace.get("reference_trim_start") or 0), workspace.get("reference_trim_end"))
                if reference_path != source_reference:
                    temporary_reference = reference_path
            instruction = str(workspace.get("instruction") or "").strip()
            segment_target_tokens = None
            if bool(workspace.get("manual_speed_enabled")):
                segments = split_text(workspace["text"], int(workspace["parameters"]["segment_chars"]))
                level = str(workspace.get("manual_speed_level") or "中等")
                segment_target_tokens = [estimate_speed_tokens(segment, level) for segment in segments]
            model_payload = {
                "text": workspace["text"], "language": workspace.get("language", "Chinese"), "instruction": instruction,
                "parameters": workspace["parameters"], "reference_path": str(reference_path) if reference_path else None,
                "segment_target_tokens": segment_target_tokens,
            }
            raw = ENGINE.synthesize(model_payload, progress, lambda: cancel_requested(task_id))
            temporary_raw = Path(raw["source_path"])
            self._publish_task(task_id, progress=.96, message="正在执行输出工程")
            profile = dict(workspace["output_profile"])
            if not profile.get("output_directory"):
                profile["output_directory"] = project["workspace"]["output_profile"]["output_directory"]
            index = len(list_outputs(payload["project_id"])) + 1
            voice_name = project.get("voice") or "默认音色"
            from .output_engineering import render_output

            metadata = render_output(raw["source_path"], profile, project["name"], voice_name, index)
            metadata.update({
                "voice": voice_name,
                "text": workspace["text"],
                "language": workspace.get("language", ""),
                "preset": workspace.get("preset", "标准"),
                "generation_snapshot": generation_snapshot,
            })
            record = add_output(payload["project_id"], task_id, metadata)
            completed = self._publish_task(task_id, status="completed", progress=1.0, message="生成完成", result_id=record["id"])
            EVENTS.publish("runtime.updated", ENGINE.describe())
            EVENTS.publish("project.saved", {"id": payload["project_id"]})
        except TaskCancelled as exc:
            self._publish_task(task_id, status="cancelled", message=str(exc), error=None)
            ENGINE.state = "loaded" if ENGINE.model is not None else "idle"
            ENGINE.message = "MOSS-TTS 1.5 4B 已就绪" if ENGINE.model is not None else "模型未加载"
            EVENTS.publish("runtime.updated", ENGINE.describe())
        except Exception as exc:
            ENGINE.state = "error"
            ENGINE.message = "任务失败，正在释放模型"
            EVENTS.publish("runtime.updated", ENGINE.describe())
            ENGINE.release()
            self._publish_task(task_id, status="failed", message="生成失败", error=str(exc))
            EVENTS.publish("runtime.updated", ENGINE.describe())
        finally:
            if temporary_reference is not None:
                temporary_reference.unlink(missing_ok=True)
            if temporary_raw is not None:
                temporary_raw.unlink(missing_ok=True)
            with self.lock:
                self.futures.pop(task_id, None)

    def release_runtime(self) -> dict[str, Any]:
        ENGINE.release()
        snapshot = ENGINE.describe()
        EVENTS.publish("runtime.updated", snapshot)
        return snapshot

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
        ENGINE.release()


TASKS = TaskService()
