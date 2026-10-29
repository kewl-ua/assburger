@echo off
set LOG=C:\SHARE\hwid\re_hackshield\logs\create_billy2.txt
echo === %DATE% %TIME% === > "%LOG%"
net user Billy2 CHANGEME /add >> "%LOG%" 2>&1
echo user_exit=%ERRORLEVEL% >> "%LOG%"
icacls "C:\SHARE\CERBERUS" /grant "Billy2:(OI)(CI)M" /T /C >> "%LOG%" 2>&1
echo cerberus_acl=%ERRORLEVEL% >> "%LOG%"
icacls "C:\SHARE\hwid\cef\profile_1" /grant "Billy2:(OI)(CI)M" /T /C >> "%LOG%" 2>&1
echo cef_acl=%ERRORLEVEL% >> "%LOG%"
icacls "C:\SHARE\hwid\logs" /grant "Billy2:(OI)(CI)M" /T /C >> "%LOG%" 2>&1
echo logs_acl=%ERRORLEVEL% >> "%LOG%"
icacls "C:\SHARE\hwid\meta\profile_1" /grant "Billy2:(OI)(CI)M" /T /C >> "%LOG%" 2>&1
echo meta_acl=%ERRORLEVEL% >> "%LOG%"
icacls "C:\SHARE\hwid" /grant "Billy2:(OI)(CI)RX" /T /C >> "%LOG%" 2>&1
echo hwid_acl=%ERRORLEVEL% >> "%LOG%"
