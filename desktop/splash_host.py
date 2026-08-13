"""Compatibility entry point for the VoiceGrid 2.0 accent splash host.

Asset: ``voicegrid-icon-accent``.
"""

from desktop.native.splash_host import Client, SplashWindow, main

DISPLAY_VERSION = "2.0"

__all__ = ["Client", "DISPLAY_VERSION", "SplashWindow", "main"]


if __name__ == "__main__":
    main()
