"""Compatibility wrapper for the isolated legacy desktop host."""

from desktop.legacy.host import NativeApi, NativeHost, activate_existing_instance, main, run_entrypoint, startup_log

__all__ = ["NativeApi", "NativeHost", "activate_existing_instance", "main", "run_entrypoint", "startup_log"]


if __name__ == "__main__":
    run_entrypoint()
