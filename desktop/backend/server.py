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

from app.model_engine import ENGINE

from .database import DB
from .defaults import LANGUAGES, PARAMETER_PRESETS
from .desktop_control import DESKTOP
from .events import EVENTS
from .paths import ASSETS_DIR, FRONTEND_DIST, ensure_directories
from .repository import (
    add_upload,
    artifact,
    clear_finished_tasks,
    clear_outputs,
    close_project,
    create_project,
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
    reconcile_project_index,
    rebuild_project_index,
    save_project,
    save_style,
    update_voice,
)
from .schemas import ProjectCreate, ProjectPatch, StyleCreate, TaskCreate, VoicePatch
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
    MONITOR.stop()
    if reconcile_thread is not None and reconcile_thread.is_alive():
        reconcile_thread.join(timeout=2)
    DB.close()


app = FastAPI(title="龙融影业 AI 配音台", version="2.0.0-dev", lifespan=lifespan, docs_url=None, redoc_url=None)


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
        "product": "AI 配音台",
        "version": "2.0.0-dev",
        "projects": list_projects(),
        "voices": list_voices(),
        "styles": list_styles(),
        "runtime": ENGINE.describe(),
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
        "product": "AI 配音台",
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
        result = save_project(project_id, request.revision, request.workspace)
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


@app.get("/api/v2/projects/{project_id}/history")
def project_history(project_id: str):
    return list_outputs(project_id)


@app.delete("/api/v2/projects/{project_id}/history", status_code=204)
def project_history_clear(project_id: str, delete_files: bool = False):
    try:
        clear_outputs(project_id, delete_files)
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


@app.post("/api/v2/tasks")
def task_create(request: TaskCreate):
    if not request.workspace.text.strip():
        raise HTTPException(status_code=422, detail="请输入需要合成的文本。")
    try:
        return TASKS.create(request.project_id, request.workspace.model_dump(mode="json"))
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.get("/api/v2/tasks")
def tasks(project_id: str = Query(...)):
    return list_tasks(project_id)


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


@app.delete("/api/v2/tasks", status_code=204)
def tasks_clear(project_id: str = Query(...)):
    clear_finished_tasks(project_id)


@app.get("/api/v2/runtime")
def runtime():
    return ENGINE.describe()


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
                    yield EVENTS.encode({"type": "runtime.updated", "payload": ENGINE.describe()})
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
    return FileResponse(ASSETS_DIR / "longrong-icon.svg", media_type="image/svg+xml")


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
