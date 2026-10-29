import ctypes, os, subprocess, sys, time
from ctypes import wintypes

LOG = r"C:\SHARE\hwid\re_hackshield\logs\watch_inject.txt"
DLL = r"C:\SHARE\hwid\re_hackshield\poc\hsmon5.dll"
INJ = r"C:\SHARE\hwid\re_hackshield\poc\inject.exe"
STOP = r"C:\SHARE\hwid\re_hackshield\logs\watch_inject.stop"
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260)]

def log(s):
    line = time.strftime("%H:%M:%S") + " " + s
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def procs():
    snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
    pe = PROCESSENTRY32(); pe.dwSize = ctypes.sizeof(pe)
    out = []
    if k32.Process32First(snap, ctypes.byref(pe)):
        while True:
            out.append((pe.th32ProcessID, pe.szExeFile.decode("latin1")))
            if not k32.Process32Next(snap, ctypes.byref(pe)):
                break
    k32.CloseHandle(snap)
    return out

try:
    os.remove(STOP)
except OSError:
    pass
log("watcher start pid=%d" % os.getpid())
seen = set()
t0 = time.time()
while time.time() - t0 < 900 and not os.path.exists(STOP):
    for pid, name in procs():
        if name.lower() != "rf_online_4gb.bin":
            continue
        if pid in seen:
            continue
        seen.add(pid)
        log("game pid=%d" % pid)
        try:
            r = subprocess.run([INJ, str(pid), DLL], capture_output=True, text=True, timeout=10)
            log("inject rc=%d out=%r err=%r" % (r.returncode, r.stdout.strip(), r.stderr.strip()))
        except Exception as e:
            log("inject exception %r" % (e,))
        time.sleep(0.5)
    time.sleep(0.03)
log("watcher exit")
