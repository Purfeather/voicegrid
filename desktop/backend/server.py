from __future__ import annotations

import asyncio
import os
import queue
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .database import DB
from .defaults import LANGUAGES, PARAMETER_PRESETS
from .desktop_control import DESKTOP
from .events import EVENTS
from .module_service import MODULE_SERVICE
from .paths import ASSETS_DIR, FRONTEND_DIST, ensure_directories
from .repository import (
    add_upload,
    artifact,
    clear_project_activity,
    clear_finished_tasks,
    clear_outputs,
    close_project,
    create_project,
    delete_project,
    delete_style,
    delete_voice,
    get_project,
    get_task,
    list_outputs,
    list_projects,
    list_styles,
    list_tasks,
    list_voices,
    mark_project_index_ready,
    mark_interrupted_projects,
    project_files_exist,
    project_index_count,
    project_index_status,
    project_output_directory,
    reconcile_project_index,
    rebuild_project_index,
    save_project,
    save_output_as_voice,
    save_style,
    update_voice,
    update_sound_effect_output,
    delete_sound_effect_output,
)
from .runtime_service import RUNTIME
from .schemas import (
    ModuleInstallRequest,
    ModuleTaskCreate,
    ProjectCreate,
    ProjectPatch,
    SaveDesignedVoice,
    SoundEffectOutputPatch,
    StyleCreate,
    VoicePatch,
)
from .system_monitor import MONITOR, snapshot as system_snapshot
from .task_service import TASKS


def _report_startup(phase: str, message: str) -> None:
    reporter = getattr(app.state, "startup_reporter", None)
    if reporter is not None:
        reporter(phase, message)


def _delayed_reconcile() -> None:
    time.sleep(.75)
    try:
        reconcile_project_index()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_directories()
    _report_startup("database", "正在检查本地数据库")
    database_status = DB.initialize()
    _report_startup("project_recovery", "正在恢复项目状态")
    indexed = project_index_count()
    requires_rebuild = bool(
        database_status["created"]
        or database_status["recovered"]
        or database_status["schema_changed"]
        or (indexed == 0 and project_files_exist())
    )
    if requires_rebuild:
        rebuild_project_index()
    else:
        mark_project_index_ready()
    mark_interrupted_projects()
    MONITOR.start()
    reconcile_thread = None
    if not requires_rebuild:
        reconcile_thread = threading.Thread(target=_delayed_reconcile, name="project-index-reconcile", daemon=True)
        reconcile_thread.start()
    _report_startup("api", "本地服务已就绪")
    yield
    TASKS.shutdown()
    MODULE_SERVICE.shutdown()
    MONITOR.stop()
    if reconcile_thread is not None and reconcile_thread.is_alive():
        reconcile_thread.join(timeout=2)
    DB.close()


app = FastAPI(title="声格 VoiceGrid", version="2.0.0-dev", lifespan=lifespan, docs_url=None, redoc_url=None)


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v2/bootstrap")
def bootstrap():
    return {
        "brand": "龙融影业",
        "product": "声格 VoiceGrid",
        "version": "2.0.0-dev",
        "projects": list_projects(),
        "voices": list_voices(),
        "styles": list_styles(),
        "runtime": RUNTIME.describe(),
        "modules": MODULE_SERVICE.list(),
        "metrics": system_snapshot(),
        "languages": LANGUAGES,
    }


@app.get("/api/v2/health")
def health():
    return {
        "ok": DB.initialized,
        "api": "ready",
        "database": DB.health(),
        "project_index": project_index_status(),
        "version": "2.0.0-dev",
    }


@app.get("/api/v2/bootstrap/core")
def bootstrap_core():
    return {
        "brand": "龙融影业",
        "product": "声格 VoiceGrid",
        "version": "2.0.0-dev",
        "languages": LANGUAGES,
        "model_capabilities": {
            "key": "moss-tts-1.5",
            "name": "MOSS-TTS Local Transformer",
            "version": "1.5 · 4B",
            "offline": True,
            "lazy_load": True,
        },
        "defaults": {
            "preset": "标准",
            "parameters": PARAMETER_PRESETS["标准"],
        },
    }


@app.get("/api/v2/projects")
def projects():
    return list_projects()


