from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from app.model_engine import split_text
from desktop.backend import output_engineering, repository
from desktop.backend.database import Database
from desktop.backend.defaults import PARAMETER_PRESETS
from desktop.backend.schemas import WorkspaceDraft
from desktop.backend.task_service import build_generation_snapshot, duration_to_tokens


def sine(sample_rate: int, seconds: float) -> np.ndarray:
    timeline = np.arange(int(sample_rate * seconds), dtype=np.float32) / sample_rate
    return (.2 * np.sin(2 * np.pi * 220 * timeline)).astype(np.float32)


class RepositoryTests(unittest.TestCase):
    def test_project_is_atomic_and_recovery_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("验收项目", "Chinese")
                    workspace = WorkspaceDraft.model_validate(created["workspace"])
                    workspace.text = "粘贴后立即保存的新文本"
                    saved = repository.save_project(created["id"], created["revision"], workspace)
                    self.assertGreater(saved["revision"], created["revision"])
                    with database.transaction() as connection:
                        connection.execute("DELETE FROM projects WHERE id=?", (created["id"],))
                    repository.rebuild_project_index()
                    self.assertIsNotNone(database.one("SELECT id FROM projects WHERE id=?", (created["id"],)))
                    repository.mark_interrupted_projects()
                    summary = repository.list_projects()[0]
                    self.assertTrue(summary["recovery_available"])
                    reopened = repository.get_project(created["id"], begin_session=True)
                    self.assertFalse(reopened["recovery_available"])
                    self.assertEqual(reopened["workspace"]["text"], "粘贴后立即保存的新文本")
            finally:
                database.close()

    def test_project_delete_removes_index_tasks_and_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("待删除项目", "Chinese")
                    project_root = root / "projects" / created["id"]
                    with database.transaction() as connection:
                        connection.execute(
                            "INSERT INTO tasks(id,project_id,status,progress,message,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                            ("task-1", created["id"], "completed", 1, "完成", "{}", "2026-08-12T10:00:00", "2026-08-12T10:00:00"),
                        )
                    repository.delete_project(created["id"])
                    self.assertFalse(project_root.exists())
                    self.assertIsNone(database.one("SELECT id FROM projects WHERE id=?", (created["id"],)))
                    self.assertIsNone(database.one("SELECT id FROM tasks WHERE project_id=?", (created["id"],)))
            finally:
                database.close()

    def test_concurrent_autosave_and_open_leave_valid_project_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("并发保存验收", "Chinese")

                    def save(index: int) -> None:
                        workspace = WorkspaceDraft.model_validate(created["workspace"])
                        workspace.text = f"自动保存版本 {index}"
                        repository.save_project(created["id"], index, workspace)

                    def reopen(_: int) -> None:
                        repository.get_project(created["id"], begin_session=True)

                    with ThreadPoolExecutor(max_workers=8) as executor:
                        futures = [executor.submit(save if index % 2 else reopen, index) for index in range(24)]
                        for future in futures:
                            future.result()

                    project_file = root / "projects" / created["id"] / "project.json"
                    payload = json.loads(project_file.read_text(encoding="utf-8"))
                    self.assertEqual(payload["id"], created["id"])
                    self.assertFalse(list(project_file.parent.glob("*.tmp")))
            finally:
                database.close()

    def test_built_in_style_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database):
                    with self.assertRaises(PermissionError):
                        repository.delete_style("自然影视")
                    custom = repository.save_style("我的风格", "自然、克制、有呼吸感")
                    self.assertFalse(custom["built_in"])
                    repository.delete_style("我的风格")
            finally:
                database.close()


class AudioOutputTests(unittest.TestCase):
    def test_output_engineering_persists_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            source = raw_dir / "source.wav"
            sf.write(source, sine(24000, 1.0), 24000, subtype="PCM_24")
            profile = {"format": "WAV", "sample_rate": 48000, "bit_depth": 24, "channels": 1, "loudness_lufs": -23, "filename_template": "{project}_{index}", "output_directory": str(root / "outputs")}
            with patch.object(output_engineering, "RAW_OUTPUTS_DIR", raw_dir):
                metadata = output_engineering.render_output(str(source), profile, "工程测试", "音色A", 1)
            target = Path(metadata["path"])
            self.assertTrue(target.is_file())
            self.assertTrue(target.with_suffix(".wav.json").is_file())
            self.assertEqual(metadata["sample_rate"], 48000)


