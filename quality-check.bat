@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Project Python runtime is missing.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "desktop\tools\quality_check.py" %*
set "VOICEGRID_EXIT=%ERRORLEVEL%"
if not "%VOICEGRID_EXIT%"=="0" pause
exit /b %VOICEGRID_EXIT%
