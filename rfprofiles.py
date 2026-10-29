r"""
rfprofiles.py - one per-profile view of the launcher/game/bot config (used by app.py and rfguard.py).

A profile is a directory: C:\SHARE\hwid\profiles\<id>\. It holds the current spoof cfg used by the
guard, a small profile.json (paths only, no secrets) and, when a bot is configured, the bot profile
directory is C:\SHARE\rfbot2\profiles\<bot_profile>\ (Bagnon.dll + BotCore.ini + .target).

The legacy per-instance cfg written by app.py (C:\SHARE\hwid\spoof_<id>.cfg) stays the source of
truth while app.py is running, because it carries the current relay port. The guard never invents a
new relay port; it uses that file, then the profile copy, then a direct-proxy fallback.
"""
import hashlib
import os
import re
import stat
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES_PATH = os.path.join(HERE, "profiles.json")
PROFILE_ROOT = os.path.join(HERE, "profiles")
if os.path.isfile(os.path.join(HERE, "portable.flag")) and os.path.isdir(os.path.join(HERE, "bot", "profiles")):
    RFBOT_ROOT = os.path.join(HERE, "bot")
else:
    RFBOT_ROOT = r"C:\SHARE\rfbot2"
RFBOT_PROFILES = os.path.join(RFBOT_ROOT, "profiles")
LOGDIR = os.path.join(HERE, "logs")


def _norm(p):
    return os.path.normcase(os.path.abspath(p or ""))


def load_profiles(path=PROFILES_PATH):
    import json
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def profiles(cfg=None):
    cfg = cfg or load_profiles()
    return [p for p in cfg.get("profiles", []) if p.get("enabled", True)]


def profile_dir(pid):
    return os.path.join(PROFILE_ROOT, str(pid))


def profile_by_id(pid, cfg=None):
    for p in profiles(cfg):
        if str(p.get("id")) == str(pid):
            return p
    return None


def profile_for_exe(exe, cfg=None):
    """Match the process image (launcher main and its CEF children) to a profile by exe directory."""
    if not exe:
        return None
    d = os.path.dirname(_norm(exe))
    for p in profiles(cfg):
        if d == os.path.dirname(_norm(p.get("game_exe"))):
            return p
    return None


def spoof_dll():
    """Newest spoof build (rfspoof.dll / .new.dll / .next.dll / .build.dll)."""
    best = None
    for name in ("rfspoof.dll", "rfspoof.new.dll", "rfspoof.next.dll", "rfspoof.build.dll"):
        c = os.path.join(HERE, name)
        try:
            if os.path.isfile(c) and (best is None or os.path.getmtime(c) > os.path.getmtime(best)):
                best = c
        except OSError:
            pass
    return best or os.path.join(HERE, "rfspoof.dll")


def guard_mutex_name():
    r"""A portable copy must not share the singleton with C:\SHARE\hwid."""
    if os.path.isfile(os.path.join(HERE, "portable.flag")):
        return "Local\\RFGuardSingleton_" + hashlib.md5(HERE.lower().encode()).hexdigest()[:8]
    return "Local\\RFGuardSingleton"


def _marker_paths(profile):
    pid = str(profile.get("id"))
    mdir = os.path.join(HERE, "meta", "profile_%s" % pid)
    path = os.path.join(mdir, "vcredist_x86.exe")
    return mdir, path, path + ".golden"


def _read_marker(path):
    try:
        with open(path, "r", encoding="ascii", errors="replace") as f:
            cur = f.read().strip()
        if len(cur) == 36 and cur.count("-") == 4:
            return cur
    except OSError:
        pass
    return None


def _set_ro(path, ro=True):
    try:
        os.chmod(path, stat.S_IREAD if ro else (stat.S_IWRITE | stat.S_IREAD))
    except OSError:
        pass


def _write_marker(path, val):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _set_ro(path, False)
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write(val)


