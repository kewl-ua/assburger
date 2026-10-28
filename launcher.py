# -*- coding: utf-8 -*-
"""
launcher.py - start / stop isolated launcher instances.

IMPORTANT timing rule (found empirically on this CEF launcher):
  Injecting a dll into a running instance is fine, but if a SECOND instance starts *after* the
  first was injected, the first exits. Therefore:
      1. start ALL instances (plain, each with its own --user-data-dir),
      2. wait until all their windows are up and settled,
      3. THEN inject the spoof dll into each.
  Also never inject while the process is still initialising (suspended start crashes it): wait
  for the window + a short settle before injecting.

Each profile => spoof_<id>.dll + spoof_<id>.cfg (the dll reads the cfg by its own file name).
"""
import ctypes
import os
import time
from ctypes import wintypes

import inject as inj

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_SUSPENDED = 0x00000004
LOGON_WITH_PROFILE = 0x00000001

HERE = os.path.dirname(os.path.abspath(__file__))
DLL_SRC = os.path.join(HERE, "rfspoof.dll")
LOGDIR = os.path.join(HERE, "logs")
CEFDIR = os.path.join(HERE, "cef")
METADIR = os.path.join(HERE, "meta")


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


kernel32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                    wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                    ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
kernel32.CreateProcessW.restype = wintypes.BOOL
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL


# --------------------------------------------------------------------------- cfg / dll prep
def _cfg_text(profile):
    lines = ["id=%s" % profile["id"], "min=0", "delay=%d" % int(profile.get("_delay", 1))]
    if profile.get("proxy"):
        lines.append("net=1")
        lines.append("proxy=%s" % profile["proxy"])
    else:
        lines.append("net=0")
    lines.append("log=%s" % profile["_log"])
    lines.append("proxymain=1")
    if profile.get("_metadir"):
        lines.append("metadir=%s" % profile["_metadir"])
    if profile.get("_meta"):
        lines.append("meta=%s" % profile["_meta"])
    hw = profile.get("hw") or {}
    for key in ("serial", "cname", "macaddr", "guid", "biosvendor", "biosver", "boardmfr",
                "boardprod", "sysmfr", "sysprod", "sysver", "monid", "diskserial", "cpu",
                "biosserial", "boardserial", "uuid"):
        if hw.get(key):
            lines.append("%s=%s" % (key, hw[key]))
    if hw.get("build"):
        lines.append("build=%d" % int(hw["build"]))
    if hw.get("rammb"):
        lines.append("rammb=%d" % int(hw["rammb"]))
    return "\n".join(lines) + "\n"


def prepare(profile):
    """Write per-profile cfg and remember dll path. One shared rfspoof.dll, per-instance cfg."""
    pid = profile["id"]
    if not os.path.isfile(DLL_SRC):
        raise FileNotFoundError("rfspoof.dll missing - run build.ps1")
    os.makedirs(LOGDIR, exist_ok=True)
    os.makedirs(CEFDIR, exist_ok=True)
    os.makedirs(METADIR, exist_ok=True)
    cfg = os.path.join(HERE, "spoof_%s.cfg" % pid)
    profile["_log"] = os.path.join(LOGDIR, "spoof_%s.log" % pid)
    profile["_dll"] = DLL_SRC
    profile["_cfg"] = cfg
    # per-profile HWID directory: redirect ...\DeviceSync\ (file + folder) into our folder.
    # We create the DIRECTORY only, and let the launcher create the marker file itself.
    mdir = os.path.join(METADIR, "profile_%s" % pid)
    os.makedirs(mdir, exist_ok=True)
    profile["_metadir"] = mdir
    profile["_meta"] = os.path.join(mdir, "vcredist_x86.exe")
    try:
        open(profile["_log"], "w").close()
    except Exception:
        pass
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(_cfg_text(profile))
    return DLL_SRC


# --------------------------------------------------------------------------- process control
def _build_env(extra):
    """Unicode environment block (sorted KEY=VAL, double-null terminated) for CreateProcess.
    Built from the current environment plus *extra* so per-instance vars reach the target even
    through CreateProcessWithLogonW (which does not inherit our env)."""
    env = dict(os.environ)
    env.update(extra)
    items = sorted("%s=%s" % (k, v) for k, v in env.items() if k and "=" not in k)
    block = "\0".join(items) + "\0\0"
    return ctypes.create_unicode_buffer(block)


