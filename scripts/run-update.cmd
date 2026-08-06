@echo off
setlocal
chcp 65001 > nul
set "PYTHONUTF8=1"
set "OPROS_PROJECT=C:\projects\opros-site-updater"
if not exist "%OPROS_PROJECT%\out" mkdir "%OPROS_PROJECT%\out"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%OPROS_PROJECT%\scripts\run-update.ps1" >> "%OPROS_PROJECT%\out\scheduled-bootstrap.log" 2>&1
exit /b %errorlevel%
