import ctypes, json, time, subprocess, sys
from ctypes import wintypes

prof = json.load(open(r"C:\SHARE\hwid\profiles.json", encoding="utf-8-sig"))
p2 = [p for p in prof["profiles"] if str(p.get("id")) == "2"][0]
user = p2.get("user") or "Johnny"
pw = p2.get("password") or ""
exe = r"C:\SHARE\CERBERUS3\RF_Online_4gb.bin"
cwd = r"C:\SHARE\CERBERUS3"
dll = r"C:\SHARE\hwid\re_hackshield\poc\hsmon5.dll"
inj = r"C:\SHARE\hwid\re_hackshield\poc\inject.exe"

advapi = ctypes.WinDLL("advapi32", use_last_error=True)
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

advapi.CreateProcessWithLogonW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
advapi.CreateProcessWithLogonW.restype = wintypes.BOOL

def spawn(cmdline, flags=0, workdir=cwd):
    si = STARTUPINFOW(); si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    buf = ctypes.create_unicode_buffer(cmdline)
    ok = advapi.CreateProcessWithLogonW(user, ".", pw, 1, None, buf, flags | 0x00000400, None, workdir,
                                        ctypes.byref(si), ctypes.byref(pi))
    print("spawn", ok, "err", ctypes.get_last_error(), "pid", pi.dwProcessId, flush=True)
    if not ok: sys.exit(1)
    return pi

pi = spawn('"%s"' % exe, 0x00000004)
time.sleep(0.5)
# inject as Johnny, waiting
ipi = spawn('"%s" %d "%s"' % (inj, pi.dwProcessId, dll), 0, r"C:\SHARE\hwid\re_hackshield\poc")
k32.WaitForSingleObject(ipi.hProcess, 15000)
code = wintypes.DWORD()
k32.GetExitCodeProcess(ipi.hProcess, ctypes.byref(code))
print("inject exit", code.value, flush=True)
k32.CloseHandle(ipi.hThread); k32.CloseHandle(ipi.hProcess)
k32.ResumeThread(pi.hThread)
print("resumed", flush=True)
for i in range(40):
    time.sleep(1.5)
    p = subprocess.run(['powershell','-NoProfile','-Command',"Get-Process -Id %d -ErrorAction SilentlyContinue | Select-Object -ExpandProperty MainWindowTitle" % pi.dwProcessId], capture_output=True, text=True)
    title = p.stdout.strip()
    if i % 5 == 0 or title:
        print("t=%.1f title=%r" % ((i+1)*1.5, title), flush=True)
    if title: break
print("pid=%d kept running" % pi.dwProcessId, flush=True)
