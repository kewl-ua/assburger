@echo off
rem Double-click to open the control panel (auto-elevates for injection).
cd /d "%~dp0"
start "" pythonw "%~dp0gui.py"
