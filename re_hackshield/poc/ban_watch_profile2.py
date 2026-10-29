import importlib.util
import os
import sys
import time

HWID = r"C:\SHARE\hwid"
RB = r"C:\SHARE\rfbot2"
LOG = os.path.join(HWID, "re_hackshield", "logs", "ban_test_profile2.txt")


def load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    sys.modules[name] = m
    s.loader.exec_module(m)
    return m


mm = load("ban_mm", os.path.join(HWID, "manualmap.py"))
sys.path.insert(0, RB)
sys.path.insert(0, os.path.join(RB, "tools"))
import run_bot  # noqa: E402
import importlib.util as iu  # noqa: E402
s = iu.spec_from_file_location("ban_botmm", os.path.join(RB, "tools", "manualmap.py"))
bm = iu.module_from_spec(s)
sys.modules["ban_botmm"] = bm
s.loader.exec_module(bm)
run_bot.mm = bm


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg + "\n")


def pid_for(path_lower):
    for p in bm.find_game_pids():
        try:
            import ctypes
            from ctypes import wintypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            h = k.OpenProcess(0x1000, False, p)
            if not h:
                continue
            buf = ctypes.create_unicode_buffer(1024)
            n = wintypes.DWORD(1024)
            ok = k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
            k.CloseHandle(h)
            if ok and buf.value.lower().endswith(path_lower):
                return p
        except Exception:
            pass
    return None


def main():
    target = r"\share\cerberus2\rf_online_4gb.bin"
    log("ban-test start profile=2 account=brians target=%s" % target)
    while True:
        p = pid_for(target)
        marker = os.path.join(HWID, "meta", "profile_2", "vcredist_x86.exe")
        acc = r"C:\SHARE\CERBERUS2\System\accounts.json"
        if not p:
            log("profile2 game NOT RUNNING")
        else:
            try:
                st = mm.spoof_state(p)
                bl = run_bot.module_live(p, os.path.join(RB, "profiles", "bot2", "Bagnon.dll"))
                log("pid=%d spoof=%s ready=%s peb=%s bot=%s marker_mtime=%s accounts_mtime=%s"
                    % (p, mm.spoof_live(p), bool(st and st.get("ready")), mm.spoof_modules(p),
                       bl,
                       time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(marker)))
                       if os.path.isfile(marker) else "-",
                       time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(acc)))
                       if os.path.isfile(acc) else "-"))
            except Exception as e:
                log("pid=%d check error: %s" % (p, e))
        time.sleep(60)


if __name__ == "__main__":
    main()
