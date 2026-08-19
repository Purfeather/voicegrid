from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
        self.assertEqual(self.module.VERSION, "1.0.2")
        self.assertEqual(
            self.module.BUILD["build_id"],
            "VOICEGRID-1.0.2-20260818",
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

    def test_only_offline_archive_uses_fixed_four_gib_volumes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release_root = Path(temporary)
            (release_root / "artifacts").mkdir()
            tool = release_root / "tools" / "7zip-26.02" / "7z.exe"
            tool.parent.mkdir(parents=True)
            tool.touch()

            commands: list[list[str]] = []

            def fake_run(command: list[str], _cwd: Path) -> None:
                commands.append(command)
                if command[1] != "a":
                    return
                archive = Path(command[-2])
                output = archive.with_name(archive.name + ".001") if "-v4g" in command else archive
                output.write_bytes(b"archive")

            outputs: dict[str, list[Path]] = {}
            for flavor in ("standard", "source", "offline"):
                stage = release_root / "staging" / self.module.PACKAGE_NAMES[flavor]
                stage.mkdir(parents=True)
                (stage / "payload.bin").write_bytes(b"payload")
                with mock.patch.object(self.module, "run", side_effect=fake_run):
                    outputs[flavor] = self.module.archive_stage(release_root, flavor)

            archive_commands = [command for command in commands if command[1] == "a"]
            self.assertEqual(len(archive_commands), 1)
            self.assertIn("-v4g", archive_commands[0])
            self.assertEqual(
                archive_commands[0][-1],
                self.module.PACKAGE_NAMES["offline"],
            )
            self.assertEqual(outputs["standard"][0].suffix, ".zip")
            self.assertEqual(outputs["source"][0].suffix, ".zip")
            self.assertTrue(outputs["offline"][0].name.endswith(".zip.001"))


if __name__ == "__main__":
    unittest.main()