def start(profile, game_exe, suspended=False):
    """Start the instance. Returns (pid, hProcess, hThread).

    If suspended=True the main thread stays frozen (CREATE_SUSPENDED) so the caller can inject
    the spoof dll BEFORE the process reads any hardware (no race). Call resume(hThread) after.

    The exe path may be overridden per profile via profile["game_exe"].
    """
    prepare(profile)
    udd = os.path.join(CEFDIR, "profile_%s" % profile["id"])
    os.makedirs(udd, exist_ok=True)
    # per-instance config path is passed to the dll via SPOOF_CFG (inherited env)
    os.environ["SPOOF_CFG"] = profile["_cfg"]
    exe = os.path.abspath(profile.get("game_exe") or game_exe)
    cmdline = ctypes.create_unicode_buffer('"%s" --user-data-dir="%s"' % (exe, udd))
    workdir = os.path.dirname(exe)
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    flags = (CREATE_SUSPENDED if suspended else 0) | CREATE_UNICODE_ENVIRONMENT

    user = profile.get("user") or ""
    pwd = profile.get("password") or ""
    # environment block with SPOOF_CFG (CreateProcessWithLogonW does NOT inherit our env)
    env = _build_env({"SPOOF_CFG": profile["_cfg"]})
    env_p = ctypes.cast(env, ctypes.c_void_p) if env else None
    if user:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.CreateProcessWithLogonW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                   wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                                   ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
                                                   ctypes.POINTER(PROCESS_INFORMATION)]
        advapi.CreateProcessWithLogonW.restype = wintypes.BOOL
        ok = advapi.CreateProcessWithLogonW(user, ".", pwd, LOGON_WITH_PROFILE, exe, cmdline,
                                            flags, env_p, workdir,
                                            ctypes.byref(si), ctypes.byref(pi))
    else:
        ok = kernel32.CreateProcessW(exe, cmdline, None, None, False, flags,
                                     env_p, workdir, ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        raise OSError("CreateProcess failed err=%d" % ctypes.get_last_error())
    h = pi.hProcess
    if user:
        full = kernel32.OpenProcess(0x1F0FFF, False, pi.dwProcessId)
        if not full:
            full = kernel32.OpenProcess(0x0002 | 0x0008 | 0x0010 | 0x0020 | 0x0400 | 0x1000, False, pi.dwProcessId)
        if full:
            h = full
    return pi.dwProcessId, h, pi.hThread


def resume(hthread):
    if hthread:
        kernel32.ResumeThread(hthread)
        kernel32.CloseHandle(hthread)


def wait_windows(pids, timeout=25.0):
    """Wait until every pid owns a visible top-level window (or timeout)."""
    end = time.time() + timeout
    need = set(pids)
    while time.time() < end:
        got = visible_windows()
        if need & set(got):
            need -= set(got)
        if not need:
            return True
        time.sleep(0.25)
    return not need


def visible_windows():
    """Map pid -> [titles] for all currently visible top-level windows (our own process only)."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    res = {}
    CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        p = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value:
            res.setdefault(p.value, []).append(buf.value)
        return True

    user32.EnumWindows(CB(cb), 0)
    return res


def inject_instance(pid, dll, h=None):
    """Inject the spoof dll. If h (a handle to the process) is given, use it — required for a
    process started as another user (OpenProcess gives no VM rights across logins)."""
    inj._enable_debug_privilege()
    if not h:
        h = kernel32.OpenProcess(0x1F0FFF, False, pid)
        if not h:
            h = kernel32.OpenProcess(0x0002 | 0x0008 | 0x0010 | 0x0020 | 0x0400 | 0x1000, False, pid)
        if not h:
            raise OSError("OpenProcess failed pid=%d err=%d" % (pid, ctypes.get_last_error()))
        own = True
    else:
        own = False
    try:
        inj._pid_holder["pid"] = pid
        res = None
        for _ in range(80):
            kbase = (inj.peb_kernel32(pid, h)
                     or inj.find_module_base_h(h, "kernel32.dll") or inj.find_module_base_h(h, "KernelBase.dll")
                     or inj.find_module_base(pid, "kernel32.dll"))
            if kbase:
                res = inj.export_rva(h, kbase, "LoadLibraryA")
                if res:
                    break
            time.sleep(0.05)
        if not res:
            raise OSError("LoadLibraryA not resolved")
        data = dll.encode("ascii") + b"\0"
        rb = kernel32.VirtualAllocEx(h, None, len(data), inj.MEM_COMMIT | inj.MEM_RESERVE, inj.PAGE_READWRITE)
        got = ctypes.c_size_t(0)
        kernel32.WriteProcessMemory(h, rb, data, len(data), ctypes.byref(got))
        th = kernel32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(res[0] + res[1]),
                                         ctypes.c_void_p(rb), 0, None)
        kernel32.WaitForSingleObject(th, 8000)
        kernel32.CloseHandle(th)
        return True
    finally:
        if own:
            kernel32.CloseHandle(h)


def child_pids(parent_pid, name_lower):
    """PIDs of processes with the given image name (best-effort, name-based)."""
    return inj.find_pids_by_name(name_lower)



def alive(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    code = wintypes.DWORD(0)
    kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    kernel32.CloseHandle(h)
    return code.value == 259


def kill_pid(pid):
    h = kernel32.OpenProcess(0x0001 | 0x1000, False, pid)  # TERMINATE | QUERY
    if not h:
        return
    kernel32.TerminateProcess(h, 0)
    kernel32.CloseHandle(h)


def run_instances(profiles, game_exe, early=2.0, watch_children=True, watch_seconds=12.0):
    """Start all instances quickly, inject each early (for proxy) + children, then watch.

    Returns {id: pid}. Blocks for watch_seconds.
    """
    started = {}
    for prof in profiles:
        try:
            pid, h, ht = start(prof, game_exe, suspended=True)
            started[prof["id"]] = [pid, h, prof, ht]
        except Exception as e:
            print("start %s failed: %s" % (prof["id"], e))
    # resume all (LDR is built the instant the thread runs), let them settle a hair, then inject.
    # This is well before CEF opens its first socket (~1.4s) and before any HWID read.
    for rec in started.values():
        try:
            resume(rec[3])
        except Exception:
            pass
    time.sleep(float(os.environ.get("SPOOF_EARLY", "0.1") or "0.25"))
    t0 = time.time()
    for pid_id, rec in list(started.items()):
        for attempt in range(40):
            try:
                inject_instance(rec[0], rec[2]["_dll"], rec[1])
                break
            except Exception as e:
                if attempt == 39:
                    print("main inject %s failed: %s" % (pid_id, e))
                else:
                    time.sleep(0.1)
    # watch children of all instances; inject each child with its own instance's dll
    if watch_children:
        name = os.path.basename(game_exe).lower()
        seen = {rec[0] for rec in started.values()}
        first_seen = {}
        main_to_dll = {rec[0]: (rec[2]["_dll"], bool(rec[2].get("inject_children"))) for rec in started.values()}
        while time.time() - t0 < watch_seconds:
            now = time.time()
            for q in inj.find_pids_by_name(name):
                if q in seen:
                    continue
                if q not in first_seen:
                    first_seen[q] = now
                    continue
                if now - first_seen[q] < 0.5:      # let the child settle before injecting
                    continue
                seen.add(q)
                dll, want = _dll_for_child(q, main_to_dll)
                if not want:
                    continue
                try:
                    inject_instance(q, dll)
                except Exception:
                    pass
            time.sleep(0.05)
    return {k: v[0] for k, v in started.items()}


def _dll_for_child(child_pid, main_to_dll):
    """Nearest ancestor main -> (dll, want_children) tuple; falls back to any main."""
    try:
        ppid = _parent_pid(child_pid)
        guard = 0
        while ppid and guard < 10:
            if ppid in main_to_dll:
                return main_to_dll[ppid]
            ppid = _parent_pid(ppid)
            guard += 1
    except Exception:
        pass
    return next(iter(main_to_dll.values()))


def _parent_pid(pid):
    TH32CS_SNAPPROCESS = 0x2
    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == ctypes.c_void_p(-1).value:
        return 0
    pe = PROCESSENTRY32(); pe.dwSize = ctypes.sizeof(pe)
    out = 0
    ok = kernel32.Process32First(snap, ctypes.byref(pe))
    while ok:
        if pe.th32ProcessID == pid:
            out = pe.th32ParentProcessID
            break
        ok = kernel32.Process32Next(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    return out


def run_instance(profile, game_exe, early=2.0, watch_children=True, watch_seconds=12.0):
    return list(run_instances([profile], game_exe, early, watch_children, watch_seconds).values())[0]


def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    # auto-elevate: injection into another user's process needs admin
    if not _is_admin() and "--noelev" not in sys.argv:
        params = " ".join('"%s"' % a for a in sys.argv[1:])
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
                                                 '"%s" %s --noelev' % (os.path.abspath(__file__), params),
                                                 None, 1)
        if rc > 32:
            sys.exit(0)
    import config
    cfg = config.load()
    ids = [a for a in sys.argv[1:] if a != "--noelev"] or [p["id"] for p in cfg["profiles"] if p.get("enabled", True)]
    profs = [p for p in cfg["profiles"] if p["id"] in ids]
    res = run_instances(profs, cfg["game_exe"])
    for pid_id, pid in res.items():
        print("started+injected %s pid=%d" % (pid_id, pid))
