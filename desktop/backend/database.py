from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .defaults import BUILT_IN_STYLES
from .paths import APP_DB


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL,
    session_active INTEGER NOT NULL DEFAULT 0,
    recovery_available INTEGER NOT NULL DEFAULT 0,
    voice_id TEXT
);
CREATE TABLE IF NOT EXISTS voices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    saved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    health_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS styles (
    name TEXT PRIMARY KEY,
    instruction TEXT NOT NULL,
    built_in INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    module TEXT NOT NULL DEFAULT 'speech',
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_id TEXT,
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    remove_after_stop INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outputs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    module TEXT NOT NULL DEFAULT 'speech',
    kind TEXT NOT NULL DEFAULT 'speech_output',
    task_id TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS output_roots (
    project_id TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, path)
);
CREATE INDEX IF NOT EXISTS idx_tasks_project_created ON tasks(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_outputs_project_created ON outputs(project_id, created_at DESC);
"""


class Database:
    def __init__(self, path: Path = APP_DB) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.connection: sqlite3.Connection | None = None
        self.initialized = False
        self.recovered = False
        self.created = False
        self.schema_changed = False
        self.last_error = ""

    def initialize(self) -> dict[str, object]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            self.created = not self.path.exists()
            self.recovered = False
            self.schema_changed = False
            self.last_error = ""
            try:
                self.connection = self._connect()
                self.connection.executescript(SCHEMA)
                self.schema_changed = self._migrate()
                self._seed_styles()
                self.connection.execute("UPDATE tasks SET status='interrupted', message='应用上次退出时任务未完成', updated_at=? WHERE status IN ('queued','running')", (datetime.now().isoformat(timespec="seconds"),))
                self.connection.execute("DELETE FROM tasks WHERE remove_after_stop=1 AND status NOT IN ('queued','running')")
                self.connection.commit()
            except sqlite3.DatabaseError as exc:
                self.last_error = str(exc)
                if self.connection is not None:
                    self.connection.close()
                self.connection = None
                self._preserve_corrupt_database()
                self.connection = self._connect()
                self.connection.executescript(SCHEMA)
                self.schema_changed = self._migrate()
                self._seed_styles()
                self.connection.commit()
                self.created = True
                self.recovered = True
            self.initialized = True
            return self.health()

    def _migrate(self) -> bool:
        assert self.connection is not None
        project_columns = {str(row["name"]) for row in self.connection.execute("PRAGMA table_info(projects)").fetchall()}
        task_columns = {str(row["name"]) for row in self.connection.execute("PRAGMA table_info(tasks)").fetchall()}
        output_columns = {str(row["name"]) for row in self.connection.execute("PRAGMA table_info(outputs)").fetchall()}
        changed = False
        if "voice_id" not in project_columns:
            self.connection.execute("ALTER TABLE projects ADD COLUMN voice_id TEXT")
            changed = True
        if "remove_after_stop" not in task_columns:
            self.connection.execute("ALTER TABLE tasks ADD COLUMN remove_after_stop INTEGER NOT NULL DEFAULT 0")
            changed = True
        if "module" not in task_columns:
            self.connection.execute("ALTER TABLE tasks ADD COLUMN module TEXT NOT NULL DEFAULT 'speech'")
            changed = True
        if "module" not in output_columns:
            self.connection.execute("ALTER TABLE outputs ADD COLUMN module TEXT NOT NULL DEFAULT 'speech'")
            changed = True
        if "kind" not in output_columns:
            self.connection.execute("ALTER TABLE outputs ADD COLUMN kind TEXT NOT NULL DEFAULT 'speech_output'")
            changed = True
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_module_created ON tasks(project_id, module, created_at DESC)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_outputs_project_module_created ON outputs(project_id, module, created_at DESC)")
        return changed

    def _preserve_corrupt_database(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(self.path) + suffix)
            if not source.exists():
                continue
            target = self.path.with_name(f"app.corrupt-{stamp}{suffix}.db")
            os.replace(source, target)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=NORMAL")
            return connection
        except Exception:
            connection.close()
            raise

    def _seed_styles(self) -> None:
        assert self.connection is not None
        now = datetime.now().isoformat(timespec="seconds")
        for name, instruction in BUILT_IN_STYLES:
            self.connection.execute(
                "INSERT INTO styles(name,instruction,built_in,updated_at) VALUES(?,?,1,?) ON CONFLICT(name) DO UPDATE SET instruction=excluded.instruction,built_in=1",
                (name, instruction, now),
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            if self.connection is None:
                raise RuntimeError("数据库尚未初始化。")
            try:
                yield self.connection
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def query(self, sql: str, parameters: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            if self.connection is None:
                raise RuntimeError("数据库尚未初始化。")
            return list(self.connection.execute(sql, parameters).fetchall())

    def one(self, sql: str, parameters: tuple = ()) -> sqlite3.Row | None:
        rows = self.query(sql, parameters)
        return rows[0] if rows else None

    def health(self) -> dict[str, object]:
        return {
            "status": "ready" if self.initialized else "starting",
            "created": self.created,
            "recovered": self.recovered,
            "schema_changed": self.schema_changed,
            "error": self.last_error or None,
        }

    def close(self) -> None:
        with self.lock:
            if self.connection is not None:
                self.connection.close()
                self.connection = None
            self.initialized = False


DB = Database()
