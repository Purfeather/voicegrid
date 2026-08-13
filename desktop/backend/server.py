from __future__ import annotations

import asyncio
import queue
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from desktop.native.build_info import BUILD_INFO
from .api import assets_router, modules_router, projects_router, tasks_router
from .api.errors import translate_error
from .database import DB
from .defaults import LANGUAGES, PARAMETER_PRESETS
from .desktop_control import DESKTOP
from .events import EVENTS
from .module_service import MODULE_SERVICE
from .paths import ASSETS_DIR, FRONTEND_DIST, ensure_directories
from .repository import (
    artifact,
    list_projects,
    list_styles,
    list_voices,
    mark_project_index_ready,
    mark_interrupted_projects,
    project_files_exist,
    project_index_count,
    project_index_status,
    reconcile_project_index,
    rebuild_project_index,
)
from .runtime_service import RUNTIME
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


app = FastAPI(title=BUILD_INFO.product, version=BUILD_INFO.version, lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(projects_router)
app.include_router(assets_router)
app.include_router(tasks_router)
app.include_router(modules_router)


def _translate_error(exc: Exception) -> HTTPException:
    return translate_error(exc)


@app.get("/api/v2/bootstrap")
def bootstrap():
    return {
        "brand": BUILD_INFO.brand,
        "product": BUILD_INFO.product,
        "version": BUILD_INFO.version,
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
        "version": BUILD_INFO.version,
    }


@app.get("/api/v2/bootstrap/core")
def bootstrap_core():
    return {
        "brand": BUILD_INFO.brand,
        "product": BUILD_INFO.product,
        "version": BUILD_INFO.version,
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
