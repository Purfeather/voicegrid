from __future__ import annotations

import ctypes
import os

from desktop.native.startup import json_request


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


def activate_existing_instance(host: str, port: int) -> bool:
    status = json_request(host, port, "/api/v2/desktop/status", timeout=.35)
    if not status or not status.get("native") or not status.get("ready"):
        return False
    result = json_request(host, port, "/api/v2/desktop/action/show", method="POST", timeout=.5)
    return bool(result and result.get("ok"))

