import ctypes
import os
import subprocess
import time
from ctypes import wintypes

HERE = r"C:\SHARE\hwid\re_hackshield"
INJECT = os.path.join(HERE, "poc", "inject.exe")
DLL = os.path.join(HERE, "poc", "rfmon3.dll")
ASJ = os.path.join(HERE, "scripts", "run_as_johnny.py")
LOG = os.path.join(HERE, "logs", "inject_rfmon3_delayed.txt")
PY = r"C:\Users\Admin\AppData\Local\Programs\Python\Python314\python.exe"

k = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


def game_pids():
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    if snap == ctypes.c_void_p(-1).value:
        return []
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(pe)
    out = []
    ok = k.Process32First(snap, ctypes.byref(pe))
    while ok:
        if pe.szExeFile.decode("latin1", "replace").lower() == "rf_online_4gb.bin":
            out.append(pe.th32ProcessID)
        ok = k.Process32Next(snap, ctypes.byref(pe))
    k.CloseHandle(snap)
    return out


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("[%H:%M:%S] ") + msg + "\n")


seen = set(game_pids())
log("observer start; existing=%s" % sorted(seen))
while True:
    for pid in game_pids():
        if pid in seen:
            continue
        seen.add(pid)
        log("new game pid=%d, waiting 2.5s before rfmon3" % pid)
        time.sleep(2.5)
        cmd = '"%s" %d "%s"' % (INJECT, pid, DLL)
        try:
            p = subprocess.run([PY, ASJ, "--nowait", cmd], capture_output=True, text=True, timeout=30)
            log("inject pid=%d rc=%s out=%s err=%s" % (pid, p.returncode,
                                                       (p.stdout or "").strip(), (p.stderr or "").strip()))
        except Exception as e:
            log("inject pid=%d failed: %s" % (pid, e))
        raise SystemExit(0)
    time.sleep(0.1)
