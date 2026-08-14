from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from desktop.backend import audio


class UploadStabilityTests(unittest.TestCase):
    def test_atomic_wav_upload_is_decodable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upload_dir = root / "uploads"
            sample = root / "source.wav"
            sf.write(sample, np.zeros(16000, dtype=np.float32), 16000, subtype="PCM_16")
            content = sample.read_bytes()
            with patch.object(audio, "ROOT", root), patch.object(audio, "UPLOADS_DIR", upload_dir):
                target = audio.save_upload("sample.wav", content)
                self.assertTrue(target.is_file())
                self.assertEqual(target.stat().st_size, len(content))
                self.assertFalse(list(upload_dir.glob("*.partial")))
                self.assertEqual(audio.analyze_audio(target)["sample_rate"], 16000)

    def test_empty_upload_is_rejected_without_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upload_dir = root / "uploads"
            with patch.object(audio, "ROOT", root), patch.object(audio, "UPLOADS_DIR", upload_dir):
                with self.assertRaisesRegex(ValueError, "上传文件为空"):
                    audio.save_upload("empty.wav", b"")
                self.assertFalse(upload_dir.exists())

    def test_invalid_mp3_returns_classified_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upload_dir = root / "uploads"
            with patch.object(audio, "ROOT", root), patch.object(audio, "UPLOADS_DIR", upload_dir):
                target = audio.save_upload("broken.mp3", b"not an mp3 file")
                with self.assertRaisesRegex(ValueError, "MP3"):
                    audio.analyze_audio(target)
                target.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()