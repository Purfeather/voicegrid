from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop.backend import repository
from desktop.backend.database import DATABASE_SCHEMA_VERSION, Database


class StartupDataTests(unittest.TestCase):
    def test_new_database_uses_current_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "app.db")
            database.initialize()
            try:
                self.assertEqual(database.one("PRAGMA user_version")[0], DATABASE_SCHEMA_VERSION)
                self.assertEqual(database.health()["schema_version"], DATABASE_SCHEMA_VERSION)
            finally:
                database.close()

    def test_project_list_uses_one_batched_query_for_two_hundred_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            projects = root / "projects"
            projects.mkdir()
            timestamp = "2026-08-11T12:00:00"
            for index in range(200):
                project_id = f"{index + 1:032x}"
                folder = projects / project_id
                folder.mkdir()
                payload = {
                    "schema_version": 4,
                    "id": project_id,
                    "name": f"Project {index + 1}",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "revision": 1,
                    "session_active": False,
                    "recovery_available": False,
                    "workspaces": {},
                    "output_snapshots": {},
                }
                (folder / "project.json").write_text(json.dumps(payload), encoding="utf-8")
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", projects):
                    self.assertEqual(repository.rebuild_project_index(), 200)
                    with patch.object(database, "query", wraps=database.query) as query:
                        started = time.perf_counter()
                        result = repository.list_projects()
                        elapsed_ms = (time.perf_counter() - started) * 1000
                    self.assertEqual(len(result), 200)
                    self.assertEqual(query.call_count, 1)
                    self.assertLess(elapsed_ms, 500)
            finally:
                database.close()

    def test_corrupt_database_is_preserved_and_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "app.db"
            target.write_bytes(b"not-a-sqlite-database")
            database = Database(target)
            status = database.initialize()
            try:
                self.assertTrue(status["recovered"])
                self.assertTrue(target.is_file())
                self.assertTrue(list(root.glob("app.corrupt-*.db")))
            finally:
                database.close()

    def test_cached_database_health_is_well_below_api_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "app.db")
            database.initialize()
            try:
                started = time.perf_counter()
                for _ in range(1000):
                    database.health()
                average_ms = (time.perf_counter() - started) * 1000 / 1000
                self.assertLess(average_ms, 1)
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
