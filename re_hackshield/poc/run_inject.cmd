@echo off
"C:\SHARE\hwid\re_hackshield\poc\inject.exe" 13052 "C:\SHARE\hwid\re_hackshield\poc\rfmon2.dll" > "C:\SHARE\hwid\re_hackshield\logs\inject_rfmon2.txt" 2>&1
echo exit=%ERRORLEVEL% >> "C:\SHARE\hwid\re_hackshield\logs\inject_rfmon2.txt"
