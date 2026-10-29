@echo off
rem One-click, windowless start. Double-click this file:
rem   - launches rfbot.py under pythonw.exe (no console window),
rem   - rfbot.py self-elevates (UAC) and maps the BotCore module into the running game, then shows the GUI.
rem The game (+ spoof in the launcher) must already be running.
rem Flags: --sys-console (python.exe + console), --no-elevate, --no-map, --show-console, --hide-console.
setlocal
cd /d "%~dp0"

for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.dirname(sys.executable))" 2^>nul') do set "PYD=%%i"
if not defined PYD (
  echo python not found in PATH
  pause
  exit /b 1
)

set "EXE=%PYD%\pythonw.exe"
for %%a in (%*) do if /i "%%a"=="--sys-console" set "EXE=%PYD%\python.exe"
if not exist "%EXE%" set "EXE=%PYD%\python.exe"
if not exist "%EXE%" (
  echo pythonw.exe / python.exe not found in %PYD%
  pause
  exit /b 1
)

start "" "%EXE%" "%~dp0rfbot.py" %*
