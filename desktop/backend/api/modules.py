from __future__ import annotations

from fastapi import APIRouter, HTTPException
from ..module_service import MODULE_SERVICE
from ..repository import list_projects, list_tasks
from ..runtime_service import RUNTIME
from ..schemas import ModuleInstallRequest
from ..system_monitor import snapshot as system_snapshot
from ..task_service import TASKS
from .errors import translate_error

router = APIRouter(prefix="/api/v2", tags=["modules"])

@router.get("/modules")
def modules(): return MODULE_SERVICE.list()

@router.post("/modules/{module_id}/detect")
def module_detect(module_id: str):
    try: return MODULE_SERVICE.detect(module_id)
    except Exception as exc: raise translate_error(exc) from exc

@router.post("/modules/{module_id}/install")
def module_install(module_id: str, request: ModuleInstallRequest):
    try: return MODULE_SERVICE.install(module_id, request.confirm)
    except Exception as exc: raise translate_error(exc) from exc

@router.post("/modules/{module_id}/repair")
def module_repair(module_id: str, request: ModuleInstallRequest):
    try: return MODULE_SERVICE.install(module_id, request.confirm)
    except Exception as exc: raise translate_error(exc) from exc

@router.get("/runtime")
def runtime(): return RUNTIME.describe()

@router.post("/runtime/release")
def runtime_release():
    if any(task["status"] == "running" for project in list_projects() for task in list_tasks(project["id"])):
        raise HTTPException(status_code=409, detail="当前有任务正在运行，无法释放模型。")
    return TASKS.release_runtime()

@router.get("/system/metrics")
def system_metrics(): return system_snapshot()
