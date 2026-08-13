from __future__ import annotations

import json
import os
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import uvicorn

from desktop.backend.paths import ASSETS_DIR, LOGS_DIR, ROOT
from desktop.native.build_info import BUILD_INFO


HOST = "127.0.0.1"
PORT = 7862
APP_URL = f"http://{HOST}:{PORT}/projects"
ICON_PATH = ASSETS_DIR / "voicegrid.ico"
STARTUP_LOG = LOGS_DIR / "desktop-startup-legacy.log"


def startup_log(message: str, reset: bool = False) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    mode = "w" if reset else "a"
    with STARTUP_LOG.open(mode, encoding="utf-8") as handle:
        handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")


def json_request(path: str, method: str = "GET", timeout: float = 1.2) -> dict[str, Any] | None:
    request = urllib.request.Request(f"http://{HOST}:{PORT}{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def activate_existing_instance() -> bool:
    status = json_request("/api/v2/desktop/status")
    if not status or not status.get("native"):
        return False
    result = json_request("/api/v2/desktop/action/show", method="POST")
    return bool(result and result.get("ok"))


class NativeHost:
    def __init__(self) -> None:
        self.window: Any = None
        self.tray: Any = None
        self.server: uvicorn.Server | None = None
        self.server_thread: threading.Thread | None = None
        self.exiting = False
        self.maximized = False
        self.lock = threading.RLock()

    def start_server(self) -> None:
        from desktop.backend.server import app

        config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", access_log=False)
        self.server = uvicorn.Server(config)
        self.server_thread = threading.Thread(target=self.server.run, name="local-api", daemon=True)
        self.server_thread.start()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if self.server.started:
                return
            if not self.server_thread.is_alive():
                break
            time.sleep(.05)
        raise RuntimeError("本地服务启动失败，请确认 7862 端口没有被其他程序占用。")

    def command(self, action: str) -> str:
        with self.lock:
            if self.window is None:
                raise RuntimeError("桌面窗口尚未准备完成。")
            if action == "show":
                self.window.show()
                self.window.restore()
                return "shown"
            if action == "hide":
                self.window.hide()
                return "hidden"
            if action == "minimize":
                self.window.minimize()
                return "minimized"
            if action == "maximize":
                if self.maximized:
                    self.window.restore()
                    self.maximized = False
                    return "restored"
                self.window.maximize()
                self.maximized = True
                return "maximized"
            if action == "exit":
                threading.Thread(target=self.shutdown, name="app-shutdown", daemon=True).start()
                return "exiting"
        raise ValueError("不支持的窗口操作。")

    def on_closing(self, *_: Any) -> bool:
        if self.exiting:
            return True
        self.command("hide")
        return False

    def start_tray(self) -> None:
        import pystray
        from PIL import Image

        image = Image.open(ICON_PATH)
        menu = pystray.Menu(
            pystray.MenuItem("打开声格 VoiceGrid", lambda *_: self.command("show"), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda *_: self.command("exit")),
        )
        self.tray = pystray.Icon("voicegrid-legacy", image, BUILD_INFO.product, menu)
        threading.Thread(target=self.tray.run, name="system-tray", daemon=True).start()

    def shutdown(self) -> None:
        from desktop.backend.desktop_control import DESKTOP

        with self.lock:
            if self.exiting:
                return
            self.exiting = True
        DESKTOP.register(None)
        if self.server is not None:
            self.server.should_exit = True
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass

    def run(self) -> None:
        import webview
        from desktop.backend.desktop_control import DESKTOP

        self.start_server()
        DESKTOP.register(self.command)
        self.window = webview.create_window(
            f"{BUILD_INFO.window_title}（旧启动链）",
            APP_URL,
            js_api=NativeApi(self),
            width=1600,
            height=1000,
            min_size=(1040, 700),
            frameless=True,
            easy_drag=False,
            shadow=True,
            background_color="#090a0b",
            text_select=True,
        )
        self.window.events.closing += self.on_closing
        self.start_tray()
        try:
            webview.start(gui="edgechromium", icon=str(ICON_PATH), debug=False)
        finally:
            self.shutdown()
            if self.server_thread is not None:
                self.server_thread.join(timeout=10)


class NativeApi:
    def __init__(self, host: NativeHost) -> None:
        self.host = host

    def window_action(self, action: str) -> str:
        return self.host.command(action)

    def select_folder(self, initial: str = "") -> str | None:
        import webview

        start = Path(initial).expanduser() if initial else ROOT
        if start.is_file():
            start = start.parent
        if not start.is_dir():
            start = ROOT
        result = self.host.window.create_file_dialog(webview.FOLDER_DIALOG, directory=str(start))
        if not result:
            return None
        if isinstance(result, (list, tuple)):
            return str(result[0]) if result else None
        return str(result)

    def open_folder(self, path: str) -> bool:
        candidate = Path(path).expanduser().resolve()
        folder = candidate if candidate.is_dir() else candidate.parent
        if not folder.is_dir():
            raise FileNotFoundError("目录不存在。")
        os.startfile(str(folder))
        return True


def main() -> None:
    startup_log(f"收到旧启动链请求，程序目录：{ROOT}", reset=True)
    os.chdir(ROOT)
    if activate_existing_instance():
        return
    NativeHost().run()


def run_entrypoint() -> None:
    try:
        main()
    except BaseException as exc:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        try:
            startup_log("启动失败：\n" + detail)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    run_entrypoint()
