@echo off
setlocal
cd /d "%~dp0"
git -c safe.directory=D:/MOSS-TTS-Test-Version %*
exit /b %errorlevel%
