from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
class VersionConsistencyTests(unittest.TestCase):
    def test_machine_readable_versions_match_build_manifest(self) -> None:
        build = json.loads((ROOT / "build.json").read_text(encoding="utf-8"))
        package = json.loads((ROOT / "desktop" / "frontend" / "package.json").read_text(encoding="utf-8"))
        package_lock = json.loads((ROOT / "desktop" / "frontend" / "package-lock.json").read_text(encoding="utf-8"))

        self.assertEqual(package["version"], build["version"])
        self.assertEqual(package_lock["version"], build["version"])
        self.assertEqual(package_lock["packages"][""]["version"], build["version"])
        self.assertTrue(build["build_id"])

    def test_visible_shells_use_display_name(self) -> None:
        for relative in (
            "desktop/host.py",
            "desktop/splash_host.py",
            "desktop/splash.html",
            "desktop/frontend/src/components/TitleBar.tsx",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("VoiceGrid", source, relative)

    def test_runtime_build_info_comes_from_manifest(self) -> None:
        from desktop.native.build_info import BUILD_INFO

        build = json.loads((ROOT / "build.json").read_text(encoding="utf-8"))
        self.assertEqual(BUILD_INFO.product, build["product"])
        self.assertEqual(BUILD_INFO.brand, build["brand"])
        self.assertEqual(BUILD_INFO.author, build["author"])
        self.assertEqual(BUILD_INFO.version, build["version"])

    def test_splash_shells_use_the_accent_brand_icon(self) -> None:
        expected_asset = "voicegrid-icon-accent"
        for relative in (
            "desktop/host.py",
            "desktop/splash_host.py",
            "desktop/splash.html",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(expected_asset, source, relative)
            self.assertNotIn("voicegrid-icon-white", source, relative)

        self.assertTrue((ROOT / "desktop" / "assets" / "voicegrid-icon-accent.svg").is_file())
        self.assertTrue((ROOT / "desktop" / "assets" / "voicegrid-icon-accent.png").is_file())


if __name__ == "__main__":
    unittest.main()
