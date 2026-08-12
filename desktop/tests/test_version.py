from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INTERNAL_VERSION = "2.0.0-dev"
DISPLAY_VERSION = "2.0"


class VersionConsistencyTests(unittest.TestCase):
    def test_machine_readable_versions_match_build_manifest(self) -> None:
        build = json.loads((ROOT / "build.json").read_text(encoding="utf-8"))
        package = json.loads((ROOT / "desktop" / "frontend" / "package.json").read_text(encoding="utf-8"))
        package_lock = json.loads((ROOT / "desktop" / "frontend" / "package-lock.json").read_text(encoding="utf-8"))

        self.assertEqual(build["version"], INTERNAL_VERSION)
        self.assertEqual(package["version"], INTERNAL_VERSION)
        self.assertEqual(package_lock["version"], INTERNAL_VERSION)
        self.assertEqual(package_lock["packages"][""]["version"], INTERNAL_VERSION)
        self.assertEqual(build["build_id"], "LRYY-VOICEGRID-2.0-DEV-20260812")

    def test_visible_shells_use_display_name(self) -> None:
        for relative in (
            "desktop/host.py",
            "desktop/splash_host.py",
            "desktop/splash.html",
            "desktop/frontend/src/components/TitleBar.tsx",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(DISPLAY_VERSION, source, relative)

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
