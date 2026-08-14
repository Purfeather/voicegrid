from __future__ import annotations

import json
import os
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
from desktop.backend.module_service import MODEL_LOCKS, RUNTIME_PYTHON_LOCKS, RUNTIME_VERSION_LOCKS, ModuleService, _model_complete
from desktop.backend.schemas import ModuleTaskCreate, ProjectPatch, SoundEffectDraft, SoundEffectOutputPatch, VoiceDesignDraft, WorkspaceDraft
from desktop.workers.module_downloader import manifest_digest, verify_install_manifest
from desktop.workers.runtime_audio_probe import probe_pcm24
from desktop.workers.audio_io import write_pcm24_wav
from desktop.workers.cuda_policy import sdpa_policy, voice_generator_precision_policy
from desktop.workers.sampling_precision import promote_sampling_logits_to_float32, validate_sampleable_logits
from desktop.workers.voice_generator_worker import native_bf16_available
from desktop.backend.task_service import _next_output_index, build_generation_snapshot, build_sound_effect_snapshot, estimate_speed_tokens


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

    def test_legacy_project_is_rejected_without_partial_migration(self) -> None:
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
                    before = project_file.read_bytes()
                    with self.assertRaisesRegex(ValueError, "仅支持 VoiceGrid 1.0"):
                        repository.get_project(created["id"])
                    self.assertEqual(project_file.read_bytes(), before)
            finally:
                database.close()

    def test_sound_effect_output_metadata_can_be_renamed_favorited_and_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    project = repository.create_project("音效项目", "Chinese")
                    output_dir = repository.project_output_directory(project["id"], "sound_effect", create=True)
                    source = output_dir / "音效项目_音效_001_20260813_120000.wav"
                    sf.write(source, sine(48000, 1), 48000, subtype="PCM_24")
                    record = repository.add_output(project["id"], "task", {
                        "path": str(source), "filename": source.name, "created_at": repository.now(),
                        "duration": 1.0, "sample_rate": 48000, "channels": 1, "bit_depth": 24,
                        "format": "WAV", "voice": "项目音效", "text": "雨声", "favorite": False,
                        "generation_snapshot": build_sound_effect_snapshot({"prompt": "雨声", "parameters": {}}),
                    }, "sound_effect", "sound_effect_output")
                    updated = repository.update_sound_effect_output(record["id"], SoundEffectOutputPatch(name="收藏雨声", favorite=True))
                    self.assertEqual(updated["filename"], "收藏雨声.wav")
                    self.assertTrue(updated["favorite"])
                    self.assertTrue((output_dir / "收藏雨声.wav").is_file())
                    repository.delete_sound_effect_output(record["id"], True)
                    self.assertFalse((output_dir / "收藏雨声.wav").exists())
                    self.assertEqual(repository.list_outputs(project["id"], "sound_effect"), [])
            finally:
                database.close()

    def test_sound_effect_snapshot_records_precision_and_low_vram_mode(self) -> None:
        snapshot = build_sound_effect_snapshot({
            "prompt": "金属门开启",
            "parameters": {"seconds": 20, "num_inference_steps": 100, "cfg_scale": 4.0, "sigma_shift": 5.0, "seed": 2026},
        })
        self.assertEqual(snapshot["seconds"], 20)
        self.assertEqual(snapshot["runtime_precision"], "float16")
        self.assertTrue(snapshot["low_vram"])

    def test_project_is_atomic_and_recovery_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("验收项目", "Chinese")
                    self.assertEqual(created["voice"], "无参考音色")
                    self.assertEqual(repository.list_projects()[0]["voice"], "无参考音色")
                    workspace = WorkspaceDraft.model_validate(created["workspace"])
                    workspace.text = "粘贴后立即保存的新文本"
                    saved = repository.save_project(created["id"], created["revision"], workspace)
                    self.assertGreater(saved["revision"], created["revision"])
                    with database.transaction() as connection:
                        connection.execute("DELETE FROM projects WHERE id=?", (created["id"],))
                    repository.rebuild_project_index()
                    self.assertIsNotNone(database.one("SELECT id FROM projects WHERE id=?", (created["id"],)))
                    saved_at = saved["updated_at"]
                    repository.mark_interrupted_projects()
                    summary = repository.list_projects()[0]
                    self.assertTrue(summary["recovery_available"])
                    self.assertEqual(summary["status"], "已恢复最近自动保存")
                    reopened = repository.get_project(created["id"], begin_session=True)
                    self.assertTrue(reopened["recovery_available"])
                    self.assertEqual(reopened["updated_at"], saved_at)
                    self.assertEqual(reopened["workspace"]["text"], "粘贴后立即保存的新文本")
                    confirmed = repository.confirm_project_recovery(created["id"])
                    self.assertFalse(confirmed["recovery_available"])
                    self.assertEqual(confirmed["status"], "项目已保存")
                    self.assertEqual(confirmed["updated_at"], saved_at)
                    repository.close_project(created["id"])
                    closed = repository.list_projects()[0]
                    self.assertFalse(closed["recovery_available"])
                    self.assertEqual(closed["updated_at"], saved_at)
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

    def test_twenty_clean_project_sessions_never_become_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("正常退出验收", "Chinese")
                    original_updated_at = created["updated_at"]
                    repository.close_project(created["id"])
                    for _ in range(20):
                        opened = repository.get_project(created["id"], begin_session=True)
                        self.assertFalse(opened["recovery_available"])
                        repository.close_project(created["id"])
                        repository.mark_interrupted_projects()
                        summary = repository.list_projects()[0]
                        self.assertFalse(summary["recovery_available"])
                        self.assertEqual(summary["status"], "项目已保存")
                        self.assertEqual(summary["updated_at"], original_updated_at)
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

    def test_atomic_project_write_retries_transient_windows_denial(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "project.json"
            real_replace = os.replace
            attempts = 0

            def transient_replace(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError(5, "transient sharing violation")
                return real_replace(source, destination)

            with patch.object(repository.os, "replace", side_effect=transient_replace):
                repository._write_atomic(target, {"schema_version": 4, "id": "retry"})
            self.assertEqual(attempts, 3)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["id"], "retry")
            self.assertFalse(list(target.parent.glob("*.tmp")))

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
                    audio = repository.project_output_directory(created["id"], "speech") / "kept.wav"
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
            profile = {"format": "WAV", "sample_rate": 48000, "bit_depth": 24, "channels": 2, "loudness_lufs": -23, "filename_template": "BROKEN_{missing}", "output_directory": str(root / "ignored")}
            output_directory = root / "outputs"
            with patch.object(output_engineering, "RAW_OUTPUTS_DIR", raw_dir):
                metadata = output_engineering.render_output(str(source), profile, output_directory, "工程测试", "音色A", 1)
            target = Path(metadata["path"])
            self.assertTrue(target.is_file())
            self.assertTrue(target.with_suffix(".wav.json").is_file())
            self.assertEqual(metadata["sample_rate"], 48000)
            self.assertEqual(metadata["channels"], 2)
            self.assertEqual(sf.info(target).channels, 2)
            self.assertEqual(target.parent.resolve(), output_directory.resolve())
            self.assertRegex(target.name, r"^工程测试_音色A_001_\d{8}_\d{6}\.wav$")
            self.assertNotIn("BROKEN", target.name)

    def test_reference_free_output_uses_explicit_voice_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            source = raw_dir / "source.wav"
            sf.write(source, sine(24000, .2), 24000, subtype="PCM_24")
            output_directory = root / "outputs"
            with patch.object(output_engineering, "RAW_OUTPUTS_DIR", raw_dir):
                metadata = output_engineering.render_output(
                    str(source),
                    {"format": "WAV", "sample_rate": 48000, "bit_depth": 24, "channels": 2, "loudness_lufs": None},
                    output_directory,
                    "无参考测试",
                    "无参考音色",
                    1,
                )
            self.assertRegex(Path(metadata["path"]).name, r"^无参考测试_无参考音色_001_\d{8}_\d{6}\.wav$")


class ModelContractTests(unittest.TestCase):
    def test_runtime_data_defaults_are_consolidated_under_data(self) -> None:
        from desktop.backend.paths import DATA_DIR, LOGS_DIR, OUTPUTS_DIR, PROJECTS_DIR, REFERENCES_DIR

        self.assertEqual(PROJECTS_DIR, DATA_DIR / "projects")
        self.assertEqual(OUTPUTS_DIR, DATA_DIR / "outputs")
        self.assertEqual(REFERENCES_DIR, DATA_DIR / "references")
        self.assertEqual(LOGS_DIR, DATA_DIR / "logs")

    def test_speech_models_are_managed_inside_test_optional_models(self):
        from desktop.backend.module_service import MODEL_LOCKS, MODULE_SERVICE
        from desktop.backend.paths import MOSS_CODEC_DIR, MOSS_MODEL_DIR, OPTIONAL_MODELS_DIR

        self.assertEqual(MOSS_MODEL_DIR.parent, OPTIONAL_MODELS_DIR)
        self.assertEqual(MOSS_CODEC_DIR.parent, OPTIONAL_MODELS_DIR)
        self.assertIn("openmoss/MOSS-TTS-Local-Transformer-v1.5", MODEL_LOCKS)
        self.assertIn("openmoss/MOSS-Audio-Tokenizer-v2", MODEL_LOCKS)
        descriptor = MODULE_SERVICE.describe("speech")
        self.assertEqual(descriptor["runtime_mode"], "host")
        self.assertEqual(descriptor["manual_paths"], [
            "optional-models\\MOSS-TTS-Local-Transformer-v1.5",
            "optional-models\\MOSS-Audio-Tokenizer-v2",
        ])

    def test_voice_design_pcm24_writer_and_runtime_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "voice.wav"
            metadata = write_pcm24_wav(target, sine(24000, 1.0), 24000)
            info = sf.info(target)
            self.assertEqual(info.subtype, "PCM_24")
            self.assertEqual(metadata["subtype"], "PCM_24")
            self.assertEqual(metadata["channels"], 1)
            probe = probe_pcm24(root / "probe")
            self.assertEqual(probe["subtype"], "PCM_24")

    def test_voice_design_runtime_is_fully_pinned_to_python_312(self) -> None:
        self.assertEqual(RUNTIME_PYTHON_LOCKS["voice_design"], (3, 12))
        expected = {
            "torch", "torchaudio", "transformers", "modelscope", "modelscope-hub", "accelerate",
            "safetensors", "numpy", "orjson", "tqdm", "PyYAML", "einops", "scipy", "librosa",
            "tiktoken", "soundfile", "psutil", "packaging",
        }
        self.assertEqual(set(RUNTIME_VERSION_LOCKS["voice_design"]), expected)

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

    def test_voice_generator_rejects_emulated_bf16_on_turing(self) -> None:
        self.assertFalse(native_bf16_available((7, 5), True))
        self.assertFalse(native_bf16_available((8, 0), False))
        self.assertTrue(native_bf16_available((8, 0), True))

    def test_turing_uses_math_sdpa_without_disabling_sdpa(self) -> None:
        turing = sdpa_policy((7, 5))
        self.assertFalse(turing.flash)
        self.assertFalse(turing.memory_efficient)
        self.assertTrue(turing.math)
        self.assertEqual(turing.label, "sdpa-math")
        ampere = sdpa_policy((8, 0))
        self.assertTrue(ampere.flash)
        self.assertTrue(ampere.memory_efficient)
        self.assertTrue(ampere.math)

    def test_voice_generator_precision_policy_uses_fp32_on_turing(self) -> None:
        turing = voice_generator_precision_policy((7, 5), native_bf16=False)
        self.assertEqual(turing.model_dtype, "float32")
        self.assertEqual(turing.projection_dtype, "float32")
        self.assertEqual(turing.sampling_dtype, "float32")
        self.assertEqual(turing.attention_backend, "sdpa-math")
        self.assertIn("float32-model", turing.runtime_label)

    def test_voice_generator_precision_policy_uses_native_bf16_on_ampere(self) -> None:
        ampere = voice_generator_precision_policy((8, 0), native_bf16=True)
        self.assertEqual(ampere.model_dtype, "bfloat16")
        self.assertEqual(ampere.sampling_dtype, "float32")
        self.assertEqual(ampere.attention_backend, "sdpa")

    def test_fp32_sampling_adapter_reuses_official_sampler(self) -> None:
        calls: list[tuple[object, object]] = []

        class FakeLogits:
            def __init__(self, name: str) -> None:
                self.name = name

            def float(self) -> "FakeLogits":
                return FakeLogits("float32")

        def official_sampler(logits, *, top_k=None):
            calls.append((logits, top_k))
            return "sampled"

        adapter = promote_sampling_logits_to_float32(official_sampler)
        self.assertEqual(adapter(logits=FakeLogits("float16"), top_k=50), "sampled")
        self.assertEqual(calls[0][0].name, "float32")
        self.assertEqual(calls[0][1], 50)
        self.assertTrue(getattr(adapter, "_voicegrid_fp32_sampling"))

    def test_sampling_validation_allows_empty_batch_with_vocabulary(self) -> None:
        import torch

        validate_sampleable_logits(torch.empty((0, 1024), dtype=torch.float32))
        with self.assertRaisesRegex(RuntimeError, "空的采样分布"):
            validate_sampleable_logits(torch.empty((1, 0), dtype=torch.float32))

    def test_model_lock_contracts_are_stable(self) -> None:
        self.assertEqual(MODEL_LOCKS["openmoss/MOSS-VoiceGenerator"]["file_count"], 17)
        self.assertEqual(MODEL_LOCKS["openmoss/MOSS-Audio-Tokenizer"]["total_bytes"], 7_101_116_247)
        self.assertEqual(MODEL_LOCKS["openmoss/MOSS-SoundEffect-v2.0"]["manifest_sha256"], "b50a3034b1abae0bfcc7435e079e5c03705b1a61ee17f22aaae1941126c7daf7")

    def test_module_service_keeps_catalog_and_integrity_compatibility_exports(self) -> None:
        from desktop.backend import module_catalog, module_integrity, module_service

        self.assertIs(module_service.MODEL_LOCKS, module_catalog.MODEL_LOCKS)
        self.assertIs(module_service.MODULES, module_catalog.MODULES)
        self.assertIs(module_service.RUNTIME_PYTHON_LOCKS, module_catalog.RUNTIME_PYTHON_LOCKS)
        self.assertIs(module_service.RUNTIME_VERSION_LOCKS, module_catalog.RUNTIME_VERSION_LOCKS)
        self.assertIs(module_service._model_complete, module_integrity.model_complete)

    def test_module_catalog_owns_paths_and_jobs_for_each_module(self) -> None:
        from desktop.backend.module_catalog import manual_paths, model_ids, runtime_dir

        self.assertEqual(model_ids("speech"), [
            "openmoss/MOSS-TTS-Local-Transformer-v1.5",
            "openmoss/MOSS-Audio-Tokenizer-v2",
        ])
        self.assertEqual(model_ids("voice_design"), [
            "openmoss/MOSS-VoiceGenerator",
            "openmoss/MOSS-Audio-Tokenizer",
        ])
        self.assertEqual(model_ids("sound_effect"), ["openmoss/MOSS-SoundEffect-v2.0"])
        self.assertIsNone(runtime_dir("speech"))
        self.assertEqual(manual_paths("voice_design")[-1], "runtimes\\moss-voice-generator")

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

    def test_locked_manifest_verifies_hidden_repository_files(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b"*.safetensors filter=lfs"
            hidden = root / ".gitattributes"
            hidden.write_bytes(payload)
            manifest = [{
                "path": ".gitattributes",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }]
            verification = verify_install_manifest(root, manifest)
            self.assertTrue(verification.valid)
            self.assertEqual(verification.checked_count, 1)

    def test_locked_manifest_rejects_size_or_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config.json").write_bytes(b"wrong")
            verification = verify_install_manifest(root, [{
                "path": "config.json",
                "size": 5,
                "sha256": "0" * 64,
            }])
            self.assertFalse(verification.valid)
            self.assertEqual(len(verification.mismatches), 1)

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

    def test_ready_module_descriptor_does_not_report_manual_paths_as_missing(self) -> None:
        service = ModuleService()
        service.states["voice_design"] = {
            "model_ready": True,
            "runtime_ready": True,
            "missing": [],
            "status": "ready",
        }
        descriptor = service.describe("voice_design")
        self.assertTrue(descriptor["installed"])
        self.assertEqual(descriptor["missing"], [])

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

    def test_rebuild_accepts_only_module_resource_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("固定交付目录", "Chinese")
                    delivery = repository.project_output_directory(created["id"], "speech")
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

    def test_new_project_creates_fixed_module_directories_and_defaults_to_stereo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "app.db")
            database.initialize()
            try:
                with patch.object(repository, "DB", database), patch.object(repository, "PROJECTS_DIR", root / "projects"):
                    created = repository.create_project("固定目录", "Chinese")
                    self.assertEqual(created["workspace"]["output_profile"]["channels"], 2)
                    self.assertNotIn("output_directory", created["workspace"]["output_profile"])
                    for module in ("speech", "voice_design", "sound_effect"):
                        self.assertTrue(repository.project_output_directory(created["id"], module).is_dir())
                    with self.assertRaises(ValueError):
                        repository.project_output_directory(created["id"], "unknown", create=True)
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
        payload = repository.default_workspace("Chinese")
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
        workspace = repository.default_workspace("Chinese")
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
                    audio = repository.project_output_directory(created["id"], "speech") / "result.wav"
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
