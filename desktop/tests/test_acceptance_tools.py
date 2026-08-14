from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from desktop.tools.acceptance_common import WavExpectations, inspect_wav, save_module_workspace, write_report
from desktop.tools.voice_generator_acceptance import (
    CASES,
    dry_run_plan,
    execute_case_matrix,
    precision_gate_passed,
    _stage_timings,
    run_case_with_retry,
    workspace_for,
)
from desktop.tools.sound_effect_acceptance import CASES as SOUND_EFFECT_CASES, GATE as SOUND_EFFECT_GATE, dry_run_plan as sound_effect_dry_run_plan, workspace_for as sound_effect_workspace_for


class AcceptanceCommonTests(unittest.TestCase):
    def test_gpu_sampler_can_summarize_a_sample_window(self) -> None:
        from desktop.tools.acceptance_common import NvidiaSmiSampler

        sampler = NvidiaSmiSampler()
        sampler.samples = [{"memory_used_mib": 100.0, "utilization_percent": 10.0}]
        mark = sampler.mark()
        sampler.samples.extend([
            {"memory_used_mib": 9000.0, "utilization_percent": 99.0},
            {"memory_used_mib": 8500.0, "utilization_percent": 80.0},
        ])
        summary = sampler.summary_since(mark)
        self.assertEqual(summary["sample_count"], 2)
        self.assertEqual(summary["peak_memory_used_mib"], 9000.0)

    def test_save_module_workspace_reuses_project_revision(self) -> None:
        from unittest.mock import Mock

        client = Mock()
        client.get.return_value = {"revision": 7}
        client.patch.return_value = {"revision": 8}
        result = save_module_workspace(client, "project", "voice_design", {"text": "test"})
        self.assertEqual(result["revision"], 8)
        client.patch.assert_called_once_with(
            "/projects/project",
            {"revision": 7, "module": "voice_design", "workspace": {"text": "test"}},
        )

    def test_wav_inspection_accepts_clean_pcm24(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "clean.wav"
            sample_rate = 24000
            time_axis = np.arange(sample_rate, dtype=np.float32) / sample_rate
            audio = (0.2 * np.sin(2 * np.pi * 440 * time_axis)).astype(np.float32)
            sf.write(path, audio, sample_rate, subtype="PCM_24")
            result = inspect_wav(path, WavExpectations(sample_rate=24000, channels=1))
            self.assertTrue(result["passed"], result["failures"])
            self.assertEqual(result["subtype"], "PCM_24")
            self.assertEqual(result["sample_rate"], 24000)
            self.assertTrue(result["finite"])

    def test_wav_inspection_rejects_wrong_subtype_and_silence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "silent.wav"
            sf.write(path, np.zeros(24000, dtype=np.float32), 24000, subtype="PCM_16")
            result = inspect_wav(path, WavExpectations(sample_rate=24000, channels=1))
            self.assertFalse(result["passed"])
            self.assertIn("subtype", result["failures"])
            self.assertIn("silence_ratio", result["failures"])

    def test_report_writes_utf8_json_and_markdown(self) -> None:
        report = {
            "title": "音色设计验收",
            "status": "passed",
            "started_at": "2026-08-12T12:00:00",
            "finished_at": "2026-08-12T12:01:00",
            "base_url": "http://127.0.0.1:7862/api/v2",
            "project": {"name": "中文项目"},
            "samples": [],
            "gpu": {"sample_count": 1, "peak_memory_used_mib": 9000, "peak_utilization_percent": 99},
            "errors": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            json_path, markdown_path = write_report(report, Path(temporary), "report")
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["title"], "音色设计验收")
            self.assertIn("中文项目", markdown_path.read_text(encoding="utf-8"))
            self.assertFalse(json_path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_sound_effect_acceptance_matrix_uses_locked_parameters(self) -> None:
        self.assertEqual([(case.case_id, case.seconds) for case in SOUND_EFFECT_CASES], [("A", 5), ("B", 10), ("C", 20), ("D", 30)])
        gate = sound_effect_workspace_for(SOUND_EFFECT_GATE, steps=10)
        self.assertEqual(gate["parameters"], {
            "seconds": 3, "num_inference_steps": 10, "cfg_scale": 4.0,
            "sigma_shift": 5.0, "seed": 2026,
        })
        plan = sound_effect_dry_run_plan("验收项目", "http://127.0.0.1:7862")
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["rules"]["duration_tolerance_seconds"], .02)


class VoiceGeneratorAcceptanceTests(unittest.TestCase):
    def test_stage_timings_are_derived_from_progress_timeline(self) -> None:
        timeline = [
            {"elapsed_seconds": 5.0, "progress": 0.676},
            {"elapsed_seconds": 5.2, "progress": 0.714},
            {"elapsed_seconds": 11.0, "progress": 0.883},
            {"elapsed_seconds": 13.0, "progress": 1.0},
        ]
        timings = _stage_timings(timeline)
        self.assertEqual(timings["load_seconds"], 5.0)
        self.assertEqual(timings["generation_seconds"], 5.8)
        self.assertEqual(timings["decode_and_write_seconds"], 2.0)

    def test_precision_gate_requires_completed_pcm_and_requested_cuda_dtype(self) -> None:
        sample = {"task_status": "completed", "wav": {"passed": True}}
        fp16_runtime = {
            "device": "cuda",
            "dtype": "float16",
            "sampling_dtype": "float32",
            "projection_dtype": "float32",
        }
        self.assertTrue(precision_gate_passed(sample, fp16_runtime, "float16"))
        self.assertFalse(precision_gate_passed(sample, {**fp16_runtime, "sampling_dtype": "float16"}, "float16"))
        self.assertFalse(precision_gate_passed(sample, {**fp16_runtime, "projection_dtype": "float16"}, "float16"))
        self.assertFalse(precision_gate_passed(sample, {**fp16_runtime, "dtype": "bfloat16"}, "float16"))
        self.assertFalse(precision_gate_passed({"task_status": "failed", "wav": {"passed": True}}, fp16_runtime, "float16"))

        fp32_runtime = {
            "device": "cuda",
            "dtype": "float32",
            "sampling_dtype": "float32",
            "projection_dtype": "float32",
        }
        self.assertTrue(precision_gate_passed(sample, fp32_runtime, "float32"))

        bf16_runtime = {
            "device": "cuda",
            "dtype": "bfloat16",
            "sampling_dtype": "float32",
            "projection_dtype": "bfloat16",
        }
        self.assertTrue(precision_gate_passed(sample, bf16_runtime, "bfloat16"))

    def test_configuration_uses_2026_and_dry_run_is_offline(self) -> None:
        self.assertEqual([case.case_id for case in CASES], ["A", "B", "C", "D"])
        workspace = workspace_for(CASES[0], 2026)
        self.assertEqual(workspace["parameters"]["seed"], 2026)
        self.assertEqual(workspace["text"], "哎呀，我的老腰啊，这年纪大了就是不行了。")
        self.assertIn("老年男性", workspace["instruction"])
        plan = dry_run_plan("验收项目", "http://127.0.0.1:7862", True)
        self.assertTrue(plan["dry_run"])
        self.assertTrue(plan["cancel_recovery"])
        self.assertEqual(plan["technical_retry_seed"], 2027)

    def test_retry_is_limited_to_completed_technical_failure(self) -> None:
        from unittest.mock import patch

        completed_bad = {"task_status": "completed", "wav": {"passed": False}, "technical_passed": False}
        completed_good = {"task_status": "completed", "wav": {"passed": True}, "technical_passed": True}
        with patch(
            "desktop.tools.voice_generator_acceptance.run_case",
            side_effect=[completed_bad, completed_good],
        ) as mocked:
            final, attempts = run_case_with_retry(object(), "project", CASES[0], Path("temporary"), 1)
            self.assertEqual(len(attempts), 2)
            self.assertTrue(final["technical_passed"])
            self.assertEqual(mocked.call_args_list[1].args[3], 2027)

        task_failed = {"task_status": "failed", "technical_passed": False}
        with patch("desktop.tools.voice_generator_acceptance.run_case", return_value=task_failed) as mocked:
            _, attempts = run_case_with_retry(object(), "project", CASES[0], Path("temporary"), 1)
            self.assertEqual(len(attempts), 1)
            mocked.assert_called_once()

    def test_failed_a_gate_stops_before_b_through_d(self) -> None:
        from unittest.mock import Mock, patch

        successful_wav = {"case_id": "A", "task_status": "completed", "wav": {"passed": True}, "technical_passed": True}
        client = Mock()
        client.get.return_value = {"device": "cuda", "dtype": "bfloat16", "sampling_dtype": "bfloat16"}
        with patch(
            "desktop.tools.voice_generator_acceptance.run_case_with_retry",
            return_value=(successful_wav, [successful_wav]),
        ) as run:
            matrix = execute_case_matrix(client, "project", Path("temporary"), 1, "float16")
        self.assertFalse(matrix["a_gate_passed"])
        self.assertEqual(len(matrix["final_samples"]), 1)
        run.assert_called_once()

    def test_a_gate_prefers_runtime_snapshot_captured_while_loaded(self) -> None:
        from unittest.mock import Mock, patch

        loaded_runtime = {
            "device": "cuda",
            "dtype": "float16",
            "sampling_dtype": "float32",
            "projection_dtype": "float32",
        }
        successful = {
            "case_id": "A",
            "task_status": "completed",
            "wav": {"passed": True},
            "technical_passed": True,
            "runtime_loaded": loaded_runtime,
        }
        client = Mock()
        with patch(
            "desktop.tools.voice_generator_acceptance.run_case_with_retry",
            return_value=(successful, [successful]),
        ):
            matrix = execute_case_matrix(client, "project", Path("temporary"), 1, "float16")
        self.assertTrue(matrix["a_gate_passed"])
        self.assertEqual(matrix["a_gate_runtime"], loaded_runtime)
        client.get.assert_not_called()

    def test_gate_only_stops_after_successful_a(self) -> None:
        from unittest.mock import Mock, patch

        runtime = {
            "device": "cuda",
            "dtype": "float16",
            "sampling_dtype": "float32",
            "projection_dtype": "float32",
        }
        successful = {
            "case_id": "A",
            "task_status": "completed",
            "wav": {"passed": True},
            "technical_passed": True,
            "runtime_loaded": runtime,
        }
        client = Mock()
        with patch(
            "desktop.tools.voice_generator_acceptance.run_case_with_retry",
            return_value=(successful, [successful]),
        ) as run:
            matrix = execute_case_matrix(client, "project", Path("temporary"), 1, "float16", gate_only=True)
        self.assertTrue(matrix["a_gate_passed"])
        self.assertEqual(len(matrix["final_samples"]), 1)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
