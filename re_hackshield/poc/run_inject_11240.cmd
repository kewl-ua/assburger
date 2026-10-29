@echo off
"C:\SHARE\hwid\re_hackshield\poc\inject.exe" 11240 "C:\SHARE\hwid\re_hackshield\poc\rfmon2.dll" > "C:\SHARE\hwid\re_hackshield\logs\inject_rfmon2_11240.txt" 2>&1
echo exit=%ERRORLEVEL% >> "C:\SHARE\hwid\re_hackshield\logs\inject_rfmon2_11240.txt"
