r"""
rfguard.py - one elevated guard for the CERBERUS profile.

It covers every process of a profile the same way, with no LoadLibrary:
  * launcher main (CERBERUS-GAMES.exe) and its CEF children -> manual-mapped full spoofer (HWID + net);
  * game (RF_Online_4gb.bin) -> manual-mapped full spoofer + the manual-mapped BotCore (Bagnon.dll).

One copy per process: spoof.c creates Local\RFSpoofMutex_<pid> (a second map idles) and publishes
Local\RFSpoofState_<pid>; the guard checks both before mapping. The bot is reused through
Local\RFBotState_<name> (rfbot2's module_live). app.py + the guard share the same manualmap.py and
the same per-profile cfg (rfprofiles.py), so a process is never mapped twice by accident.

The guard is fail-closed: if the spoofer cannot be mapped after a few retries, it kills the process
(so it can never run "silently without spoof") and logs it. RF_KILL_ON_FAIL=0 disables the kill.

Run (elevated):  pythonw rfguard.py --detach
Stop:            python rfguard.py --stop
One pass:        python rfguard.py --once
"""
import argparse
import ctypes
import os
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import manualmap
import rfprofiles

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

LOGDIR = os.path.join(HERE, "logs")
LOGPATH = os.path.join(LOGDIR, "rfguard.log")
STOPFILE = os.path.join(LOGDIR, "rfguard.stop")
SINGLETON = "Local\\RFGuardSingleton"
RFBOT = (os.path.join(HERE, "bot")
         if os.path.isfile(os.path.join(HERE, "portable.flag")) and os.path.isdir(os.path.join(HERE, "bot", "profiles"))
         else r"C:\SHARE\rfbot2")

kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
ntdll.NtQueryInformationProcess.restype = ctypes.c_long

LOG_LOCK = None


