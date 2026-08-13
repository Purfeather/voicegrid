from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
IDENTITY_PATH = ROOT / "desktop" / "splash-identity.json"
TEXT_SUFFIXES = {".bat", ".cmd", ".cs", ".css", ".html", ".json", ".log", ".md", ".py", ".svg", ".toml", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml"}
LEGACY_MARKERS = (
    "Wang " + "Xiaohan",
    "Long" + "Rong",
    "long" + "rong",
    "LR" + "YY",
    "AI " + "配音台",
    "AI" + "配音台",
)
ICON_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / value.decode("utf-8") for value in result.stdout.split(b"\0") if value]


class IdentityBoundaryTests(unittest.TestCase):
    def test_splash_identity_values_exist_only_in_identity_config(self) -> None:
        identity = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
        protected_values = tuple(str(identity[key]) for key in ("organization", "author"))
        violations: list[str] = []
        for path in tracked_files():
            if path == IDENTITY_PATH or path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
                continue
            content = path.read_text(encoding="utf-8")
            if any(value in content for value in protected_values):
                violations.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(violations, [])

    def test_legacy_identity_markers_and_paths_are_absent(self) -> None:
        violations: list[str] = []
        for path in tracked_files():
            relative = path.relative_to(ROOT).as_posix()
            forbidden_path_parts = ("long" + "rong", "voicegrid-icon-" + "white")
            if any(marker.lower() in relative.lower() for marker in forbidden_path_parts):
                violations.append(relative)
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
                continue
            content = path.read_text(encoding="utf-8")
            if any(marker in content for marker in LEGACY_MARKERS):
                violations.append(relative)
        self.assertEqual(violations, [])

    def test_bootstrap_and_public_contracts_do_not_expose_identity(self) -> None:
        from desktop.backend.server import bootstrap_core

        self.assertNotIn("brand", bootstrap_core())
        generated = (ROOT / "desktop" / "frontend" / "src" / "api.generated.ts").read_text(encoding="utf-8")
        self.assertNotIn("brand:", generated)
        schema_source = (ROOT / "desktop" / "backend" / "schemas.py").read_text(encoding="utf-8")
        for field in ("organization", "author", "brand"):
            self.assertNotRegex(schema_source, rf"(?m)^\s*{field}\s*:")

    def test_titlebar_contains_only_the_product_identity(self) -> None:
        source = (ROOT / "desktop" / "frontend" / "src" / "components" / "TitleBar.tsx").read_text(encoding="utf-8")
        self.assertIn("<strong>{product}</strong>", source)
        self.assertNotIn("<div className={styles.brand}><strong>{product}</strong><span>", source)


class IconAndLauncherConsistencyTests(unittest.TestCase):
    def test_ico_has_all_required_sizes(self) -> None:
        with Image.open(ROOT / "desktop" / "assets" / "voicegrid.ico") as image:
            sizes = set(image.info.get("sizes", set()))
        self.assertEqual(sizes, {(size, size) for size in ICON_SIZES})

    def test_generated_icon_rasters_match_the_single_builder(self) -> None:
        builder_path = ROOT / "desktop" / "assets" / "build_voicegrid_icon.py"
        spec = importlib.util.spec_from_file_location("voicegrid_icon_builder", builder_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        expected_accent = module.render_accent(256)
        with Image.open(ROOT / "desktop" / "assets" / "voicegrid-icon-accent.png") as actual:
            self.assertEqual(actual.convert("RGBA").tobytes(), expected_accent.tobytes())
        with Image.open(ROOT / "desktop" / "assets" / "voicegrid.ico") as icon:
            for size in ICON_SIZES:
                icon.size = (size, size)
                self.assertEqual(icon.convert("RGBA").tobytes(), module.render_system(size).tobytes())

    def test_svg_and_react_marks_share_the_master_geometry(self) -> None:
        paths = (
            ROOT / "desktop" / "assets" / "voicegrid-icon.svg",
            ROOT / "desktop" / "assets" / "voicegrid-icon-accent.svg",
            ROOT / "desktop" / "frontend" / "src" / "components" / "VoiceGridMark.tsx",
        )
        geometry = ('x="5" y="5" width="54" height="54" rx="13"', 'd="M15 29v6m8-11v16m8-23v30m8-24v18m8-13v8"', 'x="45" y="15" width="6" height="6"', 'x="49" y="23" width="5" height="5"')
        for path in paths:
            source = path.read_text(encoding="utf-8")
            for fragment in geometry:
                self.assertIn(fragment, source, path.name)

    def test_launcher_metadata_is_product_only(self) -> None:
        executable = ROOT / "声格 VoiceGrid.exe"
        script = (
            "$v=(Get-Item -LiteralPath $env:VOICEGRID_EXE_PATH).VersionInfo;"
            "[pscustomobject]@{ProductName=$v.ProductName;FileDescription=$v.FileDescription;"
            "CompanyName=$v.CompanyName;Copyright=$v.LegalCopyright;ProductVersion=$v.ProductVersion;"
            "OriginalFilename=$v.OriginalFilename}|ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            env={**os.environ, "VOICEGRID_EXE_PATH": str(executable)},
        )
        metadata = json.loads(result.stdout)
        build = json.loads((ROOT / "build.json").read_text(encoding="utf-8"))
        identity = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(metadata["ProductName"], build["product"])
        self.assertEqual(metadata["FileDescription"], build["product"])
        self.assertEqual(metadata["CompanyName"], "VoiceGrid")
        self.assertFalse(str(metadata.get("Copyright") or "").strip())
        self.assertEqual(metadata["ProductVersion"], build["version"])
        self.assertEqual(metadata["OriginalFilename"], executable.name)
        serialized = json.dumps(metadata, ensure_ascii=False)
        self.assertNotIn(identity["organization"], serialized)
        self.assertNotIn(identity["author"], serialized)


if __name__ == "__main__":
    unittest.main()
