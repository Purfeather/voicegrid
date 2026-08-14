from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ReleasePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = ROOT / "release" / "build_release.py"
        spec = importlib.util.spec_from_file_location("voicegrid_release", path)
        assert spec and spec.loader
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_release_identity_matches_build_manifest(self) -> None:
        self.assertEqual(self.module.VERSION, "1.0.0")
        self.assertEqual(
            self.module.BUILD["build_id"],
            "VOICEGRID-1.0.0-20260814",
        )

    def test_release_root_is_strictly_scoped(self) -> None:
        with self.assertRaises(ValueError):
            self.module.ensure_release_root(Path("D:/VoiceGrid-Other"))

    def test_all_expected_models_are_declared(self) -> None:
        self.assertEqual(len(self.module.MODEL_DIRS), 5)
        self.assertIn("MOSS-TTS-Local-Transformer-v1.5", self.module.MODEL_DIRS)
        self.assertIn("MOSS-SoundEffect-v2.0", self.module.MODEL_DIRS)

    def test_source_package_excludes_generated_launcher_and_frontend(self) -> None:
        files = {path.as_posix() for path in self.module.source_files()}
        self.assertNotIn("VoiceGrid 声格.exe", files)
        self.assertFalse(any(path.startswith("desktop/frontend/dist/") for path in files))

    def test_host_runtime_does_not_make_missing_speech_models_a_repair(self) -> None:
        from desktop.backend.module_service import ModuleService

        service = ModuleService()
        missing = [
            "optional-models\\MOSS-TTS-Local-Transformer-v1.5",
            "optional-models\\MOSS-Audio-Tokenizer-v2",
        ]
        self.assertFalse(
            service._has_partial_install(
                "speech",
                model_ready=False,
                runtime_ready=True,
                missing=missing,
            )
        )
        self.assertTrue(
            service._has_partial_install(
                "speech",
                model_ready=False,
                runtime_ready=True,
                missing=missing[:1],
            )
        )


if __name__ == "__main__":
    unittest.main()
