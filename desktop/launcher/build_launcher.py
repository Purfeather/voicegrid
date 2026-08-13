from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_DIR = Path(__file__).resolve().parent
OUTPUT_NAME = "\u58f0\u683c VoiceGrid.exe"
OUTPUT_PATH = ROOT / OUTPUT_NAME


def csharp_literal(value: str) -> str:
    return '"' + "".join(
        f"\\u{ord(character):04x}" if ord(character) > 0x7F else "\\\"" if character == '"' else "\\\\" if character == "\\" else character
        for character in value
    ) + '"'


def numeric_version(version: str) -> str:
    parts = [int(value) for value in re.findall(r"\d+", version)[:4]]
    return ".".join(str(value) for value in (parts + [0, 0, 0, 0])[:4])


def find_compiler() -> Path:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = [
        windows / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
        windows / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Microsoft .NET Framework C# compiler was not found.")


def assembly_info(build: dict[str, str]) -> str:
    version = str(build["version"])
    file_version = numeric_version(version)
    product = str(build["product"])
    company = "VoiceGrid"
    return "\n".join(
        [
            "using System.Reflection;",
            f"[assembly: AssemblyTitle({csharp_literal(product)})]",
            f"[assembly: AssemblyDescription({csharp_literal(product)})]",
            f"[assembly: AssemblyCompany({csharp_literal(company)})]",
            f"[assembly: AssemblyProduct({csharp_literal(product)})]",
            f"[assembly: AssemblyCopyright({csharp_literal('')})]",
            f"[assembly: AssemblyVersion({csharp_literal(file_version)})]",
            f"[assembly: AssemblyFileVersion({csharp_literal(file_version)})]",
            f"[assembly: AssemblyInformationalVersion({csharp_literal(version)})]",
            "",
        ]
    )


def launcher_identity(build: dict[str, str]) -> str:
    return "\n".join(
        [
            "internal static class LauncherIdentity",
            "{",
            f"    internal const string ProductName = {csharp_literal(str(build['product']))};",
            "}",
            "",
        ]
    )


def build_launcher() -> Path:
    build = json.loads((ROOT / "build.json").read_text(encoding="utf-8"))
    compiler = find_compiler()
    cache_root = ROOT / ".rebuild-cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voicegrid-launcher-", dir=cache_root) as temporary:
        temporary_path = Path(temporary)
        assembly_path = temporary_path / "AssemblyInfo.cs"
        identity_path = temporary_path / "LauncherIdentity.cs"
        candidate = temporary_path / OUTPUT_NAME
        assembly_path.write_text(assembly_info(build), encoding="utf-8", newline="\n")
        identity_path.write_text(launcher_identity(build), encoding="utf-8", newline="\n")
        command = [
            str(compiler),
            "/nologo",
            "/target:winexe",
            "/platform:anycpu",
            "/optimize+",
            "/codepage:65001",
            f"/win32icon:{ROOT / 'desktop' / 'assets' / 'voicegrid.ico'}",
            f"/win32manifest:{LAUNCHER_DIR / 'launcher.manifest'}",
            f"/out:{candidate}",
            str(LAUNCHER_DIR / "VoiceGridLauncher.cs"),
            str(assembly_path),
            str(identity_path),
        ]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            raise RuntimeError((result.stdout + "\n" + result.stderr).strip())
        if not candidate.is_file() or candidate.stat().st_size > 512 * 1024:
            raise RuntimeError("Launcher output is missing or exceeds the 512 KiB size budget.")
        os.replace(candidate, OUTPUT_PATH)
    return OUTPUT_PATH


if __name__ == "__main__":
    output = build_launcher()
    print(f"Built launcher: {output} ({output.stat().st_size} bytes)")