@app.post("/api/v2/projects")
def project_create(request: ProjectCreate):
    try:
        return create_project(request.name, request.language)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.get("/api/v2/projects/{project_id}")
def project_get(project_id: str, begin_session: bool = True):
    try:
        return get_project(project_id, begin_session)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.patch("/api/v2/projects/{project_id}")
def project_patch(project_id: str, request: ProjectPatch):
    try:
        result = save_project(project_id, request.revision, request.workspace, request.module)
        EVENTS.publish("project.saved", {"id": project_id, "revision": result["revision"]})
        return result
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post("/api/v2/projects/{project_id}/close", status_code=204)
def project_close(project_id: str):
    try:
        close_project(project_id)
    except Exception as exc:
        raise _translate_error(exc) from exc

@app.delete("/api/v2/projects/{project_id}", status_code=204)
def project_remove(project_id: str):
    try:
        delete_project(project_id)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.get("/api/v2/projects/{project_id}/history")
def project_history(project_id: str, module: str | None = Query(default=None)):
    return list_outputs(project_id, module)


@app.delete("/api/v2/projects/{project_id}/history", status_code=204)
def project_history_clear(project_id: str, delete_files: bool = False, module: str | None = Query(default=None)):
    try:
        clear_outputs(project_id, delete_files, module)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.delete("/api/v2/projects/{project_id}/activity")
def project_activity_clear(project_id: str, delete_files: bool = False, module: str | None = Query(default=None)):
    try:
        result = clear_project_activity(project_id, delete_files, module)
        EVENTS.publish("activity.cleared", {"project_id": project_id, "module": module, **result})
        return result
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post("/api/v2/projects/{project_id}/outputs/{module}/open", status_code=204)
def project_output_open(project_id: str, module: str):
    try:
        get_project(project_id)
        folder = project_output_directory(project_id, module, create=True)
        os.startfile(str(folder))
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.get("/api/v2/voices")
def voices():
    return list_voices()


@app.post("/api/v2/voices/uploads")
async def voice_upload(file: UploadFile = File(...)):
    try:
        content = await file.read()
        if len(content) > 256 * 1024 * 1024:
            raise ValueError("参考音频不能超过 256MB。")
        return add_upload(file.filename or "reference.wav", content)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.patch("/api/v2/voices/{asset_id}")
def voice_update(asset_id: str, request: VoicePatch):
    try:
        return update_voice(asset_id, request)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.delete("/api/v2/voices/{asset_id}", status_code=204)
def voice_remove(asset_id: str, delete_file: bool = True):
    try:
        delete_voice(asset_id, delete_file)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.get("/api/v2/styles")
def styles():
    return list_styles()


@app.post("/api/v2/styles")
def style_create(request: StyleCreate):
    try:
        return save_style(request.name, request.instruction)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.delete("/api/v2/styles/{name}", status_code=204)
def style_remove(name: str):
    try:
        delete_style(name)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post("/api/v2/module-tasks")
def module_task_create(request: ModuleTaskCreate):
    workspace = request.workspace.model_dump(mode="json")
    try:
        if request.module == "speech":
            if not workspace["text"].strip():
                raise ValueError("请输入需要合成的文本。")
            return TASKS.create(request.project_id, workspace)
        if request.module == "voice_design":
            if not workspace["text"].strip():
                raise ValueError("请输入试听台词。")
            if not workspace["instruction"].strip():
                raise ValueError("请输入最终音色提示词。")
            return TASKS.create_voice_design(request.project_id, workspace)
        if request.module == "sound_effect":
            if not workspace["prompt"].strip():
                raise ValueError("请输入需要生成的声音场景。")
            return TASKS.create_sound_effect(request.project_id, workspace)
        raise ValueError("未知的生成模块。")
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post("/api/v2/voice-design/outputs/{output_id}/save-as-voice")
def voice_design_save(output_id: str, request: SaveDesignedVoice):
    try:
        voice = save_output_as_voice(output_id, request.name)
        EVENTS.publish("voice.updated", voice)
        return voice
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.patch("/api/v2/sound-effects/outputs/{output_id}")
def sound_effect_output_update(output_id: str, request: SoundEffectOutputPatch):
    try:
        output = update_sound_effect_output(output_id, request)
        EVENTS.publish("project.saved", {"id": output["project_id"], "module": "sound_effect"})
        return output
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.delete("/api/v2/sound-effects/outputs/{output_id}", status_code=204)
def sound_effect_output_remove(output_id: str, delete_file: bool = True):
    try:
        project_id = delete_sound_effect_output(output_id, delete_file)
        EVENTS.publish("project.saved", {"id": project_id, "module": "sound_effect"})
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.get("/api/v2/tasks")
def tasks(project_id: str = Query(...), module: str | None = Query(default=None)):
    return list_tasks(project_id, module)


