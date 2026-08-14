@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo Python runtime is missing.
  pause
  exit /b 1
)

rem Compatibility wrapper: desktop.host_legacy delegates to desktop.legacy.host.
start "" ".venv\Scripts\pythonw.exe" -m desktop.host_legacy
exit /b 0
