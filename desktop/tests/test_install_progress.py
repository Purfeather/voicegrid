from __future__ import annotations

import unittest

from desktop.backend.module_service import _clean_install_output


class InstallProgressTests(unittest.TestCase):
    def test_install_output_removes_control_sequences_and_carriage_returns(self) -> None:
        value = "\x1b[2K\r\x1b[32mVOICEGRID_INSTALL_PROGRESS {}\x1b[0m"
        self.assertEqual(_clean_install_output(value), "VOICEGRID_INSTALL_PROGRESS {}")

    def test_install_output_drops_non_printable_bytes(self) -> None:
        self.assertEqual(_clean_install_output("model\x00file\x07"), "modelfile")


if __name__ == "__main__":
    unittest.main()