@echo off
rem Double-click: opens the one-file control panel (auto-elevates for injection).
cd /d "%~dp0"
for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.dirname(sys.executable))" 2^>nul') do set "PYD=%%i"
if not defined PYD ( echo python not found in PATH & pause & exit /b 1 )
set "EXE=%PYD%\pythonw.exe"
if not exist "%EXE%" set "EXE=%PYD%\python.exe"
rem app.py self-elevates and starts the always-on rfguard (manual map: spoofer into launcher/CEF/game,
rem BotCore into the game); no LoadLibrary, no watchinj_multi.
start "" "%EXE%" "%~dp0app.py"
