from __future__ import annotations

from fastapi import APIRouter, Query
from ..repository import clear_finished_tasks, get_task, list_tasks
from ..schemas import ModuleTaskCreate
from ..task_service import TASKS
from .errors import translate_error

router = APIRouter(prefix="/api/v2", tags=["tasks"])

@router.post("/module-tasks")
def module_task_create(request: ModuleTaskCreate):
    workspace = request.workspace.model_dump(mode="json")
    try:
        if request.module == "speech":
            if not workspace["text"].strip(): raise ValueError("请输入需要合成的文本。")
            return TASKS.create(request.project_id, workspace)
        if request.module == "voice_design":
            if not workspace["text"].strip(): raise ValueError("请输入试听台词。")
            if not workspace["instruction"].strip(): raise ValueError("请输入最终音色提示词。")
            return TASKS.create_voice_design(request.project_id, workspace)
        if request.module == "sound_effect":
            if not workspace["prompt"].strip(): raise ValueError("请输入需要生成的声音场景。")
            return TASKS.create_sound_effect(request.project_id, workspace)
        raise ValueError("未知的生成模块。")
    except Exception as exc: raise translate_error(exc) from exc

@router.get("/tasks")
def tasks(project_id: str = Query(...), module: str | None = Query(default=None)): return list_tasks(project_id, module)

@router.get("/tasks/{task_id}")
def task_get(task_id: str):
    try: return get_task(task_id)
    except Exception as exc: raise translate_error(exc) from exc

@router.post("/tasks/{task_id}/cancel")
def task_cancel(task_id: str):
    try: return TASKS.cancel(task_id)
    except Exception as exc: raise translate_error(exc) from exc

@router.delete("/tasks/{task_id}")
def task_remove(task_id: str):
    try: return TASKS.remove(task_id)
    except Exception as exc: raise translate_error(exc) from exc

@router.delete("/tasks", status_code=204)
def tasks_clear(project_id: str = Query(...), module: str | None = Query(default=None)): clear_finished_tasks(project_id, module)
