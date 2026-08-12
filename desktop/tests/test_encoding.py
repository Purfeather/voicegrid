from __future__ import annotations

import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".venv", ".rebuild-cache", "__pycache__", "archive", "cache", "design-system", "dist", "LICENSES", "logs", "models", "node_modules", "outputs", "projects", "references"}
TEXT_EXTENSIONS = {".css", ".html", ".js", ".json", ".jsx", ".log", ".md", ".py", ".ts", ".tsx", ".txt"}


def project_files():
    for current, directories, filenames in os.walk(ROOT):
        directories[:] = [name for name in directories if name not in SKIP_DIRS]
        folder = Path(current)
        for filename in filenames:
            yield folder / filename


class EncodingPolicyTests(unittest.TestCase):
    def test_windows_command_files_are_ascii_crlf(self) -> None:
        command_files = [path for path in project_files() if path.suffix.lower() in {".bat", ".cmd"}]
        self.assertTrue(command_files, "没有找到可检查的 Windows 启动脚本")
        problems: list[str] = []
        for path in command_files:
            data = path.read_bytes()
            relative = path.relative_to(ROOT)
            if data.startswith(b"\xef\xbb\xbf"):
                problems.append(f"{relative}: 含 UTF-8 BOM")
            if any(byte > 0x7F for byte in data):
                problems.append(f"{relative}: 含非 ASCII 字节")
            if b"\n" in data and data.count(b"\r\n") != data.count(b"\n"):
                problems.append(f"{relative}: 不是完整 CRLF 换行")
        self.assertFalse(problems, "\n" + "\n".join(problems))

    def test_source_text_is_utf8_without_bom(self) -> None:
        problems: list[str] = []
        for path in project_files():
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            data = path.read_bytes()
            relative = path.relative_to(ROOT)
            if data.startswith(b"\xef\xbb\xbf"):
                problems.append(f"{relative}: 含 UTF-8 BOM")
                continue
            try:
                decoded = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                problems.append(f"{relative}: 不是有效 UTF-8（{exc}）")
                continue
            if "\ufffd" in decoded:
                problems.append(f"{relative}: 包含 Unicode 替代字符 U+FFFD")
        self.assertFalse(problems, "\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
