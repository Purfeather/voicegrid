"""Compatibility entry point for the VoiceGrid 2.0 accent splash host.

Asset: ``voicegrid-icon-accent``.
"""

from desktop.native.splash_host import Client, SplashWindow, main

__all__ = ["Client", "SplashWindow", "main"]


if __name__ == "__main__":
    main()
