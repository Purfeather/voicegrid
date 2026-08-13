from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEXT_EXTENSIONS = {".css", ".html", ".js", ".json", ".jsx", ".log", ".md", ".py", ".ts", ".tsx", ".txt"}


def project_files():
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    for relative in result.stdout.decode("utf-8").split("\0"):
        if relative:
            path = ROOT / relative
            if path.is_file():
                yield path


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
