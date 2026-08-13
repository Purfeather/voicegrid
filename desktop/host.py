"""Compatibility entry point for ``python -m desktop.host``.

VoiceGrid 2.0 uses the accent asset ``voicegrid-icon-accent``. The native
implementation lives in :mod:`desktop.native.host`.
"""

from desktop.native.host import NativeApi, NativeHost, NativeSplash, StartupTrace, WindowsMutex, activate_existing_instance, main, run_entrypoint, startup_log

__all__ = [
    "NativeApi",
    "NativeHost",
    "NativeSplash",
    "StartupTrace",
    "WindowsMutex",
    "activate_existing_instance",
    "main",
    "run_entrypoint",
    "startup_log",
]


if __name__ == "__main__":
    run_entrypoint()
