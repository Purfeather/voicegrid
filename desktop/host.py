from __future__ import annotations

import ctypes
import faulthandler
import json
import os
import secrets
import socketserver
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import webview


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_DIR = ROOT / "desktop"
ASSETS_DIR = DESKTOP_DIR / "assets"
LOGS_DIR = Path(os.environ.get("MOSS_TTS_LOGS_DIR", ROOT / "logs")).resolve()
WEBVIEW_PROFILE = Path(os.environ.get("MOSS_TTS_WEBVIEW_PROFILE", ROOT / "data" / "cache" / "webview2")).resolve()
SPLASH_PATH = DESKTOP_DIR / "splash.html"
ICON_PATH = ASSETS_DIR / "voicegrid.ico"
HOST = "127.0.0.1"
PORT = int(os.environ.get("MOSS_TTS_PORT", "7862"))
APP_URL = f"http://{HOST}:{PORT}/projects"
STARTUP_LOG = LOGS_DIR / "desktop-startup.log"
TRACE_PATH = Path(os.environ.get("MOSS_TTS_TRACE_PATH", LOGS_DIR / "startup-trace-latest.jsonl")).resolve()
MUTEX_NAME = os.environ.get("MOSS_TTS_MUTEX_NAME", r"Local\LongRongAIStudioV2")
WINDOW_TITLE = os.environ.get("MOSS_TTS_WINDOW_TITLE", "声格 VoiceGrid 2.0")
STARTED_AT = time.perf_counter()


class StartupTrace:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def record(self, event: str, phase: str, message: str = "", **extra: Any) -> None:
        payload = {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "elapsed_ms": round((time.perf_counter() - STARTED_AT) * 1000),
            "event": event,
            "phase": phase,
            "message": message,
            "pid": os.getpid(),
            "thread": threading.current_thread().name,
            **extra,
        }
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")


TRACE: StartupTrace | None = None


def startup_log(message: str, reset: bool = False) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    mode = "w" if reset else "a"
    with STARTUP_LOG.open(mode, encoding="utf-8", newline="\n") as handle:
        handle.write(f"[{datetime.now().isoformat(timespec='milliseconds')}] {message}\n")


def json_request(path: str, method: str = "GET", timeout: float = .6) -> dict[str, Any] | None:
    request = urllib.request.Request(f"http://{HOST}:{PORT}{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


class WindowsMutex:
    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str) -> None:
        self.handle: int | None = None
        self.already_exists = False
        if os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = int(handle)
        self.already_exists = ctypes.get_last_error() == self.ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self.handle is None or os.name != "nt":
            return
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self.handle))
        self.handle = None


def activate_existing_instance() -> bool:
    status = json_request("/api/v2/desktop/status", timeout=.35)
    if not status or not status.get("native") or not status.get("ready"):
        return False
    result = json_request("/api/v2/desktop/action/show", method="POST", timeout=.5)
    return bool(result and result.get("ok"))


