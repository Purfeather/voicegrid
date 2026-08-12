from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .audio import analyze_audio, internal_audio_path, save_upload
from .database import DB
from .defaults import default_workspace
from .paths import PROJECTS_DIR, UPLOADS_DIR, VOICES_DIR
from .schemas import ProjectWorkspaces, SoundEffectDraft, SoundEffectOutputPatch, VoiceDesignDraft, VoicePatch, WorkspaceDraft


_PROJECT_WRITE_LOCK = threading.RLock()
_INDEX_LOCK = threading.RLock()
_INDEX_STATE: dict[str, Any] = {"status": "idle", "indexed": 0, "error": None, "mode": None}
_OUTPUT_SUFFIXES = {".wav", ".flac"}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_project_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value.strip())
    return re.sub(r"\s+", " ", value).strip(" ._")[:80] or "未命名配音项目"


def _project_file(project_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", project_id or ""):
        raise ValueError("项目编号无效。")
    return PROJECTS_DIR / project_id / "project.json"


def _is_within(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    resolved_root = root.resolve()
    return resolved != resolved_root and resolved_root in resolved.parents


_MODULE_OUTPUT_DIRECTORIES: dict[str, str] = {
    "speech": "speech",
    "voice_design": "voice-design",
    "sound_effect": "sound-effects",
}


def project_output_directory(project_id: str, module: str, create: bool = False) -> Path:
    _project_file(project_id)
    directory_name = _MODULE_OUTPUT_DIRECTORIES.get(module)
    if directory_name is None:
        raise ValueError("模块编号无效。")
    directory = (PROJECTS_DIR / project_id / "outputs" / directory_name).resolve()
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def _rebuildable_output_path(project_id: str, module: str, value: str) -> Path | None:
    try:
        candidate = Path(value).resolve()
        if candidate.suffix.lower() not in _OUTPUT_SUFFIXES or not candidate.is_file():
            return None
        if module not in _MODULE_OUTPUT_DIRECTORIES:
            return None
        output_root = project_output_directory(project_id, module)
        if not _is_within(candidate, output_root):
            return None
        return candidate
    except (OSError, RuntimeError, ValueError):
        return None


def _deletable_output_path(project_id: str, value: str) -> Path | None:
    try:
        candidate = Path(value).resolve()
        if candidate.suffix.lower() not in _OUTPUT_SUFFIXES or not candidate.is_file():
            return None
        project_output_root = (PROJECTS_DIR / project_id / "outputs").resolve()
        return candidate if _is_within(candidate, project_output_root) else None
    except (OSError, RuntimeError, ValueError):
        return None


def _read_project(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    legacy_workspace = payload.pop("workspace", None)
    workspaces = dict(payload.get("workspaces") or {})
    if isinstance(legacy_workspace, dict) and "speech" not in workspaces:
        workspaces["speech"] = legacy_workspace
    payload["workspaces"] = ProjectWorkspaces.model_validate(workspaces).model_dump(mode="json")
    payload["schema_version"] = max(4, int(payload.get("schema_version", 3)))
    return payload


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    with _PROJECT_WRITE_LOCK:
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=f"{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
                temporary = Path(stream.name)
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _set_index_state(**changes: Any) -> None:
    with _INDEX_LOCK:
        _INDEX_STATE.update(changes)


def project_index_status() -> dict[str, Any]:
    with _INDEX_LOCK:
        return dict(_INDEX_STATE)


def project_index_count() -> int:
    row = DB.one("SELECT COUNT(*) AS count FROM projects")
    return int(row["count"] if row else 0)


def project_files_exist() -> bool:
    return next(PROJECTS_DIR.glob("*/project.json"), None) is not None


def mark_project_index_ready() -> None:
    _set_index_state(status="ready", indexed=project_index_count(), error=None, mode="sqlite")


def rebuild_project_index(mode: str = "rebuild") -> int:
    _set_index_state(status="running", indexed=0, error=None, mode=mode)
    records: list[tuple[Any, ...]] = []
    output_records: list[tuple[Any, ...]] = []
    for path in PROJECTS_DIR.glob("*/project.json"):
        try:
            payload = _read_project(path)
            if payload.get("id") != path.parent.name or not re.fullmatch(r"[0-9a-f]{32}", str(payload.get("id") or "")):
                continue
            workspace = payload.get("workspaces", {}).get("speech", {})
            voice_id = workspace.get("voice_id") or workspace.get("reference_id")
            records.append((
                payload["id"], payload["name"], str(path), payload["created_at"], payload["updated_at"],
                int(payload.get("revision", 1)), int(bool(payload.get("session_active"))),
                int(bool(payload.get("recovery_available"))), voice_id,
            ))
            for output_id, output in (payload.get("output_snapshots") or {}).items():
                output_path = str(output.get("path") or "")
                module = str(output.get("module") or "speech")
                trusted_path = _rebuildable_output_path(payload["id"], module, output_path)
                if trusted_path is None:
                    continue
                record = {**output, "id": output_id, "project_id": payload["id"], "path": str(trusted_path)}
                output_records.append((
                    output_id,
                    payload["id"],
                    module,
                    str(record.get("kind") or "speech_output"),
                    str(record.get("task_id") or "recovered"),
                    str(trusted_path),
                    str(record.get("filename") or trusted_path.name),
                    str(record.get("created_at") or payload["updated_at"]),
                    json.dumps(record, ensure_ascii=False),
                ))
        except Exception:
            continue
    try:
        if records:
            with DB.transaction() as connection:
                connection.executemany(
                    """INSERT INTO projects(id,name,path,created_at,updated_at,revision,session_active,recovery_available,voice_id)
                    VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,path=excluded.path,created_at=excluded.created_at,updated_at=excluded.updated_at,
                    revision=excluded.revision,session_active=excluded.session_active,
                    recovery_available=excluded.recovery_available,voice_id=excluded.voice_id""",
                    records,
                )
                if output_records:
                    connection.executemany(
                        """INSERT INTO outputs(id,project_id,module,kind,task_id,path,filename,created_at,metadata_json)
                        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                        project_id=excluded.project_id,module=excluded.module,kind=excluded.kind,task_id=excluded.task_id,path=excluded.path,
                        filename=excluded.filename,created_at=excluded.created_at,metadata_json=excluded.metadata_json""",
                        output_records,
                    )
        _set_index_state(status="ready", indexed=len(records), error=None, mode=mode)
        return len(records)
    except Exception as exc:
        _set_index_state(status="error", indexed=0, error=str(exc), mode=mode)
        raise


def reconcile_project_index() -> int:
    return rebuild_project_index(mode="reconcile")


def create_project(name: str, language: str) -> dict[str, Any]:
    project_id = uuid.uuid4().hex
    project_root = PROJECTS_DIR / project_id
    for module in _MODULE_OUTPUT_DIRECTORIES:
        project_output_directory(project_id, module, create=True)
    timestamp = now()
    payload = {
        "schema_version": 4,
        "id": project_id,
        "name": _safe_project_name(name),
        "created_at": timestamp,
        "updated_at": timestamp,
        "revision": 1,
        "session_active": True,
        "recovery_available": False,
        "workspaces": ProjectWorkspaces(
            speech=WorkspaceDraft.model_validate(default_workspace(language)),
        ).model_dump(mode="json"),
        "output_snapshots": {},
    }
    path = project_root / "project.json"
    _write_atomic(path, payload)
    with DB.transaction() as connection:
        connection.execute(
            "INSERT INTO projects(id,name,path,created_at,updated_at,revision,session_active,recovery_available,voice_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (project_id, payload["name"], str(path), timestamp, timestamp, 1, 1, 0, None),
        )
    return project_detail(payload)


def list_projects() -> list[dict[str, Any]]:
    rows = DB.query(
        """SELECT p.id,p.name,p.updated_at,p.recovery_available,
        COALESCE(output_totals.output_count,0) AS output_count,
        COALESCE(v.name,'未选择') AS voice
        FROM projects AS p
        LEFT JOIN (SELECT project_id,COUNT(*) AS output_count FROM outputs GROUP BY project_id) AS output_totals
          ON output_totals.project_id=p.id
        LEFT JOIN voices AS v ON v.id=p.voice_id
        ORDER BY p.updated_at DESC"""
    )
    return [{
        "id": row["id"],
        "name": row["name"],
        "updated_at": row["updated_at"],
        "recovery_available": bool(row["recovery_available"]),
        "output_count": int(row["output_count"]),
        "voice": row["voice"],
        "status": "已保留上次编辑进度" if row["recovery_available"] else "已自动保存",
    } for row in rows]


def get_project(project_id: str, begin_session: bool = False) -> dict[str, Any]:
    path = _project_file(project_id)
    if not path.exists():
        raise FileNotFoundError("找不到项目。")
    with _PROJECT_WRITE_LOCK:
        payload = _read_project(path)
        if begin_session:
            payload["session_active"] = True
            payload["recovery_available"] = False
            payload["updated_at"] = now()
            _write_atomic(path, payload)
            with DB.transaction() as connection:
                connection.execute("UPDATE projects SET session_active=1,recovery_available=0,updated_at=? WHERE id=?", (payload["updated_at"], project_id))
    return project_detail(payload)


def project_detail(payload: dict[str, Any]) -> dict[str, Any]:
    count_row = DB.one("SELECT COUNT(*) AS count FROM outputs WHERE project_id=?", (payload["id"],))
    speech_workspace = payload.get("workspaces", {}).get("speech", {})
    return {
        **payload,
        "workspace": speech_workspace,
        "output_count": int(count_row["count"] if count_row else 0),
        "voice": _project_voice_name(payload.get("workspaces", {}).get("speech", {})),
        "status": "已保留上次编辑进度" if payload.get("recovery_available") else "已自动保存",
        "history": list_outputs(payload["id"], "speech"),
    }


def _project_voice_name(workspace: dict[str, Any]) -> str:
    asset_id = workspace.get("voice_id") or workspace.get("reference_id")
    if not asset_id:
        return "未选择"
    row = DB.one("SELECT name FROM voices WHERE id=?", (asset_id,))
    return str(row["name"]) if row else "未选择"


def save_project(
    project_id: str,
    revision: int,
    workspace: WorkspaceDraft | VoiceDesignDraft | SoundEffectDraft,
    module: str = "speech",
) -> dict[str, Any]:
    path = _project_file(project_id)
    with _PROJECT_WRITE_LOCK:
        payload = _read_project(path)
        current_revision = int(payload.get("revision", 0))
        payload.setdefault("workspaces", {})[module] = workspace.model_dump(mode="json")
        payload["revision"] = max(current_revision + 1, revision + 1)
        payload["updated_at"] = now()
        payload["session_active"] = True
        payload["recovery_available"] = False
        _write_atomic(path, payload)
        workspace_payload = payload["workspaces"]["speech"]
        voice_id = workspace_payload.get("voice_id") or workspace_payload.get("reference_id")
        with DB.transaction() as connection:
            connection.execute("UPDATE projects SET updated_at=?,revision=?,session_active=1,recovery_available=0,voice_id=? WHERE id=?", (payload["updated_at"], payload["revision"], voice_id, project_id))
    return project_detail(payload)


def close_project(project_id: str) -> None:
    path = _project_file(project_id)
    with _PROJECT_WRITE_LOCK:
        payload = _read_project(path)
        payload["session_active"] = False
        payload["recovery_available"] = False
        payload["updated_at"] = now()
        _write_atomic(path, payload)
        with DB.transaction() as connection:
            connection.execute("UPDATE projects SET session_active=0,recovery_available=0,updated_at=? WHERE id=?", (payload["updated_at"], project_id))


def delete_project(project_id: str) -> None:
    project_file = _project_file(project_id)
    row = DB.one("SELECT id FROM projects WHERE id=?", (project_id,))
    if row is None or not project_file.exists():
        raise FileNotFoundError("找不到项目。")
    active = DB.one(
        "SELECT id FROM tasks WHERE project_id=? AND status IN ('queued','running') LIMIT 1",
        (project_id,),
    )
    if active is not None:
        raise ValueError("项目仍有排队或生成中的任务，请先停止任务。")
    project_root = project_file.parent
    with _PROJECT_WRITE_LOCK:
        with DB.transaction() as connection:
            connection.execute("DELETE FROM outputs WHERE project_id=?", (project_id,))
            connection.execute("DELETE FROM tasks WHERE project_id=?", (project_id,))
            connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
        shutil.rmtree(project_root)
    _set_index_state(indexed=project_index_count())


def mark_interrupted_projects() -> None:
    for row in DB.query("SELECT id,path FROM projects WHERE session_active=1"):
        try:
            path = Path(row["path"])
            with _PROJECT_WRITE_LOCK:
                payload = _read_project(path)
                payload["session_active"] = False
                payload["recovery_available"] = True
                _write_atomic(path, payload)
        except Exception:
            continue
    with DB.transaction() as connection:
        connection.execute("UPDATE projects SET session_active=0,recovery_available=1 WHERE session_active=1")


def add_upload(filename: str, content: bytes) -> dict[str, Any]:
    path = save_upload(filename, content)
    try:
        health = analyze_audio(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    asset_id = uuid.uuid4().hex
    timestamp = now()
    name = Path(filename).stem[:80] or "临时参考音频"
    with DB.transaction() as connection:
        connection.execute(
            "INSERT INTO voices(id,name,path,saved,created_at,metadata_json,health_json) VALUES(?,?,?,?,?,?,?)",
            (asset_id, name, str(path), 0, timestamp, "{}", json.dumps(health, ensure_ascii=False)),
        )
    return get_voice(asset_id)


def _voice_from_row(row) -> dict[str, Any]:
    metadata = json.loads(row["metadata_json"] or "{}")
    return {
        "id": row["id"], "name": row["name"], "saved": bool(row["saved"]), "created_at": row["created_at"],
        "artifact_url": f"/api/v2/artifacts/{row['id']}", "health": json.loads(row["health_json"]), **metadata,
    }


def list_voices() -> list[dict[str, Any]]:
    return [_voice_from_row(row) for row in DB.query("SELECT * FROM voices ORDER BY saved DESC, created_at DESC")]


def get_voice(asset_id: str) -> dict[str, Any]:
    row = DB.one("SELECT * FROM voices WHERE id=?", (asset_id,))
    if row is None:
        raise FileNotFoundError("音色资产不存在。")
    return _voice_from_row(row)


def voice_path(asset_id: str) -> Path:
    row = DB.one("SELECT path FROM voices WHERE id=?", (asset_id,))
    if row is None:
        raise FileNotFoundError("音色资产不存在。")
    return internal_audio_path(row["path"])


def update_voice(asset_id: str, patch: VoicePatch) -> dict[str, Any]:
    row = DB.one("SELECT * FROM voices WHERE id=?", (asset_id,))
    if row is None:
        raise FileNotFoundError("音色资产不存在。")
    name = patch.name or row["name"]
    path = Path(row["path"])
    saved = bool(row["saved"] if patch.saved is None else patch.saved)
    if saved and not row["saved"]:
        target = VOICES_DIR / f"{asset_id}{path.suffix.lower()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        path = target
    metadata = json.loads(row["metadata_json"] or "{}")
    for field in ("role", "language_accent", "gender_age", "description"):
        value = getattr(patch, field)
        if value is not None:
            metadata[field] = value
    with DB.transaction() as connection:
        connection.execute("UPDATE voices SET name=?,path=?,saved=?,metadata_json=? WHERE id=?", (name, str(path), int(saved), json.dumps(metadata, ensure_ascii=False), asset_id))
    return get_voice(asset_id)


def save_output_as_voice(output_id: str, name: str) -> dict[str, Any]:
    row = DB.one("SELECT * FROM outputs WHERE id=?", (output_id,))
    if row is None:
        raise FileNotFoundError("音色设计输出不存在。")
    if row["module"] != "voice_design":
        raise ValueError("只有音色设计结果可以保存到共享音色库。")
    source = internal_audio_path(row["path"])
    asset_id = uuid.uuid4().hex
    target = VOICES_DIR / f"{asset_id}{source.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    try:
        health = analyze_audio(target)
        record = json.loads(row["metadata_json"] or "{}")
        snapshot = dict(record.get("generation_snapshot") or {})
        metadata = {
            "role": "设计音色",
            "language_accent": str(snapshot.get("composer", {}).get("accent_language") or ""),
            "gender_age": str(snapshot.get("composer", {}).get("age_gender") or ""),
            "description": str(record.get("instruction") or "")[:500],
            "source_output_id": output_id,
        }
        timestamp = now()
        with DB.transaction() as connection:
            connection.execute(
                "INSERT INTO voices(id,name,path,saved,created_at,metadata_json,health_json) VALUES(?,?,?,?,?,?,?)",
                (
                    asset_id,
                    _safe_project_name(name),
                    str(target),
                    1,
                    timestamp,
                    json.dumps(metadata, ensure_ascii=False),
                    json.dumps(health, ensure_ascii=False),
                ),
            )
        return get_voice(asset_id)
    except Exception:
        target.unlink(missing_ok=True)
        raise


def delete_voice(asset_id: str, delete_file: bool) -> None:
    row = DB.one("SELECT path FROM voices WHERE id=?", (asset_id,))
    if row is None:
        raise FileNotFoundError("音色资产不存在。")
    path = internal_audio_path(row["path"]) if delete_file else None
    with DB.transaction() as connection:
        connection.execute("DELETE FROM voices WHERE id=?", (asset_id,))
    if path is not None:
        path.unlink(missing_ok=True)


def list_styles() -> list[dict[str, Any]]:
    return [{"name": row["name"], "instruction": row["instruction"], "built_in": bool(row["built_in"]), "updated_at": row["updated_at"]} for row in DB.query("SELECT * FROM styles ORDER BY built_in DESC, name")]


def save_style(name: str, instruction: str) -> dict[str, Any]:
    existing = DB.one("SELECT built_in FROM styles WHERE name=?", (name,))
    if existing and existing["built_in"]:
        raise PermissionError("无法覆盖初始预设。")
    timestamp = now()
    with DB.transaction() as connection:
        connection.execute("INSERT INTO styles(name,instruction,built_in,updated_at) VALUES(?,?,0,?) ON CONFLICT(name) DO UPDATE SET instruction=excluded.instruction,updated_at=excluded.updated_at", (name, instruction, timestamp))
    return {"name": name, "instruction": instruction, "built_in": False, "updated_at": timestamp}


def delete_style(name: str) -> None:
    row = DB.one("SELECT built_in FROM styles WHERE name=?", (name,))
    if row is None:
        raise FileNotFoundError("风格预设不存在。")
    if row["built_in"]:
        raise PermissionError("无法删除初始预设。")
    with DB.transaction() as connection:
        connection.execute("DELETE FROM styles WHERE name=?", (name,))


def insert_task(task: dict[str, Any]) -> None:
    with DB.transaction() as connection:
        connection.execute(
            "INSERT INTO tasks(id,project_id,module,status,progress,message,payload_json,result_id,error,cancel_requested,remove_after_stop,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task["id"], task["project_id"], task.get("module", "speech"), task["status"], task["progress"], task["message"], json.dumps(task["payload"], ensure_ascii=False), None, None, 0, 0, task["created_at"], task["updated_at"]),
        )


def _task_from_row(row) -> dict[str, Any]:
    task = {key: row[key] for key in ("id", "project_id", "module", "status", "progress", "message", "result_id", "error", "created_at", "updated_at")}
    task["remove_after_stop"] = bool(row["remove_after_stop"])
    return task


def get_task(task_id: str) -> dict[str, Any]:
    row = DB.one("SELECT * FROM tasks WHERE id=?", (task_id,))
    if row is None:
        raise FileNotFoundError("任务不存在。")
    return _task_from_row(row)


def task_payload(task_id: str) -> dict[str, Any]:
    row = DB.one("SELECT payload_json FROM tasks WHERE id=?", (task_id,))
    if row is None:
        raise FileNotFoundError("任务不存在。")
    return json.loads(row["payload_json"])


def list_tasks(project_id: str, module: str | None = None) -> list[dict[str, Any]]:
    if module:
        rows = DB.query("SELECT * FROM tasks WHERE project_id=? AND module=? ORDER BY created_at DESC", (project_id, module))
    else:
        rows = DB.query("SELECT * FROM tasks WHERE project_id=? ORDER BY created_at DESC", (project_id,))
    return [_task_from_row(row) for row in rows]


def update_task(task_id: str, **changes: Any) -> dict[str, Any]:
    allowed = {"status", "progress", "message", "result_id", "error", "cancel_requested", "remove_after_stop"}
    updates = {key: value for key, value in changes.items() if key in allowed}
    updates["updated_at"] = now()
    columns = ",".join(f"{key}=?" for key in updates)
    with DB.transaction() as connection:
        connection.execute(f"UPDATE tasks SET {columns} WHERE id=?", (*updates.values(), task_id))
    return get_task(task_id)


def cancel_requested(task_id: str) -> bool:
    row = DB.one("SELECT cancel_requested FROM tasks WHERE id=?", (task_id,))
    return bool(row and row["cancel_requested"])


def clear_finished_tasks(project_id: str, module: str | None = None) -> None:
    with DB.transaction() as connection:
        if module:
            connection.execute(
                "DELETE FROM tasks WHERE project_id=? AND module=? AND status NOT IN ('queued','running')",
                (project_id, module),
            )
        else:
            connection.execute("DELETE FROM tasks WHERE project_id=? AND status NOT IN ('queued','running')", (project_id,))


def delete_task(task_id: str) -> None:
    task = get_task(task_id)
    if task["status"] in {"queued", "running"}:
        raise ValueError("任务仍在排队或运行，必须先安全停止。")
    with DB.transaction() as connection:
        connection.execute("DELETE FROM tasks WHERE id=?", (task_id,))


def clear_project_activity(project_id: str, delete_files: bool = False, module: str | None = None) -> dict[str, int]:
    get_project(project_id)
    if module:
        finished_tasks = DB.one(
            "SELECT COUNT(*) AS count FROM tasks WHERE project_id=? AND module=? AND status NOT IN ('queued','running')",
            (project_id, module),
        )
        outputs = DB.one("SELECT COUNT(*) AS count FROM outputs WHERE project_id=? AND module=?", (project_id, module))
    else:
        finished_tasks = DB.one(
            "SELECT COUNT(*) AS count FROM tasks WHERE project_id=? AND status NOT IN ('queued','running')",
            (project_id,),
        )
        outputs = DB.one("SELECT COUNT(*) AS count FROM outputs WHERE project_id=?", (project_id,))
    clear_outputs(project_id, delete_files, module)
    clear_finished_tasks(project_id, module)
    return {
        "tasks_removed": int(finished_tasks["count"] if finished_tasks else 0),
        "outputs_removed": int(outputs["count"] if outputs else 0),
    }


def add_output(project_id: str, task_id: str, metadata: dict[str, Any], module: str = "speech", kind: str = "speech_output") -> dict[str, Any]:
    output_path = Path(str(metadata["path"])).resolve()
    if output_path.suffix.lower() not in _OUTPUT_SUFFIXES or not output_path.is_file():
        raise ValueError("输出音频不存在或格式不受支持。")
    if _rebuildable_output_path(project_id, module, str(output_path)) is None:
        raise ValueError("模块输出不在当前项目的受控资源目录内。")
    output_id = uuid.uuid4().hex
    record = {**metadata, "path": str(output_path), "id": output_id, "project_id": project_id, "task_id": task_id, "module": module, "kind": kind, "artifact_url": f"/api/v2/artifacts/{output_id}"}
    path = _project_file(project_id)
    previous_payload: dict[str, Any] | None = None
    with _PROJECT_WRITE_LOCK:
        payload = _read_project(path)
        previous_payload = json.loads(json.dumps(payload, ensure_ascii=False))
        payload.setdefault("output_snapshots", {})[output_id] = {key: value for key, value in record.items() if key != "artifact_url"}
        payload["schema_version"] = max(4, int(payload.get("schema_version", 3)))
        payload["updated_at"] = now()
        _write_atomic(path, payload)
    try:
        with DB.transaction() as connection:
            connection.execute("INSERT INTO outputs(id,project_id,module,kind,task_id,path,filename,created_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)", (output_id, project_id, module, kind, task_id, str(output_path), metadata["filename"], metadata["created_at"], json.dumps(record, ensure_ascii=False)))
    except Exception:
        if previous_payload is not None:
            with _PROJECT_WRITE_LOCK:
                _write_atomic(path, previous_payload)
        raise
    return record


def list_outputs(project_id: str, module: str | None = None) -> list[dict[str, Any]]:
    records = []
    if module:
        rows = DB.query("SELECT * FROM outputs WHERE project_id=? AND module=? ORDER BY created_at DESC", (project_id, module))
    else:
        rows = DB.query("SELECT * FROM outputs WHERE project_id=? ORDER BY created_at DESC", (project_id,))
    for row in rows:
        record = json.loads(row["metadata_json"])
        record.pop("path", None)
        record["artifact_url"] = f"/api/v2/artifacts/{row['id']}"
        records.append(record)
    return records


def _rewrite_output_snapshot(project_id: str, output_id: str, record: dict[str, Any]) -> None:
    path = _project_file(project_id)
    with _PROJECT_WRITE_LOCK:
        payload = _read_project(path)
        snapshots = payload.setdefault("output_snapshots", {})
        if output_id not in snapshots:
            raise FileNotFoundError("项目输出快照不存在。")
        snapshots[output_id] = {key: value for key, value in record.items() if key != "artifact_url"}
        payload["updated_at"] = now()
        _write_atomic(path, payload)


def update_sound_effect_output(output_id: str, patch: SoundEffectOutputPatch) -> dict[str, Any]:
    row = DB.one("SELECT * FROM outputs WHERE id=? AND module='sound_effect'", (output_id,))
    if row is None:
        raise FileNotFoundError("音效资源不存在。")
    record = json.loads(row["metadata_json"])
    source_path = _rebuildable_output_path(str(row["project_id"]), "sound_effect", str(row["path"]))
    if source_path is None:
        raise ValueError("音效资源不在当前项目的受控目录内。")
    changes = patch.model_dump(exclude_unset=True)
    target_path = source_path
    if "name" in changes:
        stem = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", str(changes["name"] or "").strip())
        stem = re.sub(r"\s+", " ", stem).strip(" ._")[:120]
        if not stem:
            raise ValueError("音效名称不能为空。")
        target_path = source_path.with_name(f"{stem}{source_path.suffix.lower()}")
        if target_path != source_path and target_path.exists():
            raise FileExistsError("同名音效文件已存在。")
        if target_path != source_path:
            source_sidecar = source_path.with_suffix(source_path.suffix + ".json")
            target_sidecar = target_path.with_suffix(target_path.suffix + ".json")
            os.replace(source_path, target_path)
            if source_sidecar.exists():
                os.replace(source_sidecar, target_sidecar)
        record["filename"] = target_path.name
        record["path"] = str(target_path)
    if "favorite" in changes:
        record["favorite"] = bool(changes["favorite"])
    record["artifact_url"] = f"/api/v2/artifacts/{output_id}"
    try:
        _rewrite_output_snapshot(str(row["project_id"]), output_id, record)
        with DB.transaction() as connection:
            connection.execute(
                "UPDATE outputs SET path=?,filename=?,metadata_json=? WHERE id=?",
                (str(target_path), record["filename"], json.dumps(record, ensure_ascii=False), output_id),
            )
        sidecar = target_path.with_suffix(target_path.suffix + ".json")
        sidecar.write_text(json.dumps({key: value for key, value in record.items() if key != "artifact_url"}, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    except Exception:
        if target_path != source_path and target_path.exists() and not source_path.exists():
            os.replace(target_path, source_path)
            target_sidecar = target_path.with_suffix(target_path.suffix + ".json")
            source_sidecar = source_path.with_suffix(source_path.suffix + ".json")
            if target_sidecar.exists():
                os.replace(target_sidecar, source_sidecar)
        raise
    result = dict(record)
    result.pop("path", None)
    return result


def delete_sound_effect_output(output_id: str, delete_file: bool = True) -> str:
    row = DB.one("SELECT * FROM outputs WHERE id=? AND module='sound_effect'", (output_id,))
    if row is None:
        raise FileNotFoundError("音效资源不存在。")
    project_id = str(row["project_id"])
    path = _project_file(project_id)
    with _PROJECT_WRITE_LOCK:
        payload = _read_project(path)
        payload.setdefault("output_snapshots", {}).pop(output_id, None)
        payload["updated_at"] = now()
        _write_atomic(path, payload)
    with DB.transaction() as connection:
        connection.execute("DELETE FROM outputs WHERE id=?", (output_id,))
    if delete_file:
        trusted = _deletable_output_path(project_id, str(row["path"]))
        if trusted is not None:
            trusted.unlink(missing_ok=True)
            trusted.with_suffix(trusted.suffix + ".json").unlink(missing_ok=True)
    return project_id


def clear_outputs(project_id: str, delete_files: bool, module: str | None = None) -> None:
    rows = DB.query(
        "SELECT id,path FROM outputs WHERE project_id=?" + (" AND module=?" if module else ""),
        (project_id, module) if module else (project_id,),
    )
    path = _project_file(project_id)
    with _PROJECT_WRITE_LOCK:
        payload = _read_project(path)
        if module:
            removed_ids = {row["id"] for row in rows}
            payload["output_snapshots"] = {
                output_id: output
                for output_id, output in (payload.get("output_snapshots") or {}).items()
                if output_id not in removed_ids
            }
        else:
            payload["output_snapshots"] = {}
        payload["updated_at"] = now()
        _write_atomic(path, payload)
    with DB.transaction() as connection:
        if module:
            connection.execute("DELETE FROM outputs WHERE project_id=? AND module=?", (project_id, module))
        else:
            connection.execute("DELETE FROM outputs WHERE project_id=?", (project_id,))
    if delete_files:
        for row in rows:
            trusted_path = _deletable_output_path(project_id, str(row["path"]))
            if trusted_path is None:
                continue
            trusted_path.unlink(missing_ok=True)
            trusted_path.with_suffix(trusted_path.suffix + ".json").unlink(missing_ok=True)


def artifact(asset_id: str) -> tuple[Path, str]:
    row = DB.one("SELECT path,name FROM voices WHERE id=?", (asset_id,))
    if row:
        path = Path(row["path"])
        return path, path.name
    row = DB.one("SELECT path,filename FROM outputs WHERE id=?", (asset_id,))
    if row:
        path = Path(row["path"]).resolve()
        if path.suffix.lower() not in _OUTPUT_SUFFIXES:
            raise ValueError("输出资源格式无效。")
        return path, row["filename"]
    raise FileNotFoundError("文件资源不存在。")
