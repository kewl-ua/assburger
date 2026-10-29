@echo off
set LOG=C:\SHARE\hwid\re_hackshield\logs\create_john.txt
echo === %DATE% %TIME% === > "%LOG%"
net user John CHANGEME /add >> "%LOG%" 2>&1
echo user_exit=%ERRORLEVEL% >> "%LOG%"
icacls "C:\SHARE\CERBERUS" /grant "John:(OI)(CI)M" /T /C >> "%LOG%" 2>&1
echo cerberus_acl=%ERRORLEVEL% >> "%LOG%"
icacls "C:\SHARE\hwid\cef\profile_1" /grant "John:(OI)(CI)M" /T /C >> "%LOG%" 2>&1
echo cef_acl=%ERRORLEVEL% >> "%LOG%"
icacls "C:\SHARE\hwid\logs" /grant "John:(OI)(CI)M" /T /C >> "%LOG%" 2>&1
echo logs_acl=%ERRORLEVEL% >> "%LOG%"
icacls "C:\SHARE\hwid\meta\profile_1" /grant "John:(OI)(CI)M" /T /C >> "%LOG%" 2>&1
echo meta_acl=%ERRORLEVEL% >> "%LOG%"
icacls "C:\SHARE\hwid" /grant "John:(OI)(CI)RX" /T /C >> "%LOG%" 2>&1
echo hwid_acl=%ERRORLEVEL% >> "%LOG%"