def ensure_marker(profile, create=False):
    r"""Use the launcher-created marker: first run leaves it absent (the launcher creates it);
    later runs restore the golden copy if missing/changed and keep both read-only."""
    mdir, path, golden = _marker_paths(profile)
    try:
        os.makedirs(mdir, exist_ok=True)
        g = _read_marker(golden)
        if g:
            if _read_marker(path) != g:
                _write_marker(path, g)
            _set_ro(path, True)
            _set_ro(golden, True)
            return path
        m = _read_marker(path)
        if m:
            _write_marker(golden, m)
            _set_ro(golden, True)
            _set_ro(path, True)
            return path
        if create:
            hw = profile.get("hw") or {}
            seed = "cerberus-profile-%s-%s-%s" % (str(profile.get("id")),
                                                   hw.get("guid") or hw.get("serial") or "",
                                                   hw.get("cname") or "")
            _write_marker(path, str(uuid.uuid5(uuid.NAMESPACE_DNS, seed)))
            _write_marker(golden, _read_marker(path) or "")
            _set_ro(path, True)
            _set_ro(golden, True)
        return path
    except OSError:
        return path


def capture_marker(profile):
    """After the launcher created the marker: save golden + make it read-only."""
    mdir, path, golden = _marker_paths(profile)
    m = _read_marker(path)
    if not m:
        return False
    try:
        g = _read_marker(golden)
        if not g:
            _write_marker(golden, m)
            _set_ro(golden, True)
        elif g != m:
            _write_marker(path, g)
            m = g
        _set_ro(path, True)
        _set_ro(golden, True)
        return True
    except OSError:
        return False


def capture_marker_when_ready(profile, timeout=25.0):
    end = time.time() + timeout
    while time.time() < end:
        if capture_marker(profile):
            return True
        time.sleep(0.2)
    return False


def cfg_text(profile, relay_port=None):
    """The single full spoofer cfg (HWID + net). proxy = local relay when app.py is running."""
    pid = str(profile.get("id"))
    pdir = profile_dir(pid)
    log = os.path.join(LOGDIR, "spoof_%s.log" % pid)
    lines = ["[cfg]", "id=%s" % pid, "min=0", "delay=1", "net=1", "rega=1"]
    proxy = profile.get("proxy") or ""
    if relay_port:
        proxy = "127.0.0.1:%d" % int(relay_port)
    if proxy:
        lines.append("proxy=%s" % proxy)
    lines.append("log=%s" % log)
    lines.append("proxymain=1")
    # Per-profile PC-ID marker (needed for several accounts). RF_META_REAL=1 falls back to the
    # shared real marker. The marker file is created once with a stable UUID and the spoofer
    # redirects reads/writes/stat/find/delete of ...\DeviceSync\ to it.
    if os.environ.get("RF_META_REAL", "0") == "1":
        mdir = r"C:\ProgramData\Microsoft\DeviceSync"
    else:
        mdir = os.path.join(HERE, "meta", "profile_%s" % pid)
    lines.append("metadir=%s" % mdir)
    lines.append("meta=%s" % os.path.join(mdir, "vcredist_x86.exe"))
    hw = profile.get("hw") or {}
    for k in ("serial", "cname", "macaddr", "guid", "biosvendor", "biosver", "biosserial",
              "boardmfr", "boardprod", "boardserial", "sysmfr", "sysprod", "sysver",
              "monid", "cpu", "diskserial", "uuid"):
        if hw.get(k):
            lines.append("%s=%s" % (k, hw[k]))
    for k in ("build", "rammb"):
        if hw.get(k):
            lines.append("%s=%d" % (k, int(hw[k])))
    return "\n".join(lines) + "\n"


def write_profile_cfg(profile, relay_port=None):
    """Write profiles/<id>/rfspoof.cfg (guard copy) and the legacy spoof_<id>.cfg (app/env copy)."""
    pid = str(profile.get("id"))
    os.makedirs(profile_dir(pid), exist_ok=True)
    os.makedirs(LOGDIR, exist_ok=True)
    os.makedirs(os.path.join(HERE, "meta", "profile_%s" % pid), exist_ok=True)
    ensure_marker(profile)
    text = cfg_text(profile, relay_port)
    pdir_cfg = os.path.join(profile_dir(pid), "rfspoof.cfg")
    legacy = os.path.join(HERE, "spoof_%s.cfg" % pid)
    for path in (pdir_cfg, legacy):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        try:
            os.replace(tmp, path)
        except OSError:
            try:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                os.remove(tmp)
            except OSError:
                pass
    return legacy