class NativeSplash:
    def __init__(self, host: "NativeHost") -> None:
        self.host = host
        self.ready = threading.Event()
        self.close_requested = threading.Event()
        self.show_requested = threading.Event()
        self.minimize_requested = threading.Event()
        self.thread = threading.Thread(target=self._run, name="native-splash", daemon=True)
        self.error: BaseException | None = None

    def start(self) -> None:
        self.thread.start()
        if not self.ready.wait(1.4):
            raise RuntimeError("品牌启动页未能在 1.4 秒内创建。")
        if self.error is not None:
            raise RuntimeError(f"品牌启动页创建失败：{self.error}") from self.error

    def close(self) -> None:
        self.close_requested.set()

    def show(self) -> None:
        self.show_requested.set()

    def minimize(self) -> None:
        self.minimize_requested.set()

    def _run(self) -> None:
        try:
            import tkinter as tk

            root = tk.Tk()
            root.title(WINDOW_TITLE)
            root.configure(bg="#090a0b")
            root.minsize(720, 520)
            try:
                root.iconbitmap(default=str(ICON_PATH))
            except Exception:
                pass
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            width = min(1600, max(920, int(screen_width * .9)))
            height = min(1000, max(680, int(screen_height * .86)))
            x = max(0, (screen_width - width) // 2)
            y = max(0, (screen_height - height) // 2)
            root.geometry(f"{width}x{height}+{x}+{y}")

            shell = tk.Frame(root, bg="#090a0b", padx=44, pady=36)
            shell.pack(fill="both", expand=True)
            brand = tk.Frame(shell, bg="#090a0b")
            brand.pack(fill="x")
            try:
                from PIL import Image, ImageTk
                mark_image = Image.open(ASSETS_DIR / "voicegrid-icon-accent.png").resize((40, 40), Image.Resampling.LANCZOS)
                self._brand_icon = ImageTk.PhotoImage(mark_image)
                mark = tk.Label(brand, image=self._brand_icon, bg="#090a0b")
            except Exception:
                mark = tk.Label(brand, text="VG", bg="#181b1e", fg="#f3ff00", width=4, height=2, font=("Segoe UI", 10, "bold"))
            mark.pack(side="left")
            brand_copy = tk.Frame(brand, bg="#090a0b")
            brand_copy.pack(side="left", padx=12)
            tk.Label(brand_copy, text="声格 VoiceGrid", bg="#090a0b", fg="#f4f6f8", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
            tk.Label(brand_copy, text="龙融影业 · 2.0", bg="#090a0b", fg="#9aa2ad", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(3, 0))
            tk.Label(brand_copy, text="作者：Wang Xiaohan", bg="#090a0b", fg="#9aa2ad", font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))

            content = tk.Frame(shell, bg="#090a0b")
            content.pack(fill="both", expand=True, pady=(34, 0))
            content.grid_columnconfigure(0, weight=3, uniform="content")
            content.grid_columnconfigure(1, weight=2, uniform="content")
            content.grid_rowconfigure(0, weight=1)

            identity = tk.Frame(content, bg="#090a0b")
            identity.grid(row=0, column=0, sticky="nsew", padx=(0, 54))
            tk.Label(identity, text="—  LOCAL VOICE PRODUCTION", bg="#090a0b", fg="#f3ff00", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(60, 22))
            tk.Label(identity, text="让声音先醒来，", bg="#090a0b", fg="#f4f6f8", font=("Microsoft YaHei UI", 38, "bold")).pack(anchor="w")
            tk.Label(identity, text="模型稍后就绪。", bg="#090a0b", fg="#9aa2ad", font=("Microsoft YaHei UI", 38)).pack(anchor="w", pady=(0, 24))
            description = "正在准备本地项目、音色资产与离线服务。\nMOSS-TTS 1.5 4B 仍会保持懒加载，只有开始生成时才进入显存。"
            tk.Label(identity, text=description, justify="left", bg="#090a0b", fg="#9aa2ad", font=("Microsoft YaHei UI", 11), pady=8).pack(anchor="w")

            card = tk.Frame(content, bg="#111315", highlightbackground="#2a2e33", highlightthickness=1, padx=24, pady=24)
            card.grid(row=0, column=1, sticky="nsew", pady=(40, 40))
            tk.Label(card, text="STARTUP SEQUENCE", bg="#111315", fg="#9aa2ad", font=("Segoe UI", 9, "bold")).pack(anchor="w")
            title_var = tk.StringVar(value="正在启动工作台")
            detail_var = tk.StringVar(value="窗口控制已经可用，后台服务将在独立线程中继续准备。")
            elapsed_var = tk.StringVar(value="准备中")
            tk.Label(card, textvariable=title_var, bg="#111315", fg="#f4f6f8", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", pady=(5, 22))
            segment_row = tk.Frame(card, bg="#111315")
            segment_row.pack(fill="x", pady=(0, 20))
            segments = []
            for _ in range(7):
                segment = tk.Frame(segment_row, bg="#2a2e33", height=3)
                segment.pack(side="left", fill="x", expand=True, padx=(0, 5))
                segments.append(segment)
            stage_var = tk.StringVar(value="正在创建桌面窗口")
            tk.Label(card, textvariable=stage_var, bg="#111315", fg="#f4f6f8", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
            tk.Label(card, textvariable=detail_var, wraplength=410, justify="left", bg="#111315", fg="#9aa2ad", font=("Microsoft YaHei UI", 9)).pack(anchor="w", fill="x", pady=(7, 18))

            diagnostic = tk.Frame(card, bg="#111315")
            action_row = tk.Frame(diagnostic, bg="#111315")
            action_row.pack(fill="x")

            def action_button(text: str, command: Callable[[], Any], primary: bool = False) -> None:
                tk.Button(
                    action_row,
                    text=text,
                    command=command,
                    relief="flat",
                    borderwidth=0,
                    padx=12,
                    pady=8,
                    bg="#f3ff00" if primary else "#181b1e",
                    fg="#090a0b" if primary else "#f4f6f8",
                    activebackground="#dce800" if primary else "#202429",
                    font=("Microsoft YaHei UI", 9, "bold" if primary else "normal"),
                ).pack(side="left", padx=(0, 7))

            action_button("继续等待", self.host.continue_waiting, primary=True)
            action_button("重试", self.host.retry_startup)
            action_button("打开日志", self.host.open_log_folder)
            action_button("退出", lambda: threading.Thread(target=self.host.shutdown, name="splash-exit", daemon=True).start())
            footer = tk.Frame(card, bg="#111315")
            footer.pack(side="bottom", fill="x", pady=(18, 0))
            tk.Label(footer, text="2.0.0-dev", bg="#111315", fg="#9aa2ad", font=("Consolas", 8)).pack(side="left")
            tk.Label(footer, textvariable=elapsed_var, bg="#111315", fg="#9aa2ad", font=("Consolas", 8)).pack(side="right")

            phase_names = {
                "shell": "正在创建桌面窗口",
                "backend_import": "正在载入本地服务",
                "database": "正在检查本地数据库",
                "project_recovery": "正在恢复项目状态",
                "api": "正在启动本地接口",
                "frontend": "正在载入项目中心",
                "ready": "工作台已就绪",
                "slow": "启动时间超出预期",
                "failed": "启动未能完成",
            }
            phases = ["shell", "backend_import", "database", "project_recovery", "api", "frontend", "ready"]
            diagnostic_visible = False

            def tick() -> None:
                nonlocal diagnostic_visible
                if self.close_requested.is_set() or self.host.exiting:
                    root.destroy()
                    return
                if self.show_requested.is_set():
                    self.show_requested.clear()
                    root.deiconify()
                    root.lift()
                    root.focus_force()
                if self.minimize_requested.is_set():
                    self.minimize_requested.clear()
                    root.iconify()
                status = self.host.startup_status()
                phase = status["phase"]
                active_phase = status.get("active_phase") or phase
                stage_var.set(phase_names.get(phase, phase_names.get(active_phase, "正在准备工作台")))
                detail_var.set(status.get("detail") or status.get("message") or "正在准备本地服务。")
                elapsed_ms = int(status.get("elapsed_ms") or 0)
                elapsed_var.set(f"{elapsed_ms / 1000:.1f} 秒" if elapsed_ms >= 1000 else f"{elapsed_ms} 毫秒")
                index = max(0, phases.index(active_phase) if active_phase in phases else 0)
                for item_index, segment in enumerate(segments):
                    segment.configure(bg="#f3ff00" if item_index < index or active_phase == "ready" else "#2a2e33")
                should_show = phase in {"slow", "failed"}
                if should_show and not diagnostic_visible:
                    diagnostic.pack(fill="x", pady=(6, 12), before=footer)
                    diagnostic_visible = True
                elif not should_show and diagnostic_visible:
                    diagnostic.pack_forget()
                    diagnostic_visible = False
                root.after(100, tick)

            def close_from_window() -> None:
                threading.Thread(target=self.host.shutdown, name="splash-close", daemon=True).start()
                root.destroy()

            root.protocol("WM_DELETE_WINDOW", close_from_window)
            root.update_idletasks()
            root.deiconify()
            root.lift()
            self.ready.set()
            if TRACE is not None:
                TRACE.record("splash_visible", "shell", "原生品牌启动页已显示并进入 GUI 消息循环")
            startup_log("原生品牌启动页已显示，GUI 消息循环已启动")
            root.after(50, tick)
            root.mainloop()
        except BaseException as exc:
            self.error = exc
            self.ready.set()


class NativeSplashProcess:
    def __init__(self, host: "NativeHost") -> None:
        self.host = host
        self.token = secrets.token_hex(16)
        self.ready = threading.Event()
        self.close_requested = threading.Event()
        self.server: socketserver.ThreadingTCPServer | None = None
        self.server_thread: threading.Thread | None = None
        self.process: subprocess.Popen | None = None
        self.command_lock = threading.RLock()
        self.command_id = 0
        self.window_command = ""

    def start(self) -> None:
        controller = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                try:
                    request = json.loads(self.rfile.readline(65536).decode("utf-8"))
                    if request.get("token") != controller.token:
                        response = {"ok": False, "error": "unauthorized"}
                    else:
                        response = controller._handle(str(request.get("action") or "status"))
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server((HOST, 0), Handler)
        port = int(self.server.server_address[1])
        self.server_thread = threading.Thread(target=self.server.serve_forever, name="splash-ipc", daemon=True)
        self.server_thread.start()
        command = [sys.executable, "-m", "desktop.splash_host", "--port", str(port), "--token", self.token]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(command, cwd=ROOT, env=os.environ.copy(), creationflags=creationflags)
        if not self.ready.wait(1.4):
            if self.process.poll() is not None:
                raise RuntimeError("品牌启动页辅助进程提前退出。")
            raise RuntimeError("品牌启动页未能在 1.4 秒内创建。")

    def _handle(self, action: str) -> dict[str, Any]:
        if action == "visible":
            if not self.ready.is_set():
                self.ready.set()
                if TRACE is not None:
                    TRACE.record("splash_visible", "shell", "原生品牌启动页已显示并进入 GUI 消息循环")
                startup_log("原生品牌启动页已显示，GUI 消息循环已启动")
            return {"ok": True}
        if action == "continue":
            return {"ok": True, "status": self.host.continue_waiting()}
        if action == "retry":
            return {"ok": True, "status": self.host.retry_startup()}
        if action == "logs":
            return {"ok": self.host.open_log_folder()}
        if action == "exit":
            threading.Thread(target=self.host.shutdown, name="splash-exit", daemon=True).start()
            return {"ok": True}
        with self.command_lock:
            command_id = self.command_id
            window_command = self.window_command
        return {
            "ok": True,
            "status": self.host.startup_status(),
            "close_requested": self.close_requested.is_set() or self.host.exiting,
            "command_id": command_id,
            "window_command": window_command,
        }

    def _command(self, command: str) -> None:
        with self.command_lock:
            self.command_id += 1
            self.window_command = command

    def show(self) -> None:
        self._command("show")

    def minimize(self) -> None:
        self._command("minimize")

    def close(self) -> None:
        self.close_requested.set()

    def stop(self) -> None:
        self.close()
        if self.process is not None:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=2)
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.server_thread is not None and self.server_thread.is_alive():
            self.server_thread.join(timeout=2)


NativeSplash = NativeSplashProcess


class NativeHost:
    def __init__(self) -> None:
        self.window: Any = None
        self.tray: Any = None
        self.server: Any = None
        self.server_thread: threading.Thread | None = None
        self.backend_worker: threading.Thread | None = None
        self.desktop_control: Any = None
        self.lock = threading.RLock()
        self.init_lock = threading.Lock()
        self.shutdown_lock = threading.Lock()
        self.exiting = False
        self.shutdown_started = False
        self.maximized = False
        self.restore_window_rect: tuple[int, int, int, int] | None = None
        self.main_ready = False
        self.native_splash: NativeSplash | None = None
        self.api_ready = threading.Event()
        self.webview_loaded = threading.Event()
        self.frontend_document_loaded = threading.Event()
        self.frontend_ready_event = threading.Event()
        self.main_window_geometry: tuple[int, int, int | None, int | None] = (1600, 1000, None, None)
        self.phase = "shell"
        self.message = "正在创建桌面窗口"
        self.detail = "窗口控制已经可用，后台服务将在独立线程中继续准备。"
        self.error = ""
        self.slow_deadline = time.monotonic() + 5.0
        self.slow_generation = 0
        self.slow_reported_generation = -1
        self.watchdog_stop = threading.Event()

    def set_phase(self, phase: str, message: str) -> None:
        with self.lock:
            if self.exiting:
                return
            self.phase = phase
            self.message = message
            self.detail = message
            if phase != "failed":
                self.error = ""
        if TRACE is not None:
            TRACE.record("phase", phase, message)
        startup_log(f"{phase}: {message}")

    def fail(self, exc: BaseException) -> None:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        with self.lock:
            self.phase = "failed"
            self.message = "启动未能完成"
            self.detail = str(exc) or type(exc).__name__
            self.error = detail
        startup_log("启动失败：\n" + detail)
        if TRACE is not None:
            TRACE.record("failed", "failed", str(exc), traceback=detail)

    def startup_status(self) -> dict[str, Any]:
        with self.lock:
            phase = self.phase
            message = self.message
            detail = self.detail
            error = self.error
            generation = self.slow_generation
            deadline = self.slow_deadline
        elapsed_ms = round((time.perf_counter() - STARTED_AT) * 1000)
        active_phase = phase
        if phase not in {"ready", "failed"} and time.monotonic() >= deadline:
            phase = "slow"
            message = "启动时间超出预期"
            detail = f"当前阶段：{self.detail}。仍在进行的安全初始化不会被强制终止。"
            if self.slow_reported_generation != generation:
                self.slow_reported_generation = generation
                if TRACE is not None:
                    TRACE.record("slow", "slow", detail, active_phase=active_phase)
                threading.Thread(
                    target=self._dump_thread_stacks,
                    args=(f"Startup exceeded 5 seconds during phase: {active_phase}",),
                    name="slow-start-dump",
                    daemon=True,
                ).start()
        return {
            "phase": phase,
            "active_phase": active_phase,
            "message": message,
            "detail": detail,
            "error": error,
            "elapsed_ms": elapsed_ms,
            "ready": self.main_ready,
            "retry_allowed": phase == "failed" and not bool(self.backend_worker and self.backend_worker.is_alive()),
            "trace_path": str(TRACE_PATH),
        }

    def public_status(self) -> dict[str, Any]:
        status = self.startup_status()
        return {"ready": self.main_ready, "phase": status["phase"], "elapsed_ms": status["elapsed_ms"]}

    def continue_waiting(self) -> dict[str, Any]:
        with self.lock:
            self.slow_generation += 1
            self.slow_deadline = time.monotonic() + 5.0
        if TRACE is not None:
            TRACE.record("continue_waiting", self.phase, "用户选择继续等待")
        return self.startup_status()

    def retry_startup(self) -> dict[str, Any]:
        with self.lock:
            worker_alive = bool(self.backend_worker and self.backend_worker.is_alive())
            if self.phase != "failed" or worker_alive:
                return self.startup_status()
            self.slow_generation += 1
            self.slow_deadline = time.monotonic() + 5.0
            self.phase = "shell"
            self.message = "正在重新准备本地服务"
            self.detail = self.message
            self.error = ""
            self.backend_worker = threading.Thread(target=self._retry_worker, name="backend-retry", daemon=True)
            self.backend_worker.start()
        if TRACE is not None:
            TRACE.record("retry", "shell", "用户请求重试启动")
        return self.startup_status()

    def _retry_worker(self) -> None:
        if self.server_thread is not None and self.server_thread.is_alive() and json_request("/api/v2/health"):
            self.set_phase("frontend", "正在创建项目中心窗口")
            self.api_ready.set()
            return
        self.initialize_backend()

    def open_log_folder(self) -> bool:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(LOGS_DIR))
        return True

    def command(self, action: str) -> str:
        with self.lock:
            if action == "show":
                if not self.main_ready and self.native_splash is not None:
                    self.native_splash.show()
                    return "startup-shown"
                if self.window is None:
                    raise RuntimeError("桌面窗口尚未准备完成。")
                self.window.show()
                self.window.restore()
                return "shown"
            if action == "hide":
                if not self.main_ready:
                    threading.Thread(target=self.shutdown, name="startup-exit", daemon=True).start()
                    return "exiting"
                self.window.hide()
                return "hidden"
            if action == "minimize":
                if not self.main_ready and self.native_splash is not None:
                    self.native_splash.minimize()
                    return "startup-minimized"
                if self.window is None:
                    raise RuntimeError("桌面窗口尚未准备完成。")
                self.window.minimize()
                return "minimized"
            if action == "maximize":
                if self.window is None:
                    return "startup-window-managed"
                if self.maximized:
                    self._restore_from_work_area()
                    self.maximized = False
                    return "restored"
                self._maximize_to_work_area()
                self.maximized = True
                return "maximized"
            if action == "exit":
                threading.Thread(target=self.shutdown, name="app-shutdown", daemon=True).start()
                return "exiting"
        raise ValueError("不支持的窗口操作。")

    def _maximize_to_work_area(self) -> None:
        if os.name != "nt":
            self.window.maximize()
            return
        hwnd = self._current_window_handle()
        if hwnd is None:
            raise RuntimeError("无法读取主窗口位置。")
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        class Rect(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", Rect), ("rcWork", Rect), ("dwFlags", ctypes.c_ulong)]

        user32.GetWindowRect.argtypes = (ctypes.c_void_p, ctypes.POINTER(Rect))
        user32.GetWindowRect.restype = ctypes.c_bool
        user32.MonitorFromWindow.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = (ctypes.c_void_p, ctypes.POINTER(MonitorInfo))
        user32.GetMonitorInfoW.restype = ctypes.c_bool
        user32.SetWindowPos.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        )
        user32.SetWindowPos.restype = ctypes.c_bool
        current = Rect()
        if not user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(current)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.restore_window_rect = (current.left, current.top, current.right - current.left, current.bottom - current.top)
        monitor = user32.MonitorFromWindow(ctypes.c_void_p(hwnd), 2)
        info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
        if not monitor or not user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        work = info.rcWork
        user32.SetWindowPos(
            ctypes.c_void_p(hwnd), None, work.left, work.top,
            work.right - work.left, work.bottom - work.top,
            0x0004 | 0x0010,
        )

    def _restore_from_work_area(self) -> None:
        if os.name != "nt" or self.restore_window_rect is None:
            self.window.restore()
            return
        hwnd = self._current_window_handle()
        if hwnd is None:
            self.window.restore()
            return
        x, y, width, height = self.restore_window_rect
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetWindowPos.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        )
        user32.SetWindowPos.restype = ctypes.c_bool
        user32.SetWindowPos(ctypes.c_void_p(hwnd), None, x, y, width, height, 0x0004 | 0x0010)
        self.restore_window_rect = None

    def on_closing(self, *_: Any) -> bool:
        if self.exiting:
            return True
        if self.main_ready:
            self.window.hide()
            return False
        threading.Thread(target=self.shutdown, args=(False,), name="startup-close", daemon=True).start()
        return True

    def initialize_backend(self) -> None:
        with self.init_lock:
            if self.exiting:
                return
            self.backend_worker = threading.current_thread()
            try:
                self.set_phase("backend_import", "正在载入本地服务组件")
                if os.environ.get("MOSS_TTS_FAULT") == "backend_import":
                    raise RuntimeError("startup-lab backend import fault")
                import uvicorn
                from desktop.backend.desktop_control import DESKTOP
                from desktop.backend.server import app

                self.desktop_control = DESKTOP
                app.state.startup_reporter = self.set_phase
                DESKTOP.register(self.command, self.public_status)
                config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", access_log=False)
                self.server = uvicorn.Server(config)
                self.server_thread = threading.Thread(target=self.server.run, name="local-api", daemon=True)
                self.server_thread.start()
                deadline = time.monotonic() + 25.0
                while time.monotonic() < deadline and not self.exiting:
                    if self.server.started:
                        break
                    if not self.server_thread.is_alive():
                        raise RuntimeError(f"本地服务启动失败，请确认 {PORT} 端口没有被其他程序占用。")
                    time.sleep(.025)
                if not self.server.started:
                    raise RuntimeError("本地服务启动超时。")
                health = json_request("/api/v2/health", timeout=.8)
                if not health or not health.get("ok"):
                    raise RuntimeError("本地服务健康检查未通过。")
                self.set_phase("frontend", "正在创建项目中心窗口")
                self.api_ready.set()
            except BaseException as exc:
                if not self.exiting:
                    self.fail(exc)

    def on_webview_loaded(self, *_: Any) -> None:
        if self.webview_loaded.is_set():
            return
        self.webview_loaded.set()
        self.frontend_document_loaded.set()
        if TRACE is not None:
            TRACE.record("webview_ready", "frontend", "隐藏的 WebView2 容器已就绪")
            TRACE.record("frontend_document_loaded", "frontend", "项目中心文档已载入")
        threading.Thread(target=self._watch_frontend_ready, name="frontend-ready-watch", daemon=True).start()

    def _watch_frontend_ready(self) -> None:
        if self.frontend_ready_event.wait(timeout=4.0) or self.exiting:
            return
        if TRACE is not None:
            TRACE.record("frontend_retry", "frontend", "React 未在预期时间内就绪，正在重新载入")
        self.frontend_document_loaded.clear()
        self.window.load_url(APP_URL)
        if not self.frontend_ready_event.wait(timeout=4.0) and not self.exiting:
            self.fail(RuntimeError("React 项目中心未能完成启动。"))

    def frontend_ready(self) -> dict[str, Any]:
        with self.lock:
            if self.frontend_ready_event.is_set():
                return self.startup_status()
            self.frontend_ready_event.set()
        threading.Thread(target=self._present_main_window, name="main-window-present", daemon=True).start()
        return self.startup_status()

    def _present_main_window(self) -> None:
        if not self.webview_loaded.wait(timeout=10) or self.exiting:
            if not self.exiting:
                self.fail(RuntimeError("WebView2 主窗口未能进入可显示状态。"))
            return
        with self.lock:
            if self.main_ready:
                return
            self.main_ready = True
        self.set_phase("ready", "项目中心已就绪")
        if self.window is not None:
            self.window.restore()
            width, height, x, y = self.main_window_geometry
            self.window.resize(width, height)
            if x is not None and y is not None:
                self.window.move(x, y)
            self.window.show()
            if TRACE is not None:
                TRACE.record(
                    "main_window_centered",
                    "ready",
                    "项目中心已按主屏工作区居中",
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                )
        if self.native_splash is not None:
            self.native_splash.close()
        if TRACE is not None:
            TRACE.record("main_window_shown", "ready", "项目中心窗口已显示")
        self.watchdog_stop.set()
        threading.Thread(target=self.start_tray, name="tray-bootstrap", daemon=True).start()

    def frontend_event(self, event: str, message: str) -> bool:
        safe_event = "".join(character for character in event if character.isalnum() or character in {"_", "-"})[:48] or "frontend_event"
        if TRACE is not None:
            TRACE.record(safe_event, "frontend", message[:300])
        return True

    def start_tray(self) -> None:
        try:
            if os.environ.get("MOSS_TTS_FAULT") == "tray_failure":
                raise RuntimeError("startup-lab tray fault")
            import pystray
            from PIL import Image

            image = Image.open(ICON_PATH)
            menu = pystray.Menu(
                pystray.MenuItem("打开声格 VoiceGrid", lambda *_: self.command("show"), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", lambda *_: self.command("exit")),
            )
            self.tray = pystray.Icon("voicegrid-v2", image, "声格 VoiceGrid · 龙融影业", menu)
            if TRACE is not None:
                TRACE.record("tray_created", "ready", "系统托盘已创建")
            self.tray.run()
        except Exception as exc:
            startup_log(f"系统托盘不可用，但主界面可继续使用：{exc}")
            if TRACE is not None:
                TRACE.record("tray_failed", "ready", str(exc))

    def shutdown(self, destroy_window: bool = True) -> None:
        with self.shutdown_lock:
            if self.shutdown_started:
                return
            self.shutdown_started = True
            self.exiting = True
        self.watchdog_stop.set()
        if self.native_splash is not None:
            self.native_splash.close()
        if TRACE is not None:
            TRACE.record("shutdown_requested", self.phase, "桌面宿主正在退出")
        if self.desktop_control is not None:
            self.desktop_control.register(None)
        if self.server is not None:
            self.server.should_exit = True
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        if destroy_window and self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass

    @staticmethod
    def _current_window_handle(target_pid: int | None = None) -> int | None:
        if os.name != "nt":
            return None
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        user32.IsWindowVisible.argtypes = (ctypes.c_void_p,)
        user32.IsWindowVisible.restype = ctypes.c_bool
        user32.EnumWindows.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows.restype = ctypes.c_bool
        current_pid = target_pid or os.getpid()
        found: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd: int, _: int) -> bool:
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
            if pid.value == current_pid and user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
                found.append(int(hwnd))
                return False
            return True

        user32.EnumWindows(callback_type(callback), 0)
        return found[0] if found else None

    def _dump_thread_stacks(self, reason: str) -> None:
        target = LOGS_DIR / f"startup-hang-{datetime.now():%Y%m%d-%H%M%S-%f}.log"
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(reason + "\n")
            faulthandler.dump_traceback(file=handle, all_threads=True)
        if TRACE is not None:
            TRACE.record("thread_dump", self.phase, reason, path=str(target))

    def _watch_window_responsiveness(self) -> None:
        if os.name != "nt":
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SendMessageTimeoutW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_size_t),
        )
        user32.SendMessageTimeoutW.restype = ctypes.c_size_t
        user32.IsHungAppWindow.argtypes = (ctypes.c_void_p,)
        user32.IsHungAppWindow.restype = ctypes.c_bool
        user32.IsWindow.argtypes = (ctypes.c_void_p,)
        user32.IsWindow.restype = ctypes.c_bool
        result = ctypes.c_size_t()
        max_latency = 0.0
        last_dump = 0.0
        while not self.watchdog_stop.wait(.1) and not self.exiting:
            splash_pid = self.native_splash.process.pid if self.native_splash is not None and self.native_splash.process is not None else None
            hwnd = self._current_window_handle(splash_pid)
            if hwnd is None:
                continue
            started = time.perf_counter()
            responded = user32.SendMessageTimeoutW(ctypes.c_void_p(hwnd), 0, 0, 0, 0x0002, 250, ctypes.byref(result))
            latency_ms = (time.perf_counter() - started) * 1000
            if self.exiting or not user32.IsWindow(ctypes.c_void_p(hwnd)):
                break
            max_latency = max(max_latency, latency_ms)
            is_hung = bool(user32.IsHungAppWindow(ctypes.c_void_p(hwnd)))
            hung = not responded or is_hung or latency_ms > 250
            if hung and time.monotonic() - last_dump > 1.0:
                last_dump = time.monotonic()
                reason = f"GUI message loop stalled for {latency_ms:.1f}ms; IsHungAppWindow={is_hung}"
                self._dump_thread_stacks(reason)
        if TRACE is not None:
            TRACE.record("watchdog_complete", self.phase, "启动窗口响应检测结束", max_latency_ms=round(max_latency, 2))

    @staticmethod
    def _resolve_main_window_geometry() -> tuple[int, int, int | None, int | None]:
        try:
            screens = list(webview.screens)
            if not screens:
                return 1600, 1000, None, None
            screen = screens[0]
            frame = getattr(screen, "frame", None)
            work_x = int(getattr(frame, "X", screen.x))
            work_y = int(getattr(frame, "Y", screen.y))
            work_width = int(getattr(frame, "Width", screen.width))
            work_height = int(getattr(frame, "Height", screen.height))
            width = min(1600, max(1040, work_width - 80))
            height = min(1000, max(700, work_height - 80))
            x = work_x + max(0, (work_width - width) // 2)
            y = work_y + max(0, (work_height - height) // 2)
            return width, height, x, y
        except Exception as exc:
            startup_log(f"读取主屏工作区失败，将使用系统默认窗口位置：{exc}")
            return 1600, 1000, None, None

    def run(self) -> None:
        WEBVIEW_PROFILE.mkdir(parents=True, exist_ok=True)
        self.native_splash = NativeSplash(self)
        self.native_splash.start()
        threading.Thread(target=self._watch_window_responsiveness, name="startup-watchdog", daemon=True).start()
        self.backend_worker = threading.Thread(target=self.initialize_backend, name="backend-bootstrap", daemon=True)
        self.backend_worker.start()
        try:
            while not self.api_ready.wait(.1):
                if self.exiting:
                    return
            if os.environ.get("MOSS_TTS_FAULT") == "webview_missing":
                self.fail(RuntimeError("startup-lab WebView2 fault"))
                while not self.exiting:
                    time.sleep(.1)
                return
            self.main_window_geometry = self._resolve_main_window_geometry()
            window_width, window_height, window_x, window_y = self.main_window_geometry
            self.window = webview.create_window(
                WINDOW_TITLE,
                APP_URL,
                js_api=NativeApi(self),
                width=window_width,
                height=window_height,
                x=window_x,
                y=window_y,
                min_size=(1040, 700),
                frameless=True,
                easy_drag=False,
                shadow=True,
                background_color="#090a0b",
                text_select=True,
                hidden=True,
            )
            self.window.events.closing += self.on_closing
            self.window.events.loaded += self.on_webview_loaded
            if TRACE is not None:
                TRACE.record("window_created", "frontend", "隐藏的 WebView2 项目中心窗口已创建")
            webview.start(
                gui="edgechromium",
                icon=str(ICON_PATH),
                debug=False,
                private_mode=False,
                storage_path=str(WEBVIEW_PROFILE),
            )
        finally:
            self.shutdown(destroy_window=False)
            if self.server_thread is not None:
                self.server_thread.join(timeout=10)
            if self.native_splash is not None:
                self.native_splash.stop()


class NativeApi:
    def __init__(self, host: NativeHost) -> None:
        # pywebview recursively inspects public attributes while building the
        # JavaScript bridge. Keep the host graph private so cold startup only
        # exports the deliberately small method surface below.
        self._host = host

    def window_action(self, action: str) -> str:
        return self._host.command(action)

    def startup_status(self) -> dict[str, Any]:
        return self._host.startup_status()

    def continue_waiting(self) -> dict[str, Any]:
        return self._host.continue_waiting()

    def retry_startup(self) -> dict[str, Any]:
        return self._host.retry_startup()

    def open_log_folder(self) -> bool:
        return self._host.open_log_folder()

    def frontend_ready(self) -> dict[str, Any]:
        return self._host.frontend_ready()

    def frontend_event(self, event: str, message: str) -> bool:
        return self._host.frontend_event(event, message)

    def select_folder(self, initial: str = "") -> str | None:
        start = Path(initial).expanduser() if initial else ROOT
        if start.is_file():
            start = start.parent
        if not start.is_dir():
            start = ROOT
        result = self._host.window.create_file_dialog(webview.FOLDER_DIALOG, directory=str(start))
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
    global TRACE
    os.chdir(ROOT)
    mutex = WindowsMutex(MUTEX_NAME)
    if mutex.already_exists:
        activated = activate_existing_instance()
        startup_log("重复启动请求：已唤醒现有窗口" if activated else "重复启动请求：现有实例仍在启动，已忽略")
        mutex.close()
        return
    try:
        startup_log(f"收到启动请求，程序目录：{ROOT}", reset=True)
        TRACE = StartupTrace(TRACE_PATH)
        TRACE.record("process_start", "shell", "桌面宿主进程已启动")
        NativeHost().run()
        startup_log("桌面宿主已退出")
    finally:
        mutex.close()


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        try:
            startup_log("启动失败：\n" + detail)
            if TRACE is not None:
                TRACE.record("fatal", "failed", str(exc), traceback=detail)
        except Exception:
            pass
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                f"桌面版启动失败：\n\n{exc}\n\n详细信息：\n{STARTUP_LOG}",
                "声格 VoiceGrid",
                0x10,
            )
        except Exception:
            pass
        raise
