from __future__ import annotations

import os
from fastapi import APIRouter, Query
from ..events import EVENTS
from ..repository import clear_outputs, clear_project_activity, close_project, confirm_project_recovery, create_project, delete_project, get_project, list_outputs, list_projects, project_output_directory, save_project
from ..schemas import ProjectCreate, ProjectPatch
from .errors import translate_error

router = APIRouter(prefix="/api/v2/projects", tags=["projects"])

@router.get("")
def projects(): return list_projects()

@router.post("")
def project_create(request: ProjectCreate):
    try: return create_project(request.name, request.language)
    except Exception as exc: raise translate_error(exc) from exc

@router.get("/{project_id}")
def project_get(project_id: str, begin_session: bool = True):
    try: return get_project(project_id, begin_session)
    except Exception as exc: raise translate_error(exc) from exc

@router.patch("/{project_id}")
def project_patch(project_id: str, request: ProjectPatch):
    try:
        result = save_project(project_id, request.revision, request.workspace, request.module)
        EVENTS.publish("project.saved", {"id": project_id, "revision": result["revision"]})
        return result
    except Exception as exc: raise translate_error(exc) from exc

@router.post("/{project_id}/close", status_code=204)
def project_close(project_id: str):
    try: close_project(project_id)
    except Exception as exc: raise translate_error(exc) from exc

@router.post("/{project_id}/recovery/confirm")
def project_recovery_confirm(project_id: str):
    try: return confirm_project_recovery(project_id)
    except Exception as exc: raise translate_error(exc) from exc

@router.delete("/{project_id}", status_code=204)
def project_remove(project_id: str):
    try: delete_project(project_id)
    except Exception as exc: raise translate_error(exc) from exc

@router.get("/{project_id}/history")
def project_history(project_id: str, module: str | None = Query(default=None)): return list_outputs(project_id, module)

@router.delete("/{project_id}/history", status_code=204)
def project_history_clear(project_id: str, delete_files: bool = False, module: str | None = Query(default=None)):
    try: clear_outputs(project_id, delete_files, module)
    except Exception as exc: raise translate_error(exc) from exc

@router.delete("/{project_id}/activity")
def project_activity_clear(project_id: str, delete_files: bool = False, module: str | None = Query(default=None)):
    try:
        result = clear_project_activity(project_id, delete_files, module)
        EVENTS.publish("activity.cleared", {"project_id": project_id, "module": module, **result})
        return result
    except Exception as exc: raise translate_error(exc) from exc

@router.post("/{project_id}/outputs/{module}/open", status_code=204)
def project_output_open(project_id: str, module: str):
    try: get_project(project_id); os.startfile(str(project_output_directory(project_id, module, create=True)))
    except Exception as exc: raise translate_error(exc) from exc
