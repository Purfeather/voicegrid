from __future__ import annotations

import argparse
import json
import os
import socket
import tkinter as tk
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ICON_PATH = ROOT / "desktop" / "assets" / "voicegrid.ico"
WINDOW_TITLE = os.environ.get("MOSS_TTS_WINDOW_TITLE", "声格 VoiceGrid 2.0")


class Client:
    def __init__(self, port: int, token: str) -> None:
        self.port = port
        self.token = token

    def call(self, action: str) -> dict[str, Any]:
        payload = json.dumps({"token": self.token, "action": action}, ensure_ascii=True).encode("ascii") + b"\n"
        with socket.create_connection(("127.0.0.1", self.port), timeout=.4) as connection:
            connection.sendall(payload)
            stream = connection.makefile("rb")
            line = stream.readline(65536)
        return json.loads(line.decode("utf-8")) if line else {"ok": False}


class SplashWindow:
    def __init__(self, client: Client) -> None:
        self.client = client
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.configure(bg="#090a0b")
        self.root.overrideredirect(True)
        self.root.resizable(False, False)
        try:
            self.root.iconbitmap(default=str(ICON_PATH))
        except Exception:
            pass
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(960, max(820, int(screen_width * .56)))
        height = min(560, max(480, int(screen_height * .55)))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.attributes("-topmost", True)
        self.stage_var = tk.StringVar(value="正在创建桌面窗口")
        self.detail_var = tk.StringVar(value="窗口控制已经可用，后台服务将在独立进程中继续准备。")
        self.elapsed_var = tk.StringVar(value="准备中")
        self.drag_x = 0
        self.drag_y = 0
        self.segments: list[tk.Frame] = []
        self.diagnostic_visible = False
        self.last_command_id = 0
        self.connection_failures = 0
        self._build()

    def _build(self) -> None:
        outer = tk.Frame(self.root, bg="#090a0b", highlightbackground="#2a2e33", highlightthickness=1)
        outer.pack(fill="both", expand=True)
        shell = tk.Frame(outer, bg="#090a0b", padx=36, pady=28)
        shell.pack(fill="both", expand=True)
        brand = tk.Frame(shell, bg="#090a0b")
        brand.pack(fill="x")
        try:
            from PIL import Image, ImageTk
            mark_image = Image.open(ROOT / "desktop" / "assets" / "voicegrid-icon-white.png").resize((40, 40), Image.Resampling.LANCZOS)
            self._brand_icon = ImageTk.PhotoImage(mark_image)
            tk.Label(brand, image=self._brand_icon, bg="#090a0b").pack(side="left")
        except Exception:
            tk.Label(brand, text="VG", bg="#181b1e", fg="#f3ff00", width=4, height=2, font=("Segoe UI", 10, "bold")).pack(side="left")
        brand_copy = tk.Frame(brand, bg="#090a0b")
        brand_copy.pack(side="left", padx=12)
        tk.Label(brand_copy, text="声格 VoiceGrid", bg="#090a0b", fg="#f4f6f8", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        tk.Label(brand_copy, text="龙融影业 · 2.0", bg="#090a0b", fg="#9aa2ad", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(3, 0))
        tk.Label(brand_copy, text="作者：Wang Xiaohan", bg="#090a0b", fg="#9aa2ad", font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))

        status = tk.Frame(shell, bg="#090a0b")
        status.pack(side="bottom", fill="x")
        tk.Frame(status, bg="#2a2e33", height=1).pack(fill="x", pady=(0, 15))
        status_meta = tk.Frame(status, bg="#090a0b")
        status_meta.pack(fill="x")
        tk.Label(status_meta, text="STARTUP SEQUENCE", bg="#090a0b", fg="#9aa2ad", font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(status_meta, textvariable=self.elapsed_var, bg="#090a0b", fg="#9aa2ad", font=("Consolas", 8)).pack(side="right")
        tk.Label(status, textvariable=self.stage_var, bg="#090a0b", fg="#f4f6f8", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", pady=(5, 9))
        segment_row = tk.Frame(status, bg="#090a0b")
        segment_row.pack(fill="x")
        for _ in range(7):
            segment = tk.Frame(segment_row, bg="#2a2e33", height=3)
            segment.pack(side="left", fill="x", expand=True, padx=(0, 5))
            self.segments.append(segment)
        tk.Label(status, textvariable=self.detail_var, wraplength=850, justify="left", anchor="w", bg="#090a0b", fg="#9aa2ad", font=("Microsoft YaHei UI", 9)).pack(anchor="w", fill="x", pady=(9, 0))

        self.diagnostic = tk.Frame(status, bg="#090a0b")
        action_row = tk.Frame(self.diagnostic, bg="#090a0b")
        action_row.pack(fill="x")
        self._button(action_row, "继续等待", lambda: self._action("continue"), primary=True)
        self._button(action_row, "重试", lambda: self._action("retry"))
        self._button(action_row, "打开日志", lambda: self._action("logs"))
        self._button(action_row, "退出", self._exit)

        content = tk.Frame(shell, bg="#090a0b")
        content.pack(fill="both", expand=True, pady=(24, 18))
        identity = tk.Frame(content, bg="#090a0b")
        identity.pack(fill="both", expand=True)
        tk.Label(identity, text="—  LOCAL VOICE PRODUCTION", bg="#090a0b", fg="#f3ff00", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 15))
        tk.Label(identity, text="让声音先醒来，", bg="#090a0b", fg="#f4f6f8", font=("Microsoft YaHei UI", 30, "bold")).pack(anchor="w")
        tk.Label(identity, text="模型稍后就绪。", bg="#090a0b", fg="#9aa2ad", font=("Microsoft YaHei UI", 30)).pack(anchor="w", pady=(0, 15))
        description = "正在准备本地项目、音色资产与离线服务。\nMOSS-TTS 1.5 4B 仍会保持懒加载，只有开始生成时才进入显存。"
        tk.Label(identity, text=description, justify="left", bg="#090a0b", fg="#9aa2ad", font=("Microsoft YaHei UI", 10), pady=6).pack(anchor="w")

        for widget in (brand, brand_copy, identity):
            self._enable_drag(widget)

    def _enable_drag(self, widget: tk.Misc) -> None:
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._drag)
        for child in widget.winfo_children():
            self._enable_drag(child)

    def _start_drag(self, event: tk.Event) -> None:
        self.drag_x = event.x_root - self.root.winfo_x()
        self.drag_y = event.y_root - self.root.winfo_y()

    def _drag(self, event: tk.Event) -> None:
        self.root.geometry(f"+{event.x_root - self.drag_x}+{event.y_root - self.drag_y}")

    @staticmethod
    def _button(parent: tk.Frame, text: str, command, primary: bool = False) -> None:
        tk.Button(
            parent,
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

    def _action(self, action: str) -> None:
        try:
            self.client.call(action)
        except Exception:
            pass

    def _exit(self) -> None:
        self._action("exit")
        self.root.destroy()

    def _tick(self) -> None:
        try:
            response = self.client.call("status")
            self.connection_failures = 0
        except Exception:
            self.connection_failures += 1
            if self.connection_failures >= 12:
                self.root.destroy()
                return
            self.root.after(100, self._tick)
            return
        if response.get("close_requested"):
            self.root.destroy()
            return
        command_id = int(response.get("command_id") or 0)
        if command_id > self.last_command_id:
            self.last_command_id = command_id
            if response.get("window_command") == "show":
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            elif response.get("window_command") == "minimize":
                self.root.iconify()
        status = response.get("status") or {}
        phase = str(status.get("phase") or "shell")
        active_phase = str(status.get("active_phase") or phase)
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
        self.stage_var.set(phase_names.get(phase, phase_names.get(active_phase, "正在准备工作台")))
        self.detail_var.set(status.get("detail") or status.get("message") or "正在准备本地服务。")
        elapsed_ms = int(status.get("elapsed_ms") or 0)
        self.elapsed_var.set(f"{elapsed_ms / 1000:.1f} 秒" if elapsed_ms >= 1000 else f"{elapsed_ms} 毫秒")
        index = max(0, phases.index(active_phase) if active_phase in phases else 0)
        for item_index, segment in enumerate(self.segments):
            segment.configure(bg="#f3ff00" if item_index < index or active_phase == "ready" else "#2a2e33")
        show_diagnostic = phase in {"slow", "failed"}
        if show_diagnostic and not self.diagnostic_visible:
            self.diagnostic.pack(fill="x", pady=(10, 0))
            self.diagnostic_visible = True
        elif not show_diagnostic and self.diagnostic_visible:
            self.diagnostic.pack_forget()
            self.diagnostic_visible = False
        self.root.after(100, self._tick)

    def run(self) -> None:
        self.root.update_idletasks()
        self.root.deiconify()
        self.root.lift()
        self.root.after(0, self._announce_visible)
        self.root.mainloop()

    def _announce_visible(self) -> None:
        self.client.call("visible")
        self.root.after(50, self._tick)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    SplashWindow(Client(args.port, args.token)).run()


if __name__ == "__main__":
    main()
