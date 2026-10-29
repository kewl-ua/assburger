import ctypes, json, os, sys, time
from ctypes import wintypes

prof = json.load(open(r"C:\SHARE\hwid\profiles.json", encoding="utf-8-sig"))
p2 = [p for p in prof["profiles"] if str(p.get("id")) == "2"][0]
user = p2.get("user") or "Johnny"
pw = p2.get("password") or ""
nowait = len(sys.argv) > 2 and sys.argv[1] == "--nowait"
cmd = (sys.argv[2] if nowait else sys.argv[1]) if len(sys.argv) > 1 else "cmd.exe /c whoami > C:\\SHARE\\hwid\\re_hackshield\\logs\\who_johnny.txt 2>&1"
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
si = STARTUPINFOW(); si.cb = ctypes.sizeof(si)
pi = PROCESS_INFORMATION()
buf = ctypes.create_unicode_buffer(cmd)
ok = advapi.CreateProcessWithLogonW(user, ".", pw, 1, None, buf, 0x00000400, None,
                                    r"C:\SHARE\hwid\re_hackshield", ctypes.byref(si), ctypes.byref(pi))
print("CreateProcessWithLogonW", ok, "err", ctypes.get_last_error(), "pid", pi.dwProcessId)
if ok and not nowait:
    k32.WaitForSingleObject(pi.hProcess, 30000)
    k32.CloseHandle(pi.hThread); k32.CloseHandle(pi.hProcess)
