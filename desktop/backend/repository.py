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
from .schemas import VoicePatch, WorkspaceDraft


_PROJECT_WRITE_LOCK = threading.RLock()
_INDEX_LOCK = threading.RLock()
_INDEX_STATE: dict[str, Any] = {"status": "idle", "indexed": 0, "error": None, "mode": None}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_project_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value.strip())
    return re.sub(r"\s+", " ", value).strip(" ._")[:80] or "未命名配音项目"


def _project_file(project_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", project_id or ""):
        raise ValueError("项目编号无效。")
    return PROJECTS_DIR / project_id / "project.json"


def _read_project(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
    for path in PROJECTS_DIR.glob("*/project.json"):
        try:
            payload = _read_project(path)
            workspace = payload.get("workspace", {})
            voice_id = workspace.get("voice_id") or workspace.get("reference_id")
            records.append((
                payload["id"], payload["name"], str(path), payload["created_at"], payload["updated_at"],
                int(payload.get("revision", 1)), int(bool(payload.get("session_active"))),
                int(bool(payload.get("recovery_available"))), voice_id,
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
    output_directory = project_root / "outputs"
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = now()
    payload = {
        "schema_version": 2,
        "id": project_id,
        "name": _safe_project_name(name),
        "created_at": timestamp,
        "updated_at": timestamp,
        "revision": 1,
        "session_active": True,
        "recovery_available": False,
        "workspace": default_workspace(language, output_directory),
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
        "status": "检测到可恢复进度" if row["recovery_available"] else "已自动保存",
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
    return {
        **payload,
        "output_count": int(count_row["count"] if count_row else 0),
        "voice": _project_voice_name(payload.get("workspace", {})),
        "status": "检测到可恢复进度" if payload.get("recovery_available") else "已自动保存",
        "history": list_outputs(payload["id"]),
    }


def _project_voice_name(workspace: dict[str, Any]) -> str:
    asset_id = workspace.get("voice_id") or workspace.get("reference_id")
    if not asset_id:
        return "未选择"
    row = DB.one("SELECT name FROM voices WHERE id=?", (asset_id,))
    return str(row["name"]) if row else "未选择"


def save_project(project_id: str, revision: int, workspace: WorkspaceDraft) -> dict[str, Any]:
    path = _project_file(project_id)
    with _PROJECT_WRITE_LOCK:
        payload = _read_project(path)
        current_revision = int(payload.get("revision", 0))
        payload["workspace"] = workspace.model_dump(mode="json")
        payload["revision"] = max(current_revision + 1, revision + 1)
        payload["updated_at"] = now()
        payload["session_active"] = True
        payload["recovery_available"] = False
        _write_atomic(path, payload)
        workspace_payload = payload["workspace"]
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
            "INSERT INTO tasks(id,project_id,status,progress,message,payload_json,result_id,error,cancel_requested,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (task["id"], task["project_id"], task["status"], task["progress"], task["message"], json.dumps(task["payload"], ensure_ascii=False), None, None, 0, task["created_at"], task["updated_at"]),
        )


def _task_from_row(row) -> dict[str, Any]:
    return {key: row[key] for key in ("id", "project_id", "status", "progress", "message", "result_id", "error", "created_at", "updated_at")}


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


def list_tasks(project_id: str) -> list[dict[str, Any]]:
    return [_task_from_row(row) for row in DB.query("SELECT * FROM tasks WHERE project_id=? ORDER BY created_at DESC", (project_id,))]


def update_task(task_id: str, **changes: Any) -> dict[str, Any]:
    allowed = {"status", "progress", "message", "result_id", "error", "cancel_requested"}
    updates = {key: value for key, value in changes.items() if key in allowed}
    updates["updated_at"] = now()
    columns = ",".join(f"{key}=?" for key in updates)
    with DB.transaction() as connection:
        connection.execute(f"UPDATE tasks SET {columns} WHERE id=?", (*updates.values(), task_id))
    return get_task(task_id)


def cancel_requested(task_id: str) -> bool:
    row = DB.one("SELECT cancel_requested FROM tasks WHERE id=?", (task_id,))
    return bool(row and row["cancel_requested"])


def clear_finished_tasks(project_id: str) -> None:
    with DB.transaction() as connection:
        connection.execute("DELETE FROM tasks WHERE project_id=? AND status NOT IN ('queued','running')", (project_id,))


def add_output(project_id: str, task_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    output_id = uuid.uuid4().hex
    record = {**metadata, "id": output_id, "project_id": project_id, "task_id": task_id, "artifact_url": f"/api/v2/artifacts/{output_id}"}
    with DB.transaction() as connection:
        connection.execute("INSERT INTO outputs(id,project_id,task_id,path,filename,created_at,metadata_json) VALUES(?,?,?,?,?,?,?)", (output_id, project_id, task_id, metadata["path"], metadata["filename"], metadata["created_at"], json.dumps(record, ensure_ascii=False)))
    return record


def list_outputs(project_id: str) -> list[dict[str, Any]]:
    records = []
    for row in DB.query("SELECT * FROM outputs WHERE project_id=? ORDER BY created_at DESC", (project_id,)):
        record = json.loads(row["metadata_json"])
        record.pop("path", None)
        record["artifact_url"] = f"/api/v2/artifacts/{row['id']}"
        records.append(record)
    return records


def clear_outputs(project_id: str, delete_files: bool) -> None:
    rows = DB.query("SELECT path FROM outputs WHERE project_id=?", (project_id,))
    with DB.transaction() as connection:
        connection.execute("DELETE FROM outputs WHERE project_id=?", (project_id,))
    if delete_files:
        for row in rows:
            path = Path(row["path"])
            path.unlink(missing_ok=True)
            path.with_suffix(path.suffix + ".json").unlink(missing_ok=True)


def artifact(asset_id: str) -> tuple[Path, str]:
    row = DB.one("SELECT path,name FROM voices WHERE id=?", (asset_id,))
    if row:
        path = Path(row["path"])
        return path, path.name
    row = DB.one("SELECT path,filename FROM outputs WHERE id=?", (asset_id,))
    if row:
        return Path(row["path"]), row["filename"]
    raise FileNotFoundError("文件资源不存在。")