def _cfg_ok(path):
    """A guard cfg must be full spoofer: net=1, proxy=..., rega=1."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except OSError:
        return False
    low = txt.lower()
    return ("net=1" in low and "proxy=" in low and "rega=1" in low)


def pick_cfg(profile):
    """The cfg the guard should pass: current app cfg, profile copy, then a direct-proxy fallback."""
    pid = str(profile.get("id"))
    for path in (os.path.join(HERE, "spoof_%s.cfg" % pid),
                 os.path.join(profile_dir(pid), "rfspoof.cfg")):
        if os.path.isfile(path) and _cfg_ok(path):
            return path
    return write_profile_cfg(profile, None)


def game_cfg(profile):
    """Separate cfg for the game: lets us keep launcher/CEF on the full profile cfg while
    testing/tuning the game's hook set without app.py overwriting it on the next profile start."""
    pid = str(profile.get("id"))
    path = os.path.join(HERE, "spoof_%s_game.cfg" % pid)
    if not os.path.isfile(path):
        base = pick_cfg(profile)
        try:
            with open(base, encoding="utf-8", errors="replace") as f:
                text = f.read()
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            return base
    return path


def write_game_cfg(profile, relay_port=None):
    """Refresh the game cfg from the current profile settings (app.py at profile start)."""
    pid = str(profile.get("id"))
    ensure_marker(profile)
    path = os.path.join(HERE, "spoof_%s_game.cfg" % pid)
    overrides = os.path.join(HERE, "game_overrides.cfg")
    try:
        text = cfg_text(profile, relay_port)
        if os.path.isfile(overrides):
            with open(overrides, encoding="utf-8", errors="replace") as f:
                text += "\n" + f.read().rstrip() + "\n"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    except OSError:
        pass
    return path


def write_profile_json(profile):
    import json
    pid = str(profile.get("id"))
    os.makedirs(profile_dir(pid), exist_ok=True)
    d = {
        "id": pid,
        "game_exe": profile.get("game_exe") or "",
        "cfg": os.path.join(profile_dir(pid), "rfspoof.cfg"),
        "spoof_dll": spoof_dll(),
        "bot_profile": bot_profile(profile) or "",
        "bot_dir": bot_dir(profile) or "",
    }
    try:
        with open(os.path.join(profile_dir(pid), "profile.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except OSError:
        pass
    return d


def bot_profile(profile):
    r"""Profile name under C:\SHARE\rfbot2\profiles that has a Bagnon.dll, or None."""
    name = profile.get("bot_profile")
    candidates = []
    if name:
        candidates.append(str(name))
    pid = str(profile.get("id"))
    candidates += ["bot%s" % pid, pid, "bot", "main"]
    for c in candidates:
        d = os.path.join(RFBOT_PROFILES, c)
        if os.path.isfile(os.path.join(d, "Bagnon.dll")):
            return c
    return None


def bot_dir(profile):
    c = bot_profile(profile)
    return os.path.join(RFBOT_PROFILES, c) if c else None


def bot_dll(profile):
    d = bot_dir(profile)
    if not d:
        return None
    from_new = os.path.join(d, "Bagnon.new.dll")
    dll = os.path.join(d, "Bagnon.dll")
    if os.path.isfile(from_new) and (not os.path.isfile(dll)
                                     or os.path.getmtime(from_new) > os.path.getmtime(dll)):
        return from_new
    return dll if os.path.isfile(dll) else None


def shared_name(profile):
    d = bot_dir(profile)
    if not d:
        return None
    ini = os.path.join(d, "BotCore.ini")
    try:
        with open(ini, encoding="latin1") as f:
            txt = f.read()
        m = re.search(r"(?im)^\s*SharedName\s*=\s*(.+?)\s*$", txt)
        if m:
            return m.group(1).strip()
    except OSError:
        pass
    return "Local\\RFBotState"


def write_target(profile, pid):
    d = bot_dir(profile)
    if not d:
        return None
    path = os.path.join(d, ".target")
    try:
        with open(path, "w", encoding="ascii") as f:
            f.write(str(int(pid)))
        return path
    except OSError:
        return None


def ensure_dirs():
    for d in (PROFILE_ROOT, LOGDIR):
        os.makedirs(d, exist_ok=True)
