import ctypes, time, sys, os, subprocess
from ctypes import wintypes

exe = r"C:\SHARE\CERBERUS3\RF_Online_4gb.bin"
cwd = r"C:\SHARE\CERBERUS3"
dll = r"C:\SHARE\hwid\re_hackshield\poc\hsmon5.dll"
inj = r"C:\SHARE\hwid\re_hackshield\poc\inject.exe"
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]
class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]
k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
    wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
si = STARTUPINFOW(); si.cb = ctypes.sizeof(si)
pi = PROCESS_INFORMATION()
cmd = ctypes.create_unicode_buffer('"%s"' % exe)
ok = k32.CreateProcessW(exe, cmd, None, None, False, 0x00000004 | 0x00000400, None, cwd, ctypes.byref(si), ctypes.byref(pi))
print("CreateProcess", ok, "err", ctypes.get_last_error(), "pid", pi.dwProcessId, flush=True)
if not ok: sys.exit(1)
time.sleep(0.5)
r = subprocess.run([inj, str(pi.dwProcessId), dll], capture_output=True, text=True)
print("inject", r.returncode, r.stdout, r.stderr, flush=True)
k32.ResumeThread(pi.hThread)
print("resumed", flush=True)
for i in range(40):
    time.sleep(1.5)
    p = subprocess.run(['powershell','-NoProfile','-Command',"Get-Process -Id %d -ErrorAction SilentlyContinue | Select-Object -ExpandProperty MainWindowTitle" % pi.dwProcessId], capture_output=True, text=True)
    title = p.stdout.strip()
    if i % 5 == 0 or title:
        print("t=%.1f title=%r" % ((i+1)*1.5, title), flush=True)
    if title:
        break
print("pid=%d kept running" % pi.dwProcessId, flush=True)
