r"""
inject.py - external injector for RF Online. Injects a DLL into the running game WITHOUT putting
anything into the game folder (no dinput8.dll proxy, no renaming).

Why this is the safe injection:
  - the game folder stays 100% clean; the DLL lives next to this script,
  - injection is a plain CreateRemoteThread + LoadLibraryA (the most "normal" kind),
  - the injected DLL (rfcore.dll = the HPBars build) calls the game's own functions for the strong
    actions (select target / walk / use belt slot) and reads memory - it does NOT patch game code,
    it only replaces 5 vtable slots (that is what the bot needs to run on the game thread).

Target DLL: rfcore.dll next to this file (copy of the built dinput8.dll).
Also put HPBars.ini next to it: the DLL builds HPBars.ini / HPBars.log paths from its own folder,
so the game folder stays clean.

Usage:
    python inject.py                 # find the game, inject .\rfcore.dll
    python inject.py path\to\other.dll
Run as admin if the game is admin. Works from 32- or 64-bit Python; 64-bit Python into the 32-bit
game is handled by resolving LoadLibraryA in the TARGET process (not in ours).
"""

import ctypes
import os
import sys
import time
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ------------------------------------------------------------------ access rights
PROCESS_CREATE_THREAD     = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION      = 0x0008
PROCESS_VM_WRITE          = 0x0020
PROCESS_VM_READ           = 0x0010
PROCESS_ALL_ACCESS        = 0x1F0FFF

MEM_COMMIT  = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE  = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
WAIT_OBJECT_0 = 0x0

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
kernel32.IsWow64Process.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                    wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = wintypes.BOOL
kernel32.CreateRemoteThread.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
kernel32.CreateRemoteThread.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Module32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Module32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.GetModuleHandleA.argtypes = [wintypes.LPCSTR]
kernel32.GetModuleHandleA.restype = ctypes.c_void_p
kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, wintypes.LPCSTR]
kernel32.GetProcAddress.restype = ctypes.c_void_p
kernel32.LoadLibraryA.argtypes = [wintypes.LPCSTR]
kernel32.LoadLibraryA.restype = ctypes.c_void_p
kernel32.GetModuleFileNameA.argtypes = [ctypes.c_void_p, wintypes.LPSTR, wintypes.DWORD]


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
                ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.c_void_p),
                ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
                ("szModule", ctypes.c_char * 256), ("szExePath", ctypes.c_char * 260)]


def _enable_debug_privilege():
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]

    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID)]
    advapi.LookupPrivilegeValueW.restype = wintypes.BOOL
    advapi.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TOKEN_PRIVILEGES),
                                             wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    advapi.AdjustTokenPrivileges.restype = wintypes.BOOL

    tok = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel32.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(tok)):
        return False
    luid = LUID()
    if not advapi.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
        kernel32.CloseHandle(tok)
        return False
    tp = TOKEN_PRIVILEGES()
    tp.PrivilegeCount = 1
    tp.Privileges[0].Luid = luid
    tp.Privileges[0].Attributes = 0x2  # SE_PRIVILEGE_ENABLED
    advapi.AdjustTokenPrivileges(tok, False, ctypes.byref(tp), 0, None, None)
    rc = ctypes.get_last_error()
    kernel32.CloseHandle(tok)
    return rc == 0


