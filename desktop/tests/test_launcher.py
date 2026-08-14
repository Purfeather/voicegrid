from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "VoiceGrid \u58f0\u683c.exe"


class LauncherTests(unittest.TestCase):
    def test_launcher_is_small_windows_gui_executable(self) -> None:
        self.assertTrue(LAUNCHER.is_file())
        data = LAUNCHER.read_bytes()
        self.assertLessEqual(len(data), 512 * 1024)
        self.assertEqual(data[:2], b"MZ")
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        self.assertEqual(data[pe_offset:pe_offset + 4], b"PE\0\0")
        optional_header = pe_offset + 24
        subsystem = struct.unpack_from("<H", data, optional_header + 68)[0]
        self.assertEqual(subsystem, 2, "Launcher must use the Windows GUI subsystem.")

    def test_validation_uses_executable_directory_not_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [str(LAUNCHER), "--validate-only"],
                cwd=temporary,
                env={**os.environ, "VOICEGRID_LAUNCHER_HEADLESS": "1"},
                timeout=10,
                check=False,
            )
        self.assertEqual(result.returncode, 0)

    def test_standalone_copy_explains_missing_portable_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            isolated = Path(temporary)
            copied = isolated / LAUNCHER.name
            shutil.copy2(LAUNCHER, copied)
            result = subprocess.run(
                [str(copied), "--validate-only"],
                cwd=ROOT,
                env={**os.environ, "VOICEGRID_LAUNCHER_HEADLESS": "1"},
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            log = (isolated / "data" / "logs" / "launcher.log").read_text(encoding="utf-8")
            self.assertIn("Missing required files", log)

    def test_manifest_requests_no_elevation(self) -> None:
        manifest = (ROOT / "desktop" / "launcher" / "launcher.manifest").read_text(encoding="utf-8")
        self.assertIn('requestedExecutionLevel level="asInvoker"', manifest)
        self.assertNotIn('level="requireAdministrator"', manifest)


if __name__ == "__main__":
    unittest.main()