def log(msg):
    line = time.strftime("[%H:%M:%S] ") + str(msg)
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        with open(LOGPATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def is_admin():
    try:
        return shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elevate(args):
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(pyw):
        exe = pyw
    params = '"%s" --elevated --detach %s' % (os.path.abspath(__file__), " ".join(args))
    r = 0
    try:
        r = shell32.ShellExecuteW(None, "runas", exe, params, HERE, 0)
        log("elevation requested (ShellExecuteW=%d)" % int(r or 0))
    except Exception as e:
        log("elevation failed: %s" % e)
    return 1 if r and int(r) > 32 else 0


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


def _u16(b, o):
    return int.from_bytes(b[o:o + 2], "little")


def _u32(b, o):
    return int.from_bytes(b[o:o + 4], "little")


def _rpm(h, addr, size):
    buf = (ctypes.c_char * size)()
    got = ctypes.c_size_t(0)
    if not kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
        return None
    return buf.raw[:got.value]


def image_path(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
    finally:
        kernel32.CloseHandle(h)
    return ""


def command_line(pid):
    """Best-effort command line from the 32-bit PEB (works for WOW64 targets)."""
    h = kernel32.OpenProcess(0x0410, False, pid)   # QUERY_INFORMATION | VM_READ
    if not h:
        return ""
    try:
        peb = ctypes.c_void_p(0)
        ret = wintypes.DWORD(0)
        if ntdll.NtQueryInformationProcess(wintypes.HANDLE(h), 26, ctypes.byref(peb),
                                           ctypes.sizeof(ctypes.c_void_p), ctypes.byref(ret)) != 0:
            return ""
        peb = peb.value & 0xFFFFFFFF
        if not peb:
            return ""
        params = _u32(_rpm(h, peb + 0x10, 4) or b"\0" * 4, 0)
        if not params:
            return ""
        us = _rpm(h, params + 0x40, 8)
        if not us:
            return ""
        ln = _u16(us, 0)
        ptr = _u32(us, 4)
        data = _rpm(h, ptr, min(ln, 2048)) or b""
        return data.decode("utf-16le", "replace")
    except Exception:
        return ""
    finally:
        kernel32.CloseHandle(h)


def snapshot():
    out = []
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if snap == ctypes.c_void_p(-1).value:
        return out
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(pe)
    ok = kernel32.Process32First(snap, ctypes.byref(pe))
    while ok:
        out.append((pe.th32ProcessID, pe.szExeFile.decode("latin1", "replace"),
                    pe.th32ParentProcessID))
        ok = kernel32.Process32Next(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    return out


def alive(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    code = wintypes.DWORD(0)
    kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    kernel32.CloseHandle(h)
    return code.value == 259


def kill(pid, why):
    h = kernel32.OpenProcess(0x0001 | 0x1000, False, pid)
    if not h:
        log("FAIL-CLOSED: cannot open pid %d to kill (%s)" % (pid, why))
        return False
    try:
        ok = kernel32.TerminateProcess(h, 0)
        log("FAIL-CLOSED: killed pid %d (%s), ok=%s" % (pid, why, bool(ok)))
        return bool(ok)
    finally:
        kernel32.CloseHandle(h)


def _rfbot():
    """Load rfbot2's run_bot with rfbot2's own tools/manualmap (not the spoofer mapper)."""
    if RFBOT not in sys.path:
        sys.path.insert(0, RFBOT)
    import importlib.util
    name = "rfbot2_manualmap"
    botmm = sys.modules.get(name)
    if botmm is None:
        path = os.path.join(RFBOT, "tools", "manualmap.py")
        spec = importlib.util.spec_from_file_location(name, path)
        botmm = importlib.util.module_from_spec(spec)
        sys.modules[name] = botmm
        spec.loader.exec_module(botmm)
    import run_bot  # noqa: E402  (loads rfbot.py for the shm layout)
    run_bot.mm = botmm
    return run_bot


def bot_live(pid, dll):
    try:
        return _rfbot().module_live(pid, dll)
    except Exception:
        return False


def map_bot(pid, profile):
    dll = rfprofiles.bot_dll(profile)
    if not dll:
        return None
    d = rfprofiles.bot_dir(profile)
    if not d:
        return None
    rfprofiles.write_target(profile, pid)
    if bot_live(pid, dll):
        return "live"
    try:
        rb = _rfbot()
        base = manualmap.read_record(pid, "bot")
        if base and base.get("pid") == pid and base.get("base") \
                and manualmap.mapped_region(pid, base["base"]):
            return "mapped"
        pid2, base2, reused = rb.find_and_map(dll=dll, pid=pid, then_unlink=True)
        manualmap._write_record(pid, base2, dll, "", "bot", "rfbot2/manualmap")
        log("bot mapped pid=%d base=0x%08X reused=%s (%s)" % (pid, base2 or 0, reused, d))
        return "mapped"
    except Exception as e:
        log("bot map pid=%d failed: %s" % (pid, e))
        raise


class Guard(object):
    def __init__(self, cfg=None, verbose=False, once=False):
        self.cfg = cfg or rfprofiles.load_profiles()
        self.verbose = verbose
        self.once = once
        self.seen = {}
        self.kill_on_fail = os.environ.get("RF_KILL_ON_FAIL", "1") != "0"
        self.bot_required = os.environ.get("RF_BOT_REQUIRED", "0") == "1"

    def _kind(self, name, cmd):
        n = name.lower()
        if n.startswith("rf_online"):
            return "game"
        if n == "cerberus-games.exe":
            c = (cmd or "").lower()
            if "--type=crashpad-handler" in c:
                return "crashpad"
            if "--type=" in c:
                return "cef"
            return "launcher"
        return None

    def _map_spoof(self, pid, profile, rec):
        if rec.get("kind") == "game" and os.path.isfile(os.path.join(HERE, "game_map.off")):
            log("game_map.off: game pid=%d left without the spoofer" % pid)
            rec["spoof"] = "off"
            return True
        try:
            rfprofiles.ensure_marker(profile, create=False)
        except Exception:
            pass
        dll = rfprofiles.spoof_dll()
        cfg = (rfprofiles.game_cfg(profile) if rec.get("kind") == "game"
               else rfprofiles.pick_cfg(profile))
        if manualmap.spoof_live(pid):
            rec["spoof"] = "live"
            return True
        legacy = manualmap.spoof_modules(pid)
        if legacy and not manualmap.spoof_mutex_exists(pid):
            # an old LoadLibrary'd spoofer from a pre-manual-map launch: do not add a second copy
            log("spoof pid=%d legacy modules present (%s), skip to avoid double hooks"
                % (pid, ",".join(legacy)))
            rec["spoof"] = "legacy"
            return True
        now = time.time()
        if now - rec.get("last_try", 0) < 1.0:
            return rec.get("spoof") == "ok"
        rec["last_try"] = now
        rec["tries"] = rec.get("tries", 0) + 1
        try:
            base, reused = manualmap.map_module(pid, dll, cfg=cfg, log=lambda m: log("  " + m),
                                                wait_ready=True, ready_timeout=15.0)
            rec["spoof"] = "ok"
            rec["base"] = base
            log("spoof pid=%d base=0x%08X reused=%s cfg=%s" % (pid, base or 0, reused,
                                                               os.path.basename(cfg)))
            return True
        except Exception as e:
            log("spoof pid=%d attempt %d failed: %s" % (pid, rec["tries"], e))
            rec["spoof"] = "fail"
            if (self.kill_on_fail and rec.get("kind") in ("launcher", "game")
                    and rec["tries"] >= 5 and alive(pid)):
                kill(pid, "spoof map failed")
                rec["spoof"] = "killed"
            return False

    def _map_bot(self, pid, profile, rec):
        if os.path.isfile(os.path.join(HERE, "bot_map.off")):
            rec["bot"] = "off"
            return True
        if rec.get("bot") in ("live", "mapped"):
            return True
        now = time.time()
        if now - rec.get("bot_try", 0) < 2.0:
            return False
        rec["bot_try"] = now
        rec["bot_tries"] = rec.get("bot_tries", 0) + 1
        try:
            state = map_bot(pid, profile)
            if state:
                rec["bot"] = state
                log("bot pid=%d %s" % (pid, state))
                return True
        except Exception:
            rec["bot"] = "fail"
            if self.bot_required and rec.get("bot_tries", 0) >= 5 and alive(pid):
                kill(pid, "bot map failed")
                rec["bot"] = "killed"
        return False

    def scan(self):
        procs = snapshot()
        cur = set()
        for pid, name, ppid in procs:
            kind = self._kind(name, "")
            if not kind:
                continue
            exe = image_path(pid)
            profile = rfprofiles.profile_for_exe(exe, self.cfg)
            if not profile:
                continue
            if kind == "launcher":
                cmd = command_line(pid)
                kind = self._kind(name, cmd)
            if kind == "crashpad":
                continue
            cur.add(pid)
            rec = self.seen.get(pid)
            if rec is None:
                rec = {"first": time.time(), "kind": kind, "profile": str(profile.get("id")),
                       "spoof": None, "bot": None, "tries": 0}
                self.seen[pid] = rec
                log("seen %s pid=%d profile=%s %s" % (kind, pid, profile.get("id"),
                                                      os.path.basename(exe)))
            delay = 0.8 if kind == "launcher" else (0.15 if kind == "game" else 0.4)
            if time.time() - rec["first"] < delay:
                continue
            if rec.get("spoof") not in ("ok", "live", "legacy"):
                self._map_spoof(pid, profile, rec)
            if kind == "game" and rec.get("spoof") in ("ok", "live", "legacy"):
                self._map_bot(pid, profile, rec)
        for pid in list(self.seen):
            if pid not in cur:
                self.seen.pop(pid, None)

    def run(self):
        rfprofiles.ensure_dirs()
        log("guard start pid=%d admin=%s spoof_dll=%s"
            % (os.getpid(), is_admin(), os.path.basename(rfprofiles.spoof_dll())))
        # graceful handover from the old watchinj_multi (LoadLibrary guard): it checks this file
        if any(n.lower() == "watchinj_multi.exe" for _pid, n, _pp in snapshot()):
            try:
                open(os.path.join(HERE, "re_hackshield", "logs", "watch_inject_multi.stop"), "w").close()
                log("asked the legacy watchinj_multi to stop (stop file)")
            except OSError as e:
                log("legacy guard stop file failed: %s" % e)
        while True:
            if os.path.isfile(STOPFILE):
                log("stop file found, guard exit")
                try:
                    os.remove(STOPFILE)
                except OSError:
                    pass
                return 0
            try:
                self.scan()
            except Exception as e:
                log("scan error: %s" % e)
            if self.once:
                return 0
            time.sleep(0.25)


def _singleton():
    h = kernel32.CreateMutexW(None, False, SINGLETON)
    err = ctypes.get_last_error()
    if h and err == 183:   # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(h)
        return None
    return h


def main(argv=None):
    argv = argv or sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--detach", action="store_true")
    ap.add_argument("--elevated", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--profile", default=None, help="only this profile id")
    args = ap.parse_args(argv)

    rfprofiles.ensure_dirs()
    if args.stop:
        try:
            open(STOPFILE, "w").close()
        except OSError:
            pass
        log("stop requested")
        return 0

    if not is_admin() and not args.elevated:
        return elevate([a for a in argv if a not in ("--elevated",)])
    manualmap.enable_debug_privilege()

    hold = None
    if not args.once:
        if not args.force:
            hold = _singleton()
            if hold is None:
                log("another guard is already running")
                return 0
    try:
        cfg = rfprofiles.load_profiles()
        if args.profile:
            cfg["profiles"] = [p for p in cfg.get("profiles", [])
                               if str(p.get("id")) == str(args.profile)]
        for p in rfprofiles.profiles(cfg):
            rfprofiles.write_profile_json(p)
        return Guard(cfg, args.verbose, args.once).run()
    finally:
        if hold:
            kernel32.CloseHandle(hold)


if __name__ == "__main__":
    sys.exit(main())
