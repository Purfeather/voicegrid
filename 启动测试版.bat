@echo off
setlocal
set "APP_ROOT=%~dp0"
set "PYTHONW=%APP_ROOT%runtime\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=%APP_ROOT%.venv\Scripts\pythonw.exe"
cd /d "%APP_ROOT%"

if not exist "%PYTHONW%" goto missing_runtime
if not exist "desktop\frontend\dist\index.html" goto missing_frontend

start "" /D "%APP_ROOT%" "%PYTHONW%" -m desktop.host
if errorlevel 1 goto launch_failed
exit /b 0

:missing_runtime
echo [ERROR] VoiceGrid runtime is missing.
goto failed

:missing_frontend
echo [ERROR] Desktop frontend has not been built.
goto failed

:launch_failed
echo [ERROR] Failed to create the desktop process.

:failed
pause
exit /b 1