class ModelContractTests(unittest.TestCase):
    def test_duration_control_token_conversion(self) -> None:
        self.assertEqual(duration_to_tokens(1), 13)
        self.assertEqual(duration_to_tokens(10), 125)
        self.assertEqual(duration_to_tokens(120), 1500)

    def test_legacy_speed_migrates_to_automatic_duration(self) -> None:
        payload = repository.default_workspace("Chinese", Path("outputs"))
        payload.pop("target_duration_enabled")
        payload.pop("target_duration_seconds")
        payload["natural_speed"] = 1.2
        workspace = WorkspaceDraft.model_validate(payload)
        self.assertFalse(workspace.target_duration_enabled)
        self.assertEqual(workspace.target_duration_seconds, 10)
        self.assertNotIn("natural_speed", workspace.model_dump())

    def test_generation_snapshot_freezes_style_segments_and_duration(self) -> None:
        workspace = repository.default_workspace("Chinese", Path("outputs"))
        workspace["text"] = "第一段用于验证生成快照能够保存切分信息。第二段继续验证每段都对应相同的生成风格。"
        workspace["style"] = "纪录片旁白"
        workspace["instruction"] = "沉稳、克制"
        workspace["parameters"]["segment_chars"] = 20
        snapshot = build_generation_snapshot(workspace)
        workspace["instruction"] = "后来修改的提示"
        self.assertEqual(snapshot["instruction"], "沉稳、克制")
        self.assertGreater(len(snapshot["segments"]), 1)
        self.assertTrue(all(item["style"] == "纪录片旁白" for item in snapshot["segments"]))
        self.assertFalse(snapshot["target_duration_enabled"])

    def test_output_snapshot_rebuilds_sqlite_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("快照恢复", "Chinese")
                    audio = root / "projects" / created["id"] / "outputs" / "result.wav"
                    audio.write_bytes(b"RIFF")
                    metadata = {
                        "path": str(audio), "filename": audio.name, "created_at": "2026-08-12T12:00:00",
                        "duration": 1.0, "sample_rate": 24000, "channels": 1, "bit_depth": 24, "format": "WAV",
                        "generation_snapshot": build_generation_snapshot(created["workspace"]),
                    }
                    record = repository.add_output(created["id"], "task-snapshot", metadata)
                    with database.transaction() as connection:
                        connection.execute("DELETE FROM outputs WHERE id=?", (record["id"],))
                    repository.rebuild_project_index()
                    recovered = repository.list_outputs(created["id"])[0]
                    self.assertEqual(recovered["generation_snapshot"]["style"], "自然影视")
                    repository.clear_outputs(created["id"], False)
                    project_payload = json.loads((root / "projects" / created["id"] / "project.json").read_text(encoding="utf-8"))
                    self.assertEqual(project_payload["output_snapshots"], {})
            finally:
                database.close()

    def test_standard_and_compatibility_baselines(self) -> None:
        self.assertEqual(PARAMETER_PRESETS["标准"]["segment_chars"], 400)
        self.assertEqual(PARAMETER_PRESETS["标准"]["max_seconds"], 120)
        self.assertEqual(PARAMETER_PRESETS["兼容"]["segment_chars"], 90)
        self.assertEqual(PARAMETER_PRESETS["兼容"]["max_seconds"], 20)

    def test_text_split_respects_limit(self) -> None:
        segments = split_text("第一句用于测试。第二句继续测试。第三句也完整保留。", 20)
        self.assertGreater(len(segments), 1)
        self.assertTrue(all(len(segment) <= 20 for segment in segments))


if __name__ == "__main__":
    unittest.main()