@app.get("/api/v2/tasks/{task_id}")
def task_get(task_id: str):
    try:
        return get_task(task_id)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post("/api/v2/tasks/{task_id}/cancel")
def task_cancel(task_id: str):
    try:
        return TASKS.cancel(task_id)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.delete("/api/v2/tasks/{task_id}")
def task_remove(task_id: str):
    try:
        return TASKS.remove(task_id)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.delete("/api/v2/tasks", status_code=204)
def tasks_clear(project_id: str = Query(...), module: str | None = Query(default=None)):
    clear_finished_tasks(project_id, module)


@app.get("/api/v2/modules")
def modules():
    return MODULE_SERVICE.list()


@app.post("/api/v2/modules/{module_id}/detect")
def module_detect(module_id: str):
    try:
        return MODULE_SERVICE.detect(module_id)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post("/api/v2/modules/{module_id}/install")
def module_install(module_id: str, request: ModuleInstallRequest):
    try:
        return MODULE_SERVICE.install(module_id, request.confirm)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post("/api/v2/modules/{module_id}/repair")
def module_repair(module_id: str, request: ModuleInstallRequest):
    try:
        return MODULE_SERVICE.install(module_id, request.confirm)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.get("/api/v2/runtime")
def runtime():
    return RUNTIME.describe()


@app.post("/api/v2/runtime/release")
def runtime_release():
    if any(task["status"] == "running" for project in list_projects() for task in list_tasks(project["id"])):
        raise HTTPException(status_code=409, detail="当前有任务正在运行，无法释放模型。")
    return TASKS.release_runtime()


@app.get("/api/v2/system/metrics")
def system_metrics():
    return system_snapshot()


@app.get("/api/v2/events")
async def event_stream():
    async def generate():
        with EVENTS.subscribe() as subscriber:
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.get, True, 2.0)
                    yield EVENTS.encode(event)
                except queue.Empty:
                    yield EVENTS.encode({"type": "metrics.updated", "payload": system_snapshot()})
                    yield EVENTS.encode({"type": "runtime.updated", "payload": RUNTIME.describe()})
                except asyncio.CancelledError:
                    break
    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/v2/artifacts/{asset_id}")
def artifact_file(asset_id: str, download: bool = False):
    try:
        path, filename = artifact(asset_id)
        if not path.is_file():
            raise FileNotFoundError("文件资源已经不存在。")
        return FileResponse(path, filename=filename if download else None, content_disposition_type="attachment" if download else "inline")
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post("/api/v2/artifacts/{asset_id}/open", status_code=204)
def artifact_open(asset_id: str):
    try:
        path, _ = artifact(asset_id)
        folder = path.parent
        if not folder.is_dir():
            raise FileNotFoundError("输出目录不存在。")
        os.startfile(str(folder))
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.get("/api/v2/brand/icon")
def brand_icon():
    return FileResponse(ASSETS_DIR / "voicegrid-icon.svg", media_type="image/svg+xml")


@app.get("/api/v2/desktop/status")
def desktop_status():
    return DESKTOP.status()


@app.post("/api/v2/desktop/action/{action}")
def desktop_action(action: str):
    if action not in {"show", "hide", "minimize", "maximize", "exit"}:
        raise HTTPException(status_code=400, detail="不支持的窗口操作。")
    try:
        return {"ok": True, "result": DESKTOP.command(action)}
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.get("/{path:path}")
def frontend(path: str):
    target = (FRONTEND_DIST / path).resolve()
    if FRONTEND_DIST.resolve() in target.parents and target.is_file():
        return FileResponse(target)
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(status_code=503, content={"detail": "前端尚未构建。"})
