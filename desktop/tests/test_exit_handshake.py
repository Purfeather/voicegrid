from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from desktop.host import NativeHost


class ExitHandshakeTests(unittest.TestCase):
    def test_graceful_exit_waits_for_successful_frontend_receipt(self) -> None:
        host = NativeHost()
        host.main_ready = True
        window = Mock()
        window.evaluate_js.side_effect = lambda _: host.exit_save_completed(True)
        host.window = window
        with patch("desktop.host.startup_log"), patch.object(host, "shutdown") as shutdown:
            host._graceful_exit()
        window.evaluate_js.assert_called_once()
        shutdown.assert_called_once()
        self.assertTrue(host.exit_save_succeeded)

    def test_failed_dispatch_still_exits_without_claiming_success(self) -> None:
        host = NativeHost()
        host.main_ready = True
        window = Mock()
        window.evaluate_js.side_effect = RuntimeError("webview unavailable")
        host.window = window
        with patch("desktop.host.startup_log"), patch.object(host, "shutdown") as shutdown:
            host._graceful_exit()
        shutdown.assert_called_once()
        self.assertFalse(host.exit_save_succeeded)

    def test_failed_frontend_receipt_does_not_claim_saved_exit(self) -> None:
        host = NativeHost()
        host.main_ready = True
        window = Mock()
        window.evaluate_js.side_effect = lambda _: host.exit_save_completed(False)
        host.window = window
        with patch.object(host, "shutdown") as shutdown:
            host._graceful_exit()
        shutdown.assert_called_once()
        self.assertFalse(host.exit_save_succeeded)


if __name__ == "__main__":
    unittest.main()
