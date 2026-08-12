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
from desktop.backend.module_service import MODEL_LOCKS, ModuleService, _model_complete
from desktop.backend.schemas import ModuleTaskCreate, ProjectPatch, SoundEffectDraft, VoiceDesignDraft, WorkspaceDraft
from desktop.workers.module_downloader import manifest_digest
from desktop.backend.task_service import _next_output_index, build_generation_snapshot, estimate_speed_tokens


def sine(sample_rate: int, seconds: float) -> np.ndarray:
    timeline = np.arange(int(sample_rate * seconds), dtype=np.float32) / sample_rate
    return (.2 * np.sin(2 * np.pi * 220 * timeline)).astype(np.float32)


class RepositoryTests(unittest.TestCase):
    def test_module_workspaces_save_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("多模块项目", "Chinese")
                    speech_text = created["workspaces"]["speech"]["text"]
                    voice_design = VoiceDesignDraft.model_validate(created["workspaces"]["voice_design"])
                    voice_design.instruction = "明亮而富有朝气的青年女声"
                    saved = repository.save_project(created["id"], created["revision"], voice_design, "voice_design")
                    self.assertEqual(saved["workspaces"]["voice_design"]["instruction"], voice_design.instruction)
                    self.assertEqual(saved["workspaces"]["speech"]["text"], speech_text)
            finally:
                database.close()

    def test_legacy_project_is_migrated_when_opened(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("旧项目", "Chinese")
                    project_file = root / "projects" / created["id"] / "project.json"
                    payload = json.loads(project_file.read_text(encoding="utf-8"))
                    payload["workspace"] = payload.pop("workspaces")["speech"]
                    payload["schema_version"] = 3
                    payload["workspace"].pop("manual_speed_enabled")
                    payload["workspace"].pop("manual_speed_level")
                    payload["workspace"]["target_duration_enabled"] = True
                    payload["workspace"]["target_duration_seconds"] = 30
                    payload["workspace"]["natural_speed"] = 1.15
                    project_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    opened = repository.get_project(created["id"])
                    self.assertFalse(opened["workspace"]["manual_speed_enabled"])
                    self.assertEqual(opened["workspace"]["manual_speed_level"], "中等")
                    self.assertNotIn("natural_speed", opened["workspace"])
                    self.assertNotIn("target_duration_enabled", opened["workspace"])
            finally:
                database.close()

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

    def test_task_removal_and_activity_clear_preserve_active_tasks_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("活动清理", "Chinese")
                    audio = root / "kept.wav"
                    audio.write_bytes(b"RIFF")
                    with database.transaction() as connection:
                        for task_id, status in (("task-active", "running"), ("task-finished", "failed")):
                            connection.execute(
                                "INSERT INTO tasks(id,project_id,status,progress,message,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                                (task_id, created["id"], status, 0, status, "{}", "2026-08-12T10:00:00", "2026-08-12T10:00:00"),
                            )
                    metadata = {
                        "path": str(audio), "filename": audio.name, "created_at": "2026-08-12T12:00:00",
                        "duration": 1.0, "sample_rate": 24000, "channels": 1, "bit_depth": 24, "format": "WAV",
                        "generation_snapshot": build_generation_snapshot(created["workspace"]),
                    }
                    repository.add_output(created["id"], "task-output", metadata)
                    repository.delete_task("task-finished")
                    self.assertIsNone(database.one("SELECT id FROM tasks WHERE id='task-finished'"))
                    with self.assertRaises(ValueError):
                        repository.delete_task("task-active")

                    result = repository.clear_project_activity(created["id"], False)
                    self.assertEqual(result["outputs_removed"], 1)
                    self.assertIsNotNone(database.one("SELECT id FROM tasks WHERE id='task-active'"))
                    self.assertTrue(audio.exists())
                    payload = json.loads((root / "projects" / created["id"] / "project.json").read_text(encoding="utf-8"))
                    self.assertEqual(payload["output_snapshots"], {})
            finally:
                database.close()

    def test_remove_after_stop_column_migrates_and_is_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database):
                    with database.transaction() as connection:
                        connection.execute(
                            "INSERT INTO tasks(id,project_id,status,progress,message,payload_json,remove_after_stop,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                            ("task-pending-remove", "project", "running", 0, "停止中", "{}", 1, "2026-08-12T10:00:00", "2026-08-12T10:00:00"),
                        )
                    self.assertTrue(repository.get_task("task-pending-remove")["remove_after_stop"])
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
            profile = {"format": "WAV", "sample_rate": 48000, "bit_depth": 24, "channels": 1, "loudness_lufs": -23, "filename_template": "BROKEN_{missing}", "output_directory": str(root / "outputs")}
            with patch.object(output_engineering, "RAW_OUTPUTS_DIR", raw_dir):
                metadata = output_engineering.render_output(str(source), profile, "工程测试", "音色A", 1)
            target = Path(metadata["path"])
            self.assertTrue(target.is_file())
            self.assertTrue(target.with_suffix(".wav.json").is_file())
            self.assertEqual(metadata["sample_rate"], 48000)
            self.assertRegex(target.name, r"^工程测试_音色A_001_\d{8}_\d{6}\.wav$")
            self.assertNotIn("BROKEN", target.name)


