@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-rpg.ps1"
set "RPG_BUILD_EXIT=%ERRORLEVEL%"
echo.
if not "%RPG_BUILD_EXIT%"=="0" echo Build failed. See the error above.
pause
exit /b %RPG_BUILD_EXIT%