def find_pids_by_name(name_lower):
    """All PIDs whose image base name equals name_lower."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return []
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(pe)
    out = []
    ok = kernel32.Process32First(snap, ctypes.byref(pe))
    while ok:
        if pe.szExeFile.decode("latin1").lower() == name_lower:
            out.append(pe.th32ProcessID)
        ok = kernel32.Process32Next(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    return out


def is_wow64(pid):
    """True if the target runs as 32-bit (so a 32-bit DLL can be injected)."""
    try:
        h = kernel32.OpenProcess(0x0400 | 0x1000, False, pid)  # QUERY_INFORMATION | QUERY_LIMITED
        if not h:
            return False
        b = wintypes.BOOL(0)
        r = kernel32.IsWow64Process(h, ctypes.byref(b))
        kernel32.CloseHandle(h)
        return bool(r) and bool(b.value)
    except Exception:
        return False


def find_game_pid(want=None):
    """PID of the target (prefers a 32-bit process). want: exe name/prefix; default rf_online*/cerberus."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return None
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(pe)
    matches = []
    ok = kernel32.Process32First(snap, ctypes.byref(pe))
    while ok:
        name = pe.szExeFile.decode("latin1").lower()
        hit = False
        if want:
            w = want.lower()
            hit = name == w or name.startswith(w.replace(".exe", ""))
        else:
            hit = (name.startswith("rf_online") and (name.endswith(".bin") or name.endswith(".exe"))) \
                  or name == "cerberus-games.exe"
        if hit:
            matches.append(pe.th32ProcessID)
        ok = kernel32.Process32Next(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    if not matches:
        return None
    for m in matches:                 # prefer a 32-bit process for our 32-bit DLL
        if is_wow64(m):
            return m
    return matches[0]


def _u16(b, o): return int.from_bytes(b[o:o + 2], "little")
def _u32(b, o): return int.from_bytes(b[o:o + 4], "little")


def _rpm(h, addr, size):
    buf = (ctypes.c_char * size)()
    got = ctypes.c_size_t(0)
    if not kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
        return None
    return buf.raw[:got.value]


def find_module_base(pid, name):
    """Base address of a module inside the target (32-bit value for a WOW64 target)."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == INVALID_HANDLE_VALUE:
        return None
    me = MODULEENTRY32()
    me.dwSize = ctypes.sizeof(me)
    base = None
    ok = kernel32.Module32First(snap, ctypes.byref(me))
    while ok:
        if me.szModule.decode("latin1").lower() == name.lower():
            base = me.modBaseAddr
            break
        ok = kernel32.Module32Next(snap, ctypes.byref(me))
    kernel32.CloseHandle(snap)
    return base


def find_module_base_h(h, name):
    """Base of a module in the target using OUR handle (psapi) — works for another user's process."""
    try:
        psapi = ctypes.WinDLL("psapi")
        psapi.EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        arr = (ctypes.c_void_p * 2048)()
        need = wintypes.DWORD(0)
        if not psapi.EnumProcessModules(h, arr, ctypes.sizeof(arr), ctypes.byref(need)):
            return None
        cnt = need.value // ctypes.sizeof(ctypes.c_void_p)
        buf = ctypes.create_unicode_buffer(260)
        for i in range(min(cnt, 2048)):
            if arr[i] and psapi.GetModuleFileNameExW(h, arr[i], buf, 260):
                if os.path.basename(buf.value).lower() == name.lower():
                    return arr[i]
    except Exception:
        pass
    return None


def _rpm32(h, addr):
    b = _rpm(h, addr, 4)
    return int.from_bytes(b, "little") if b else 0


def _rpm_wstr(h, addr, chars):
    b = _rpm(h, addr, chars * 2)
    return b.decode("utf-16le", "replace") if b else ""


def peb_kernel32(pid, h):
    """kernel32 base via the target PEB (works while the process is SUSPENDED). WOW64-aware."""
    try:
        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        ntdll.NtQueryInformationProcess.restype = ctypes.c_long
        buf = ctypes.c_void_p(0)
        ret = wintypes.DWORD(0)
        if ntdll.NtQueryInformationProcess(wintypes.HANDLE(h), 26, ctypes.byref(buf),
                                           ctypes.sizeof(ctypes.c_void_p), ctypes.byref(ret)) != 0:
            return None
        peb = buf.value & 0xFFFFFFFF
        if not peb:
            return None
        ldr = _rpm32(h, peb + 0x0C)          # PEB32.Ldr
        if not ldr:
            return None
        head = ldr + 0x0C                     # &Ldr.InLoadOrderModuleList
        cur = _rpm32(h, head)
        for _ in range(400):
            if not cur or cur == head:
                break
            entry = cur                       # InLoadOrderLinks at entry+0
            base = _rpm32(h, entry + 0x18)    # DllBase
            name_len = _rpm32(h, entry + 0x2C) & 0xFFFF   # BaseDllName.Length
            name_ptr = _rpm32(h, entry + 0x30)             # BaseDllName.Buffer
            name = _rpm_wstr(h, name_ptr, min(name_len // 2, 64))
            if name.lower() in ("kernel32.dll", "kernelbase.dll"):
                return base
            cur = _rpm32(h, cur)
    except Exception:
        pass
    return None


def export_rva(h, base, func):
    """RVA of an export in the target module 'base' (handles forwarders by one level)."""
    dos = _rpm(h, base, 0x40)
    if not dos or dos[:2] != b"MZ":
        return None
    pe = base + _u32(dos, 0x3C)
    hdr = _rpm(h, pe, 0x100)
    if not hdr or hdr[:4] != b"PE\0\0":
        return None
    opt = 0x18
    magic = _u16(hdr, opt)
    dd = opt + (0x60 if magic == 0x10B else 0x70)
    exp_rva = _u32(hdr, dd)
    exp_size = _u32(hdr, dd + 4)
    if not exp_rva:
        return None
    exp = _rpm(h, base + exp_rva, 0x28)
    nnames = _u32(exp, 0x18)
    names_rva = _u32(exp, 0x20)
    ords_rva = _u32(exp, 0x24)
    funcs_rva = _u32(exp, 0x1C)
    names = _rpm(h, base + names_rva, nnames * 4)
    funcs = _rpm(h, base + funcs_rva, nnames * 4)
    ords = _rpm(h, base + ords_rva, nnames * 2)
    for i in range(nnames):
        nr = _u32(names, i * 4)
        nb = _rpm(h, base + nr, 64)
        if not nb:
            continue
        nm = nb.split(b"\0")[0].decode("latin1")
        if nm == func:
            idx = _u16(ords, i * 2)
            frva = _u32(funcs, idx * 4)
            # forwarder? rva inside the export directory range -> "DLL.Func"
            if exp_rva <= frva < exp_rva + exp_size:
                fb = _rpm(h, base + frva, 64)
                fwd = fb.split(b"\0")[0].decode("latin1")
                dll, _, fn = fwd.partition(".")
                wbase = find_module_base(pid_of(h), dll)
                if wbase:
                    return (wbase, fn)   # caller must use this base
            return (base, frva)
    return None


_pid_holder = {}


def pid_of(_h):
    return _pid_holder["pid"]


def inject(pid, dll_path):
    dll_path = os.path.abspath(dll_path)
    if not os.path.isfile(dll_path):
        raise FileNotFoundError(dll_path)

    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        h = kernel32.OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
                                 PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ, False, pid)
    if not h:
        raise OSError("OpenProcess failed (run as admin) err=%d" % ctypes.get_last_error())

    try:
        _pid_holder["pid"] = pid
        remote_load = None
        # Preferred: resolve LoadLibraryA inside the TARGET (works 64-bit host -> 32-bit game).
        try:
            kbase = find_module_base(pid, "kernel32.dll") or find_module_base(pid, "KernelBase.dll")
            if kbase:
                res = export_rva(h, kbase, "LoadLibraryA")
                if not res:
                    kb2 = find_module_base(pid, "KernelBase.dll")
                    res = export_rva(h, kb2, "LoadLibraryA") if kb2 else None
                if res:
                    remote_load = res[0] + res[1]
        except Exception as e:
            print("  (target export resolve failed: %s)" % e)

        # Fallback for a 32-bit injector: same-bitness shares kernel32 base on the same boot.
        if not remote_load and ctypes.sizeof(ctypes.c_void_p) == 4:
            k = kernel32.GetModuleHandleA(b"kernel32.dll")
            remote_load = kernel32.GetProcAddress(ctypes.c_void_p(k), b"LoadLibraryA")
        if not remote_load:
            raise OSError("LoadLibraryA not resolved (use 32-bit Python, or run as admin)")
        print("  remote LoadLibraryA = 0x%08X" % remote_load)

        data = dll_path.encode("ascii") + b"\0"
        remote_buf = kernel32.VirtualAllocEx(h, None, len(data), MEM_COMMIT | MEM_RESERVE,
                                             PAGE_READWRITE)
        if not remote_buf:
            raise OSError("VirtualAllocEx failed")
        got = ctypes.c_size_t(0)
        if not kernel32.WriteProcessMemory(h, remote_buf, data, len(data), ctypes.byref(got)):
            raise OSError("WriteProcessMemory failed")

        tid = wintypes.DWORD(0)
        th = kernel32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(remote_load),
                                         ctypes.c_void_p(remote_buf), 0, ctypes.byref(tid))
        if not th:
            raise OSError("CreateRemoteThread failed err=%d" % ctypes.get_last_error())
        kernel32.WaitForSingleObject(th, 8000)
        code = wintypes.DWORD(0)
        kernel32.GetExitCodeThread(th, ctypes.byref(code))
        kernel32.CloseHandle(th)
        kernel32.VirtualFreeEx(h, remote_buf, 0, MEM_RELEASE)
        return code.value  # HMODULE (nonzero = loaded)
    finally:
        kernel32.CloseHandle(h)


def main():
    _enable_debug_privilege()
    args = sys.argv[1:]
    want = None
    if "--exe" in args:
        i = args.index("--exe")
        want = args[i + 1]
        del args[i:i + 2]
    dll = args[0] if args else os.path.join(os.path.dirname(os.path.abspath(__file__)), "spoof.dll")

    pid = find_game_pid(want)
    if not pid:
        print("target process not running (looked for %s)." % (want or "rf_online*/cerberus-games"))
        return 1
    print("pid = %d, injecting %s" % (pid, dll))
    try:
        hmod = inject(pid, dll)
    except Exception as e:
        print("inject failed:", e)
        return 1
    if not hmod:
        print("LoadLibrary returned NULL in target (DLL exists? bitness? see the game's log).")
        return 1
    print("injected, remote HMODULE = 0x%08X" % hmod)
    print("HPBars.log / HPBars.ini should now be written next to %s" % dll)
    time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
