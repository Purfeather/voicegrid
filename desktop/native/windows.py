from __future__ import annotations

import ctypes
import os
from typing import Any, Callable


def current_window_handle(target_pid: int | None = None) -> int | None:
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


def resolve_main_window_geometry(webview_module: Any, log: Callable[[str], None]) -> tuple[int, int, int | None, int | None]:
    try:
        screens = list(webview_module.screens)
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
        log(f"读取主屏工作区失败，将使用系统默认窗口位置：{exc}")
        return 1600, 1000, None, None