class ModelContractTests(unittest.TestCase):
    def test_module_task_payload_is_discriminated_by_module(self) -> None:
        voice_task = ModuleTaskCreate.model_validate({
            "project_id": "project",
            "module": "voice_design",
            "workspace": {"text": "测试台词", "instruction": "温润而沉稳"},
        })
        self.assertIsInstance(voice_task.workspace, VoiceDesignDraft)
        sound_task = ModuleTaskCreate.model_validate({
            "project_id": "project",
            "module": "sound_effect",
            "workspace": {"prompt": "雨夜街道", "parameters": {"seconds": 12}},
        })
        self.assertIsInstance(sound_task.workspace, SoundEffectDraft)
        self.assertEqual(sound_task.workspace.parameters.seconds, 12)

    def test_interrupted_install_is_reported_as_repairable(self) -> None:
        service = ModuleService.__new__(ModuleService)
        service.install_threads = {}
        service.states = {
            "voice_design": {
                "status": "installing",
                "model_ready": False,
                "runtime_ready": False,
                "phase": "models",
                "progress": 0.52,
            }
        }
        descriptor = service.describe("voice_design")
        self.assertEqual(descriptor["install_state"], "repair_required")
        self.assertIn("Python 3.12", descriptor["runtime_python"])

    def test_voice_design_output_sequence_survives_cleared_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "项目_音色设计_002_20260812_120000.wav").write_bytes(b"RIFF")
            (root / "项目_音色设计_009_20260812_130000.wav").write_bytes(b"RIFF")
            self.assertEqual(_next_output_index(root), 10)
            self.assertEqual(_next_output_index(root, 15), 15)

    def test_project_patch_uses_module_to_parse_voice_design_workspace(self) -> None:
        patch_model = ProjectPatch.model_validate({
            "revision": 0,
            "module": "voice_design",
            "workspace": {"text": "测试台词", "instruction": "测试音色"},
        })
        self.assertIsInstance(patch_model.workspace, VoiceDesignDraft)
        self.assertEqual(patch_model.workspace.instruction, "测试音色")

    def test_voice_generator_defaults_match_official_sampling_baseline(self) -> None:
        parameters = VoiceDesignDraft().parameters
        self.assertEqual(parameters.audio_temperature, 1.5)
        self.assertEqual(parameters.audio_top_p, 0.6)
        self.assertEqual(parameters.audio_top_k, 50)
        self.assertEqual(parameters.audio_repetition_penalty, 1.1)
        self.assertEqual(parameters.max_new_tokens, 4096)

    def test_model_lock_contracts_are_stable(self) -> None:
        self.assertEqual(MODEL_LOCKS["openmoss/MOSS-VoiceGenerator"]["file_count"], 17)
        self.assertEqual(MODEL_LOCKS["openmoss/MOSS-Audio-Tokenizer"]["total_bytes"], 7_101_116_247)
        self.assertEqual(MODEL_LOCKS["openmoss/MOSS-SoundEffect-v2.0"]["manifest_sha256"], "b50a3034b1abae0bfcc7435e079e5c03705b1a61ee17f22aaae1941126c7daf7")

    def test_manifest_digest_is_order_independent(self) -> None:
        class Entry:
            def __init__(self, path: str, size: int, sha256: str):
                self.path = path
                self.size = size
                self.sha256 = sha256
                self.is_dir = False
                self.type = "blob"

        entries = [Entry("b.bin", 2, "bb"), Entry("a.bin", 1, "aa")]
        self.assertEqual(manifest_digest(entries), manifest_digest(reversed(entries)))

    def test_incomplete_model_install_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = MODEL_LOCKS["openmoss/MOSS-VoiceGenerator"]
            (root / ".voicegrid-install.json").write_text(
                json.dumps({"repo_id": "openmoss/MOSS-VoiceGenerator", "manifest_sha256": lock["manifest_sha256"]}),
                encoding="utf-8",
            )
            self.assertFalse(_model_complete(root, "voice_design"))
            (root / ".voicegrid-install.json").unlink()
            (root / "config.json").write_bytes(b"")
            (root / "empty.safetensors").write_bytes(b"")
            self.assertFalse(_model_complete(root, "voice_design"))

    def test_rebuild_ignores_output_outside_project_resource_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("边界检查", "Chinese")
                    external = root / "external.wav"
                    external.write_bytes(b"RIFF")
                    project_file = root / "projects" / created["id"] / "project.json"
                    payload = json.loads(project_file.read_text(encoding="utf-8"))
                    payload["output_snapshots"]["untrusted"] = {
                        "path": str(external), "filename": external.name, "module": "speech", "kind": "speech_output",
                    }
                    project_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    repository.rebuild_project_index()
                    self.assertIsNone(database.one("SELECT id FROM outputs WHERE id='untrusted'"))
            finally:
                database.close()

    def test_rebuild_accepts_registered_external_delivery_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("交付目录", "Chinese")
                    delivery = root / "delivery"
                    delivery.mkdir()
                    workspace = WorkspaceDraft.model_validate(created["workspace"])
                    workspace.output_profile.output_directory = str(delivery)
                    repository.save_project(created["id"], created["revision"], workspace)
                    audio = delivery / "result.wav"
                    audio.write_bytes(b"RIFF")
                    project_file = root / "projects" / created["id"] / "project.json"
                    payload = json.loads(project_file.read_text(encoding="utf-8"))
                    payload["output_snapshots"]["trusted"] = {
                        "path": str(audio), "filename": audio.name, "module": "speech", "kind": "speech_output",
                    }
                    project_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    repository.rebuild_project_index()
                    self.assertIsNotNone(database.one("SELECT id FROM outputs WHERE id='trusted'"))
            finally:
                database.close()

    def test_manual_speed_estimates_tokens_from_text_length(self) -> None:
        text = "这是一段用于验证手动语速控制的二十字文本。"
        effective_chars = len(text)
        expected = {
            "慢": max(13, int(effective_chars * 3.8 + .5)),
            "较慢": max(13, int(effective_chars * 3.4 + .5)),
            "中等": max(13, int(effective_chars * 3.0 + .5)),
            "较快": max(13, int(effective_chars * 2.65 + .5)),
            "快": max(13, int(effective_chars * 2.3 + .5)),
        }
        actual = {level: estimate_speed_tokens(text, level) for level in expected}
        self.assertEqual(actual, expected)
        self.assertEqual(list(actual.values()), sorted(actual.values(), reverse=True))
        self.assertEqual(estimate_speed_tokens("你 好\n世 界", "中等"), 13)
        self.assertEqual(
            estimate_speed_tokens("这是测试文本。[pause 1.0s]继续。", "中等")
            - estimate_speed_tokens("这是测试文本。继续。", "中等"),
            13,
        )

    def test_legacy_duration_migrates_to_automatic_speed(self) -> None:
        payload = repository.default_workspace("Chinese", Path("outputs"))
        payload.pop("manual_speed_enabled")
        payload.pop("manual_speed_level")
        payload["target_duration_enabled"] = True
        payload["target_duration_seconds"] = 20
        payload["natural_speed"] = 1.2
        workspace = WorkspaceDraft.model_validate(payload)
        self.assertFalse(workspace.manual_speed_enabled)
        self.assertEqual(workspace.manual_speed_level, "中等")
        self.assertNotIn("natural_speed", workspace.model_dump())
        self.assertNotIn("target_duration_seconds", workspace.model_dump())

    def test_generation_snapshot_only_freezes_style_instruction_and_reference(self) -> None:
        workspace = repository.default_workspace("Chinese", Path("outputs"))
        workspace["style"] = "纪录片旁白"
        workspace["instruction"] = "沉稳、克制"
        snapshot = build_generation_snapshot(workspace)
        workspace["instruction"] = "后来修改的提示"
        self.assertEqual(snapshot["instruction"], "沉稳、克制")
        self.assertEqual(snapshot["style"], "纪录片旁白")
        self.assertIsNone(snapshot["reference_audio"])
        self.assertEqual(snapshot["speed"], "自动")
        self.assertEqual(set(snapshot), {"style", "instruction", "reference_audio", "speed"})

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

    def test_text_split_never_breaks_native_pause_marker(self) -> None:
        text = "第一段较长的测试台词[pause 3.2s]第二段继续完整说完。"
        segments = split_text(text, 20)
        self.assertEqual("".join(segments), text)
        self.assertEqual(sum("[pause 3.2s]" in segment for segment in segments), 1)
        self.assertNotIn("[pause 3.2s]", segments)


if __name__ == "__main__":
    unittest.main()
