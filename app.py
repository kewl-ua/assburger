# -*- coding: utf-8 -*-
"""
app.py - one-file Cerberus multi-launcher (RF Online HWID spoof).

Everything needed for ONE launch lives here:
 * the per-process launcher (start / kill / manual map),
 * the shared manual PE mapper (manualmap.py; no LoadLibrary, TLS-aware),
  * the validated, atomically-saved profile store,
  * the headless model layer (ProfileModel / AppModel) - no tkinter, no launcher,
  * the tkinter control panel (one profile per isolated launcher window).

The spoof DLL source is NOT duplicated here: it lives in spoof.c next to this file and is
compiled to rfspoof.dll on first run (ensure_dll). Edit spoof.c, delete rfspoof.dll, relaunch.

Sections below are inlined from what used to be separate modules (config / profiles_model /
hwgen / gui). If you prefer a thin app.py that imports those modules instead, everything here
is importable: they are just classes/functions in this one namespace.

Run:  double-click start.cmd, or  python app.py   (self-elevates: injection needs admin).

Only the game exe, spoof.c, rfspoof.dll (auto-built) and the native per-profile spoof_<id>.cfg
files are written next to this script. No other .py files are required.
"""

import ctypes
import manualmap
import rfprofiles
import json
import os
import select
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
METADIR = os.path.join(HERE, "meta")
LOGDIR = os.path.join(HERE, "logs")
CEFDIR = os.path.join(HERE, "cef")

DEBUG_PROCESS = 0x00000001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
PAGE_READONLY = 0x02
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
IMAGE_SCN_MEM_WRITE = 0x80000000
IMAGE_SCN_MEM_EXECUTE = 0x20000000
TH32CS_SNAPTHREAD = 0x00000004
TH32CS_SNAPMODULE = 0x00000008

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
advapi = ctypes.WinDLL("advapi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                    wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.CreateRemoteThread.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
kernel32.CreateRemoteThread.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                      wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
kernel32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenMutexW.restype = wintypes.HANDLE


# =========================================================================== tiny helpers
def log(msg):
    line = time.strftime("[%H:%M:%S] ") + str(msg)
    if LOG_QUEUE is not None:
        LOG_QUEUE.put(line)
    print(line)


LOG_QUEUE = None                      # queue for GUI log lines


def is_admin():
    try:
        return shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


# =========================================================================== profile store
# Inlined from config.py: schema versioning, migration, normalization, strict validation and an
# atomic+durable writer. Nothing here touches the display or launcher, so it is testable headless.
PROFILES_PATH = os.path.join(HERE, "profiles.json")
DEFAULT_GAME = r"C:\SHARE\CERBERUS\CERBERUS-GAMES.exe"

SCHEMA_VERSION = 1

_PROFILE_STR_FIELDS = ("label", "user", "password", "proxy", "game_exe")
_PROFILE_BOOL_FIELDS = (("inject_children", False), ("enabled", True))
_HW_INT_FIELDS = ("build", "rammb")


class ConfigError(Exception):
    """Raised for any unusable config: unreadable file, invalid JSON, or schema violation."""
    pass


def _as_str(v, default=""):
    """Coerce to str without turning booleans into 'True'/'False'."""
    if v is None or isinstance(v, bool):
        return default
    return v if isinstance(v, str) else str(v)


def _as_int(v, default=0):
    """Coerce to int. Accepts int, float, and digit strings (optionally signed/space-padded)."""
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        body = s[1:] if s[:1] in "+-" else s
        if body.isdigit():
            try:
                return int(s)
            except ValueError:
                return default
    return default


def _as_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
    return default


def _migrate_0_to_1(cfg):
    """Legacy files had no 'version' field. The layout is otherwise compatible, so this only
    stamps the version (done by migrate() after the chain). Future steps go here, one per jump."""
    return cfg


_MIGRATIONS = {0: _migrate_0_to_1}


def migrate(cfg):
    """Upgrade *cfg* in place from whatever version it declares to SCHEMA_VERSION."""
    if not isinstance(cfg, dict):
        raise ConfigError("config root must be a JSON object, got %s" % type(cfg).__name__)
    raw_ver = cfg.get("version")
    ver = 0 if raw_ver is None else raw_ver           # unversioned == legacy v0
    try:
        ver = int(ver)
    except (TypeError, ValueError):
        raise ConfigError("invalid schema version: %r" % (raw_ver,))
    if ver > SCHEMA_VERSION:
        raise ConfigError(
            "profiles.json schema version %d is newer than supported %d; update the launcher"
            % (ver, SCHEMA_VERSION))
    while ver < SCHEMA_VERSION:
        step = _MIGRATIONS.get(ver)
        if step is None:
            raise ConfigError("no migration path from schema version %d" % ver)
        cfg = step(cfg)
        ver += 1
    cfg["version"] = SCHEMA_VERSION
    return cfg


def _normalize_profile(p, idx):
    if not isinstance(p, dict):
        raise ConfigError("profile #%d is not an object" % idx)
    p["id"] = _as_str(p.get("id")).strip()
    for f in _PROFILE_STR_FIELDS:
        p[f] = _as_str(p.get(f))
    for f, dflt in _PROFILE_BOOL_FIELDS:
        p[f] = _as_bool(p.get(f), dflt)
    hw = p.get("hw")
    if hw is None:
        hw = {}
    if not isinstance(hw, dict):
        raise ConfigError("profile %r: 'hw' must be an object" % (p.get("id") or idx))
    for f in _HW_INT_FIELDS:
        if f in hw:
            hw[f] = _as_int(hw.get(f))
    p["hw"] = hw
    return p


def normalize(cfg):
    """Coerce field types and fill defaults, preserving unknown keys. Mutates and returns *cfg*."""
    if not isinstance(cfg, dict):
        raise ConfigError("config root must be a JSON object, got %s" % type(cfg).__name__)
    cfg.setdefault("version", SCHEMA_VERSION)
    cfg["game_exe"] = _as_str(cfg.get("game_exe"), DEFAULT_GAME)
    profiles = cfg.get("profiles")
    if profiles is None:
        profiles = []
    if not isinstance(profiles, list):
        raise ConfigError("'profiles' must be a list, got %s" % type(profiles).__name__)
    cfg["profiles"] = [_normalize_profile(p, i) for i, p in enumerate(profiles)]
    return cfg


def validate(cfg):
    """Raise ConfigError on any structural problem. Call after normalize() for type guarantees."""
    if not isinstance(cfg, dict):
        raise ConfigError("config root must be a JSON object")
    if not isinstance(cfg.get("game_exe", ""), str):
        raise ConfigError("'game_exe' must be a string")
    profiles = cfg.get("profiles", [])
    if not isinstance(profiles, list):
        raise ConfigError("'profiles' must be a list")
    seen = set()
    for i, p in enumerate(profiles):
        if not isinstance(p, dict):
            raise ConfigError("profile #%d is not an object" % i)
        pid = p.get("id")
        if not isinstance(pid, str) or not pid.strip():
            raise ConfigError("profile #%d has an empty or non-string id" % i)
        pid = pid.strip()
        if pid in seen:
            raise ConfigError("duplicate profile id: %r" % pid)
        seen.add(pid)
        hw = p.get("hw", {})
        if not isinstance(hw, dict):
            raise ConfigError("profile %r: 'hw' must be an object" % pid)
        for f in _HW_INT_FIELDS:
            if f in hw and not isinstance(hw[f], int):
                raise ConfigError("profile %r: hw.%s must be an integer" % (pid, f))


def default_cfg():
    return {
        "version": SCHEMA_VERSION,
        "game_exe": DEFAULT_GAME if os.path.isfile(DEFAULT_GAME) else "",
        "profiles": [
            {
                "id": "1", "label": "Instance 1", "user": "", "password": "",
                "proxy": "", "inject_children": True, "enabled": True,
                "game_exe": "", "hw": hwgen_generate("1"),
            },
            {
                "id": "2", "label": "Instance 2", "user": "", "password": "",
                "proxy": "", "inject_children": True, "enabled": True,
                "game_exe": "", "hw": hwgen_generate("2"),
            },
        ],
    }


def _fsync_dir(dirpath):
    """Best-effort durability of the directory entry after a rename. No-op on Windows."""
    if os.name == "nt":
        return
    try:
        fd = os.open(dirpath, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def load_cfg(path=PROFILES_PATH):
    """Read, migrate, normalize and validate profiles.json. Creates a default on first run."""
    if not os.path.isfile(path):
        cfg = default_cfg()
        save_cfg(cfg, path)
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        raise ConfigError("cannot read %s: %s" % (path, e))
    try:
        cfg = json.loads(raw)
    except ValueError as e:
        raise ConfigError("%s is not valid JSON: %s" % (os.path.basename(path), e))
    cfg = migrate(cfg)
    cfg = normalize(cfg)
    validate(cfg)
    return cfg


def save_cfg(cfg, path=PROFILES_PATH):
    """Normalize, validate, then write *cfg* atomically and durably. Returns the normalized cfg."""
    cfg = normalize(cfg)
    validate(cfg)
    text = json.dumps(cfg, indent=2, ensure_ascii=False)
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".profiles-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(d)
    return cfg


def next_id(cfg):
    used = {str(p.get("id")) for p in cfg.get("profiles", [])}
    i = 1
    while str(i) in used:
        i += 1
    return str(i)


# =========================================================================== hwgen
# Inlined from hwgen.py: realistic, self-consistent HWID sets so an HWID check sees a plausible
# machine instead of obviously-synthetic defaults.
_MOTHERBOARDS = [
    ("ASUSTeK COMPUTER INC.", "PRIME B450M-A"),
    ("ASUSTeK COMPUTER INC.", "TUF GAMING B550-PLUS"),
    ("ASUSTeK COMPUTER INC.", "ROG STRIX B450-F GAMING"),
    ("ASUSTeK COMPUTER INC.", "PRIME H610M-K D4"),
    ("Micro-Star International Co., Ltd.", "B450 TOMAHAWK MAX"),
    ("Micro-Star International Co., Ltd.", "MAG B560M BAZOOKA"),
    ("Micro-Star International Co., Ltd.", "PRO B660M-A DDR4"),
    ("Gigabyte Technology Co., Ltd.", "B450M DS3H"),
    ("Gigabyte Technology Co., Ltd.", "B560M AORUS ELITE"),
    ("Gigabyte Technology Co., Ltd.", "H610M H DDR4"),
    ("ASRock", "B450M Pro4"),
    ("ASRock", "B550M Phantom Gaming 4"),
]
_BIOS_VENDORS = ["American Megatrends Inc.", "American Megatrends Inc.", "American Megatrends Inc.",
                 "American Megatrends International, LLC.", "Phoenix Technologies LTD"]
_BIOS_VER = ["5.12", "5.13", "5.17", "F1", "F2", "F15", "P1.20", "1.E0", "2.10"]
_SYS_VENDORS = ["ASUSTeK COMPUTER INC.", "Micro-Star International Co., Ltd.", "Gigabyte Technology Co., Ltd.",
                "ASRock", "To Be Filled By O.E.M.", "System manufacturer"]
_CPU_NAMES = [
    "AMD Ryzen 5 3600 6-Core Processor",
    "AMD Ryzen 5 5600X 6-Core Processor",
    "AMD Ryzen 7 3700X 8-Core Processor",
    "AMD Ryzen 7 5800X 8-Core Processor",
    "AMD Ryzen 5 1600 Six-Core Processor",
    "Intel(R) Core(TM) i5-9400F CPU @ 2.90GHz",
    "Intel(R) Core(TM) i5-10400F CPU @ 2.90GHz",
    "Intel(R) Core(TM) i5-12400F CPU @ 2.50GHz",
    "Intel(R) Core(TM) i7-9700F CPU @ 3.00GHz",
    "Intel(R) Core(TM) i7-10700F CPU @ 2.90GHz",
    "Intel(R) Core(TM) i3-10100F CPU @ 3.60GHz",
    "AMD Ryzen 3 3200G with Radeon Vega Graphics",
]
_BUILDS = [19041, 19043, 19044, 19045, 22621, 22631]
_MAC_PREFIX = ["00:1A:2B", "00:1B:21", "00:24:1D", "00:25:90", "08:00:27", "1C:1B:0D", "2C:F0:5D",
               "3C:7C:3F", "40:8D:5C", "54:BF:64", "6C:F0:49", "88:D7:F6", "A8:A1:59", "BC:5F:F4"]


def _hex(rng, n):
    return "".join(rng.choice("0123456789ABCDEF") for _ in range(n))


def _rng_for(seed):
    import hashlib
    if isinstance(seed, str):
        seed = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    import random
    return random.Random(seed & 0xFFFFFFFF)


def hwgen_generate(seed):
    """Deterministic, realistic HWID set from *seed* (any str/int). Returns a plain dict."""
    rng = _rng_for(seed)
    vol = "%08X" % rng.randint(0x10000000, 0xFFFFFFFF)
    guid = "%08X-%04X-%04X-%04X-%04X%08X" % (
        rng.randint(0, 0xFFFFFFFF), rng.randint(0, 0xFFFF), rng.randint(0, 0xFFFF),
        rng.randint(0, 0xFFFF), rng.randint(0, 0xFFFF), rng.randint(0, 0xFFFFFFFF))
    mac = rng.choice(_MAC_PREFIX) + ":" + ":".join("%02X" % rng.randint(0, 255) for _ in range(3))
    board_mfr, board_prod = rng.choice(_MOTHERBOARDS)
    sys_mfr = rng.choice(_SYS_VENDORS)
    name = "DESKTOP-" + _hex(rng, 7)
    return {
        "serial": vol,
        "cname": name,
        "macaddr": mac,
        "guid": guid,
        "biosvendor": rng.choice(_BIOS_VENDORS),
        "biosver": rng.choice(_BIOS_VER),
        "boardmfr": board_mfr,
        "boardprod": board_prod,
        "sysmfr": sys_mfr,
        "sysprod": board_prod,
        "sysver": "System Version %s" % _hex(rng, 4),
        "monid": "MONITOR\\%s%04X" % (rng.choice(["PRM", "SAM", "ACR", "DEL", "AUS", "GSM"]), rng.randint(0, 0xFFFF)),
        "diskserial": _hex(rng, 8),
        "cpu": rng.choice(_CPU_NAMES),
        "build": rng.choice(_BUILDS),
        "biosserial": _hex(rng, 10),
        "boardserial": _hex(rng, 12),
        "uuid": "%08X-%04X-%04X-%04X-%04X%08X" % (
            rng.randint(0, 0xFFFFFFFF), rng.randint(0, 0xFFFF), rng.randint(0, 0xFFFF),
            rng.randint(0, 0xFFFF), rng.randint(0, 0xFFFF), rng.randint(0, 0xFFFFFFFF)),
        "rammb": rng.choice([8192, 12288, 16384, 16384, 24576, 32768]),
    }


# =========================================================================== model layer
# Inlined from profiles_model.py: pure data + validation, no tkinter/launcher. from_dict/to_dict
# round-trip losslessly (unknown hw/top-level keys preserved). apply_values validates before it
# mutates, so a bad numeric value aborts with nothing changed and nothing written.
HW_FIELDS = [
    ("serial", "Volume serial (C:)"),
    ("cname", "Computer name"),
    ("macaddr", "MAC address"),
    ("guid", "MachineGuid"),
    ("uuid", "System UUID (SMBIOS)"),
    ("biosvendor", "BIOS vendor"),
    ("biosver", "BIOS version"),
    ("biosserial", "BIOS serial"),
    ("boardmfr", "Board manufacturer"),
    ("boardprod", "Board product"),
    ("boardserial", "Board serial"),
    ("sysprod", "System product"),
    ("monid", "Monitor HardwareID"),
    ("cpu", "CPU name"),
    ("diskserial", "Disk serial"),
    ("rammb", "RAM (MB)"),
    ("build", "Windows build"),
]
_HW_KEYS = [k for k, _ in HW_FIELDS]


class ValidationError(ValueError):
    """Raised by apply_values() when a numeric editor field holds something that isn't a number."""

    def __init__(self, field_key, message):
        super().__init__(message)
        self.field = field_key
        self.message = message


def validate_hw_int(key, text):
    """Parse an editor string for an integer hw field. '' -> 0; digits -> int; else ValidationError."""
    s = (text or "").strip()
    if s == "":
        return 0
    if not s.isdigit():
        raise ValidationError(key, "'%s' must be a whole number (got %r)" % (key, text))
    return int(s)


@dataclass
class ProfileModel:
    id: str
    label: str = ""
    user: str = ""
    password: str = ""
    proxy: str = ""
    game_exe: str = ""
    inject_children: bool = False
    enabled: bool = True
    hw: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)   # unknown top-level keys, preserved verbatim

    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        pid = _as_str(d.pop("id", "")).strip()
        label = _as_str(d.pop("label", ""))
        user = _as_str(d.pop("user", ""))
        password = _as_str(d.pop("password", ""))
        proxy = _as_str(d.pop("proxy", ""))
        game_exe = _as_str(d.pop("game_exe", ""))
        inject_children = _as_bool(d.pop("inject_children", False), False)
        enabled = _as_bool(d.pop("enabled", True), True)
        hw = dict(d.pop("hw", {}) or {})
        for f in _HW_INT_FIELDS:
            if f in hw:
                hw[f] = _as_int(hw.get(f))
        return cls(pid, label, user, password, proxy, game_exe,
                   inject_children, enabled, hw, d)

    def to_dict(self):
        out = dict(self.extra)
        out.update({
            "id": self.id,
            "label": self.label,
            "user": self.user,
            "password": self.password,
            "proxy": self.proxy,
            "inject_children": bool(self.inject_children),
            "enabled": bool(self.enabled),
            "game_exe": self.game_exe,
            "hw": dict(self.hw),
        })
        return out


def apply_values(profile, values):
    """Validate raw editor *values* and write them into *profile* (a ProfileModel).

    Numeric fields are validated first; on failure a ValidationError is raised and *profile* is
    left unchanged. Only editor-known hw keys are overwritten, so unknown hw keys are preserved."""
    hw_ints = {}
    for key in _HW_INT_FIELDS:
        hw_ints[key] = validate_hw_int(key, values.get(key, ""))

    profile.label = _as_str(values.get("label", ""))
    profile.user = _as_str(values.get("user", ""))
    profile.password = _as_str(values.get("password", ""))
    profile.game_exe = _as_str(values.get("game_exe", "")).strip()
    profile.proxy = _as_str(values.get("proxy", "")).strip()
    profile.inject_children = bool(values.get("inject_children", False))

    for key in _HW_KEYS:
        if key in _HW_INT_FIELDS:
            profile.hw[key] = hw_ints[key]
        else:
            profile.hw[key] = _as_str(values.get(key, "")).strip()


@dataclass
class AppModel:
    game_exe: str = ""
    profiles: list = field(default_factory=list)          # list[ProfileModel]
    version: int = SCHEMA_VERSION
    path: str = PROFILES_PATH

    @classmethod
    def load(cls, path=PROFILES_PATH):
        cfg = load_cfg(path)
        profs = [ProfileModel.from_dict(p) for p in cfg.get("profiles", [])]
        return cls(game_exe=cfg.get("game_exe", ""),
                   profiles=profs,
                   version=cfg.get("version", SCHEMA_VERSION),
                   path=path)

    def to_cfg(self):
        return {
            "version": self.version,
            "game_exe": self.game_exe,
            "profiles": [p.to_dict() for p in self.profiles],
        }

    def save(self):
        save_cfg(self.to_cfg(), self.path)

    def find(self, pid):
        for p in self.profiles:
            if p.id == pid:
                return p
        return None

    def ids(self):
        return [p.id for p in self.profiles]

    def next_id(self):
        return next_id(self.to_cfg())

    def add(self):
        pid = self.next_id()
        p = ProfileModel.from_dict({
            "id": pid, "label": "Instance %s" % pid,
            "user": "", "password": "", "proxy": "",
            "inject_children": False, "enabled": True,
            "game_exe": "", "hw": hwgen_generate(pid),
        })
        self.profiles.append(p)
        return p

    def remove(self, pid):
        self.profiles = [p for p in self.profiles if p.id != pid]

    def commit(self, pid, values):
        """Validate+apply editor *values* to profile *pid*, then persist the whole store.

        Raises ValidationError (nothing saved) on a bad numeric field. Single choke point called
        on every profile switch / Apply / Add / Remove / Start, so a switch can't lose an edit."""
        p = self.find(pid)
        if p is None:
            return
        apply_values(p, values)   # may raise -> model untouched, save skipped
        self.save()


# =========================================================================== DLL build (once)
def ensure_dll():
    """Compile spoof.c -> rfspoof.dll and rfspoof.net.dll if either is missing."""
    dll = os.path.join(HERE, "rfspoof.dll")
    net = os.path.join(HERE, "rfspoof.net.dll")
    src = os.path.join(HERE, "spoof.c")
    if not os.path.isfile(src):
        raise RuntimeError("spoof.c missing next to app.py")
    missing = [(dll, []), (net, ["-DNETONLY"])]
    missing = [(t, extra) for t, extra in missing if not os.path.isfile(t)]
    if not missing:
        return dll
    for target, extra in missing:
        built = False
        for cc in (r"tools\mingw32\bin\gcc.exe", "gcc"):
            try:
                cmd = [cc, "-shared", "-s", "-O2", "-Wno-cpp", "-Wno-unknown-pragmas",
                       "-Wno-cast-function-type"] + extra + ["-o", target, src,
                       "-lkernel32", "-luser32", "-lws2_32"]
                subprocess.run(cmd, check=True, cwd=HERE, creationflags=0x08000000)
                log("built %s" % os.path.basename(target))
                built = True
                break
            except Exception as e:
                log("gcc (%s) failed: %s" % (cc, e))
        if not built:
            raise RuntimeError("%s missing and gcc not found - run build.ps1" % os.path.basename(target))
    return dll


# =========================================================================== manual mapper
class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


def _enable_debug_privilege():
    try:
        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

        class LAA(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

        class TP(ctypes.Structure):
            _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LAA * 1)]

        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID)]
        advapi.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TP),
                                                 wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        tok = wintypes.HANDLE()
        if not advapi.OpenProcessToken(kernel32.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(tok)):
            return False
        luid = LUID()
        advapi.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid))
        tp = TP(); tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = 0x2
        advapi.AdjustTokenPrivileges(tok, False, ctypes.byref(tp), 0, None, None)
        kernel32.CloseHandle(tok)
        return True
    except Exception:
        return False


def find_pids_by_name(name_lower):
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if snap == ctypes.c_void_p(-1).value:
        return []
    pe = PROCESSENTRY32(); pe.dwSize = ctypes.sizeof(pe)
    out = []
    ok = kernel32.Process32First(snap, ctypes.byref(pe))
    while ok:
        if pe.szExeFile.decode("latin1").lower() == name_lower:
            out.append(pe.th32ProcessID)
        ok = kernel32.Process32Next(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    return out


def _parent_pid(pid):
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
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


def _rpm(h, addr, size):
    buf = (ctypes.c_char * size)()
    got = ctypes.c_size_t(0)
    if not kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
        return None
    return buf.raw[:got.value]


def _wpm(h, addr, data):
    buf = ctypes.create_string_buffer(bytes(data), len(data))
    got = ctypes.c_size_t(0)
    if not kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr), buf, len(data), ctypes.byref(got)):
        return False
    return got.value == len(data)


def _peb32(h):
    buf = ctypes.c_void_p(0)
    ret = wintypes.DWORD(0)
    if ntdll.NtQueryInformationProcess(wintypes.HANDLE(h), 26, ctypes.byref(buf),
                                       ctypes.sizeof(ctypes.c_void_p), ctypes.byref(ret)) != 0:
        return 0
    return buf.value & 0xFFFFFFFF


def _peb_modules(h):
    peb = _peb32(h)
    if not peb:
        return
    ldr = _u32(_rpm(h, peb + 0x0C, 4) or b"\0\0\0\0", 0)
    if not ldr:
        return
    head = ldr + 0x0C
    cur = _u32(_rpm(h, head, 4) or b"\0\0\0\0", 0)
    for _ in range(1024):
        if not cur or cur == head:
            break
        base = _u32(_rpm(h, cur + 0x18, 4) or b"\0\0\0\0", 0)
        nlen = _u32(_rpm(h, cur + 0x2C, 4) or b"\0\0\0\0", 0) & 0xFFFF
        nptr = _u32(_rpm(h, cur + 0x30, 4) or b"\0\0\0\0", 0)
        nb = _rpm(h, nptr, min(nlen, 256)) or b""
        name = nb.decode("utf-16le", "replace").lower()
        if base:
            yield base, name
        cur = _u32(_rpm(h, cur, 4) or b"\0\0\0\0", 0)


def _resolve_export(h, module_name, func):
    base = 0
    for b, n in _peb_modules(h):
        if n == module_name.lower():
            base = b
            break
    if not base:
        return 0
    dos = _rpm(h, base, 0x40)
    if not dos or dos[:2] != b"MZ":
        return 0
    pe_off = base + _u32(dos, 0x3C)
    hdr = _rpm(h, pe_off, 0x100)
    opt = 0x18
    dd = opt + 0x60
    exp_rva = _u32(hdr, dd)
    if not exp_rva:
        return 0
    exp = _rpm(h, base + exp_rva, 0x28)
    nnames = _u32(exp, 0x18)
    names_rva = _u32(exp, 0x20)
    ords_rva = _u32(exp, 0x24)
    funcs_rva = _u32(exp, 0x1C)
    names = _rpm(h, base + names_rva, nnames * 4)
    for i in range(nnames):
        nr = _u32(names, i * 4)
        nb = _rpm(h, base + nr, 64)
        if not nb:
            continue
        nm = nb.split(b"\0")[0].decode("latin1")
        if nm == func:
            ords = _rpm(h, base + ords_rva, nnames * 2)
            idx = _u16(ords, i * 2)
            funcs = _rpm(h, base + funcs_rva, (idx + 1) * 4)
            return base + _u32(funcs, idx * 4)
    return 0


def _newest_dll(default):
    d = os.path.dirname(default)
    b = os.path.splitext(os.path.basename(default))[0]
    best = None
    for c in (default, os.path.join(d, b + ".new.dll"), os.path.join(d, b + ".next.dll")):
        try:
            if os.path.isfile(c) and (best is None or os.path.getmtime(c) > os.path.getmtime(best)):
                best = c
        except OSError:
            pass
    return best or default


def inject_dll(pid, dll, h=None, cfg=None):
    """Manual-map a spoof DLL (no LoadLibrary, no PEB entry). Fail-closed: raises on failure."""
    _enable_debug_privilege()
    if not dll:
        raise OSError("no DLL for pid %d" % pid)
    is_spoof = "rfspoof" in os.path.basename(str(dll)).lower()
    if is_spoof:
        # app.py may have cached _dll before a rebuild; a stale manual-map DLL misses the
        # current diagnostic/test flags (and can be the wrong build). Always use the newest.
        newest = rfprofiles.spoof_dll()
        if newest and os.path.isfile(newest):
            dll = newest
    if is_spoof:
        legacy = manualmap.spoof_modules(pid)
        if legacy and not manualmap.spoof_mutex_exists(pid):
            log("  pid %d has a legacy LoadLibrary spoofer (%s), skip"
                % (pid, ",".join(legacy)))
            return True
    base, reused = manualmap.map_module(pid, dll, cfg=cfg, log=log,
                                        wait_ready=is_spoof, ready_timeout=20.0)
    log("  manual-map pid=%d base=0x%08X reused=%s cfg=%s"
        % (pid, base or 0, reused, os.path.basename(cfg) if cfg else "-"))
    return True


# =========================================================================== process control
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_SUSPENDED = 0x00000004
LOGON_WITH_PROFILE = 0x00000001


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
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]


def _build_env(extra):
    env = dict(os.environ)
    env.update(extra)
    items = sorted("%s=%s" % (k, v) for k, v in env.items() if k and "=" not in k)
    return ctypes.create_unicode_buffer("\0".join(items) + "\0\0")


def _cfg_text(profile):
    """One full cfg (HWID + net). The proxy is the per-profile local relay when it is up."""
    return rfprofiles.cfg_text(profile, profile.get("_relay_port"))


def prepare(profile):
    """Prepare the per-profile files the DLL reads: one full cfg (HWID + net) and the HWID marker dir."""
    pid = profile["id"]
    dll = rfprofiles.spoof_dll()
    if not os.path.isfile(dll):
        raise FileNotFoundError("rfspoof.dll missing - run build.ps1")
    for d in (LOGDIR, CEFDIR, METADIR):
        os.makedirs(d, exist_ok=True)
    mdir = os.path.join(METADIR, "profile_%s" % pid)
    os.makedirs(mdir, exist_ok=True)
    profile["_dll"] = dll
    profile["_cfg"] = os.path.join(HERE, "spoof_%s.cfg" % pid)
    profile["_log"] = os.path.join(LOGDIR, "spoof_%s.log" % pid)
    profile["_metadir"] = mdir
    profile["_meta"] = os.path.join(mdir, "vcredist_x86.exe")
    try:
        open(profile["_log"], "w").close()
    except Exception:
        pass
    # one cfg for the whole profile: HWID + net (local relay), written to the profile dir and
    # the historical spoof_<id>.cfg path (the launcher env / guard both point at it).
    rfprofiles.write_profile_cfg(profile, profile.get("_relay_port") or 0)
    rfprofiles.write_game_cfg(profile, profile.get("_relay_port") or 0)
    rfprofiles.write_profile_json(profile)
    profile["_netdll"] = None
    profile["_netcfg"] = ""
    return dll


def start_profile(profile, game_exe, suspended=False):
    relay = start_relay(profile)
    profile["_relay_port"] = relay.port if relay else 0
    prepare(profile)
    exe = os.path.abspath(profile.get("game_exe") or game_exe)
    udd = os.path.join(CEFDIR, "profile_%s" % profile["id"])
    os.makedirs(udd, exist_ok=True)
    relay_arg = (' --proxy-server="socks5://127.0.0.1:%d" --disable-quic' % relay.port) if relay else ""
    cmdline = ctypes.create_unicode_buffer('"%s" --user-data-dir="%s"%s %s' % (exe, udd, relay_arg, profile.get("_extra_args") or ""))
    si = STARTUPINFOW(); si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    flags = (CREATE_SUSPENDED if suspended else 0) | CREATE_UNICODE_ENVIRONMENT
    env = _build_env({"SPOOF_CFG": profile["_cfg"], "SPOOF_NET_CFG": profile.get("_netcfg", "")})
    user = profile.get("user") or ""
    if user:
        advapi.CreateProcessWithLogonW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                   wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                                   ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
                                                   ctypes.POINTER(PROCESS_INFORMATION)]
        ok = advapi.CreateProcessWithLogonW(user, ".", profile.get("password") or "", LOGON_WITH_PROFILE,
                                            exe, cmdline, flags, ctypes.cast(env, ctypes.c_void_p),
                                            os.path.dirname(exe), ctypes.byref(si), ctypes.byref(pi))
    else:
        ok = kernel32.CreateProcessW(exe, cmdline, None, None, False, flags,
                                     ctypes.cast(env, ctypes.c_void_p), os.path.dirname(exe),
                                     ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        stop_relay(profile["id"])
        raise OSError("CreateProcess failed err=%d" % ctypes.get_last_error())
    h = pi.hProcess
    if user:
        full = kernel32.OpenProcess(0x1F0FFF, False, pi.dwProcessId)
        if full:
            h = full
    # First run: the launcher creates its own PC-ID marker; capture/copy it to .golden and set it
    # read-only. Later runs restore that golden copy before the launcher starts (ensure_marker).
    try:
        threading.Thread(target=rfprofiles.capture_marker_when_ready,
                         args=(profile,), daemon=True).start()
    except Exception:
        pass
    # The mapping itself happens after the CEF window is up + settled (_w_start), so the CEF init
    # never races a manual map. The network service uses --proxy-server from the first byte.
    return pi.dwProcessId, h, pi.hThread


def resume(hthread):
    if hthread:
        kernel32.ResumeThread(hthread)
        kernel32.CloseHandle(hthread)


def alive(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    code = wintypes.DWORD(0)
    kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    kernel32.CloseHandle(h)
    return code.value == 259


def kill_pid(pid):
    h = kernel32.OpenProcess(0x0001 | 0x1000, False, pid)
    if not h:
        return
    kernel32.TerminateProcess(h, 0)
    kernel32.CloseHandle(h)


# =========================================================================== local SOCKS5 relay
# Chromium/CEF (the network service child) connects within ~100 ms of start, before app.py has a
# chance to inject.  Giving the launcher --proxy-server=socks5://127.0.0.1:<port> makes every CEF
# connection use this relay from the first byte, and the relay forwards to the authenticated
# upstream proxy.  Hostnames stay hostnames end-to-end, so there is no local DNS leak either.
RELAYS = {}


def _split_proxy(proxy):
    user = pw = ""
    hostport = proxy.strip()
    if "@" in hostport:
        creds, hostport = hostport.rsplit("@", 1)
        if ":" in creds:
            user, pw = creds.split(":", 1)
        else:
            user = creds
    host, sep, port = hostport.rpartition(":")
    if not sep:
        raise ValueError("proxy must be host:port")
    return user, pw, host, int(port)


class SocksRelay:
    def __init__(self, proxy, tag=""):
        self.user, self.pw, self.host, self.upstream_port = _split_proxy(proxy)
        self.tag = tag
        self._stop = False
        self._ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._ls.bind(("127.0.0.1", 0))
        self._ls.listen(128)
        self.port = self._ls.getsockname()[1]
        self._t = threading.Thread(target=self._accept, name="socks-relay-%s" % tag, daemon=True)
        self._t.start()
        log("relay[%s]: 127.0.0.1:%d -> %s:%d" % (tag, self.port, self.host, self.upstream_port))

    def _log(self, msg):
        log("relay[%s]: %s" % (self.tag, msg))

    def close(self):
        self._stop = True
        try:
            self._ls.close()
        except Exception:
            pass

    def _accept(self):
        while not self._stop:
            try:
                c, _ = self._ls.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(c,), daemon=True).start()

    @staticmethod
    def _rx(c, n):
        b = b""
        while len(b) < n:
            d = c.recv(n - len(b))
            if not d:
                raise OSError("eof")
            b += d
        return b

    def _upstream(self):
        u = socket.create_connection((self.host, self.upstream_port), timeout=10)
        u.settimeout(30)
        u.sendall(b"\x05\x02\x00\x02" if self.user else b"\x05\x01\x00")
        r = self._rx(u, 2)
        if r[0] != 5:
            raise OSError("bad socks version")
        if r[1] == 2:
            if not self.user:
                raise OSError("proxy demands auth")
            ub = self.user.encode("latin1")[:255]
            pb = self.pw.encode("latin1")[:255]
            u.sendall(b"\x01" + bytes([len(ub)]) + ub + bytes([len(pb)]) + pb)
            a = self._rx(u, 2)
            if a[1] != 0:
                raise OSError("proxy auth failed")
        elif r[1] != 0:
            raise OSError("proxy method %d" % r[1])
        return u

    def _handle(self, c):
        try:
            c.settimeout(30)
            h = self._rx(c, 2)
            if h[0] != 5:
                return
            methods = self._rx(c, h[1])
            if 0 not in methods:
                c.sendall(b"\x05\xff")
                return
            c.sendall(b"\x05\x00")
            req = self._rx(c, 4)
            if req[1] != 1:
                c.sendall(b"\x05\x07\x00\x01" + b"\x00" * 6)
                return
            atyp = req[3]
            if atyp == 1:
                addr = self._rx(c, 4)
            elif atyp == 4:
                addr = self._rx(c, 16)
            elif atyp == 3:
                ln = self._rx(c, 1)
                addr = ln + self._rx(c, ln[0])
            else:
                c.sendall(b"\x05\x08\x00\x01" + b"\x00" * 6)
                return
            port = self._rx(c, 2)
            u = self._upstream()
            u.sendall(b"\x05\x01\x00" + bytes([atyp]) + addr + port)
            rep = self._rx(u, 4)
            if rep[3] == 1:
                bnd = self._rx(u, 4)
            elif rep[3] == 4:
                bnd = self._rx(u, 16)
            elif rep[3] == 3:
                ln = self._rx(u, 1)
                bnd = ln + self._rx(u, ln[0])
            else:
                bnd = b""
            bport = self._rx(u, 2)
            c.sendall(bytes([5, rep[1], 0, rep[3]]) + bnd + bport)
            if rep[1] != 0:
                self._log("upstream CONNECT rep=%d" % rep[1])
                u.close()
                return
            self._pump(c, u)
        except Exception as e:
            self._log("conn error: %s" % e)
        finally:
            try:
                c.close()
            except Exception:
                pass

    @staticmethod
    def _pump(a, b):
        socks = [a, b]
        while socks:
            try:
                r, _, x = select.select(socks, [], socks, 300)
            except Exception:
                break
            if x:
                break
            if not r:
                continue
            for s in list(r):
                try:
                    d = s.recv(65536)
                except Exception:
                    d = b""
                if not d:
                    try:
                        (b if s is a else a).shutdown(socket.SHUT_WR)
                    except Exception:
                        pass
                    socks.remove(s)
                    continue
                try:
                    (b if s is a else a).sendall(d)
                except Exception:
                    socks = []
                    break
        for s in (a, b):
            try:
                s.close()
            except Exception:
                pass


def start_relay(profile):
    pid = profile["id"]
    old = RELAYS.pop(pid, None)
    if old:
        old.close()
    if not profile.get("proxy"):
        return None
    try:
        r = SocksRelay(profile["proxy"], pid)
        RELAYS[pid] = r
        profile["_relay"] = r
        return r
    except Exception as e:
        log("relay %s failed: %s" % (pid, e))
        return None


def stop_relay(pid):
    r = RELAYS.pop(pid, None)
    if r:
        r.close()


# =========================================================================== GUI (thin view)
# Inlined from gui.py. Model/view split: all data + validation is in AppModel/ProfileModel above
# (no tkinter), so an edit can't be lost on a profile switch. Non-blocking: button handlers push
# onto cmd_q; one worker thread owns every process/injection call and reports via evt_q, drained
# on the Tk thread by an after() pump (tkinter is not thread-safe).
def run_gui():
    import queue
    import tkinter as tk
    from tkinter import messagebox, ttk

    global LOG_QUEUE
    LOG_QUEUE = queue.Queue()

    class App(tk.Tk):
        POLL_MS = 1500
        DRAIN_MS = 100

        def __init__(self):
            super().__init__()
            self.title("Cerberus Multi-Launcher (one-file)")
            self.geometry("920x660")

            try:
                self.model = AppModel.load()
            except ConfigError as e:
                messagebox.showerror(
                    "profiles.json error",
                    "%s\n\nStarting with an empty list. Your existing file was left untouched." % e)
                self.model = AppModel(game_exe=DEFAULT_GAME, profiles=[])

            self.current_id = None
            self.running = {}
            self.vars = {}
            self.entries = {}
            self._errored = set()

            self.cmd_q = queue.Queue()
            self.evt_q = queue.Queue()
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)

            self._build()
            self._refresh_list()
            if self.model.profiles:
                self._select_id(self.model.profiles[0].id)

            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self._worker.start()
            self.after(self.DRAIN_MS, self._drain_events)
            self.after(self.POLL_MS, self._tick_poll)

        # ---------------------------------------------------------------- layout
        def _build(self):
            style = ttk.Style(self)
            try:
                style.configure("Error.TEntry", fieldbackground="#ffd4d4")
            except Exception:
                pass

            top = ttk.Frame(self)
            top.pack(fill="x", padx=8, pady=6)
            ttk.Label(top, text="Game exe:").pack(side="left")
            self.game_var = tk.StringVar(value=self.model.game_exe)
            ttk.Entry(top, textvariable=self.game_var, width=70).pack(side="left", padx=6)
            ttk.Button(top, text="...", width=3, command=self._pick_game).pack(side="left")
            ttk.Button(top, text="Save", command=self._save_game).pack(side="left", padx=6)
            if not is_admin():
                ttk.Label(top, text="(not admin!)", foreground="red").pack(side="left", padx=6)

            body = ttk.Frame(self)
            body.pack(fill="both", expand=True, padx=8, pady=4)

            left = ttk.Frame(body)
            left.pack(side="left", fill="y")
            ttk.Label(left, text="Profiles").pack(anchor="w")
            self.listbox = tk.Listbox(left, width=26, height=22, exportselection=False)
            self.listbox.pack(fill="y", expand=True)
            self.listbox.bind("<<ListboxSelect>>", self._on_select)
            bf = ttk.Frame(left)
            bf.pack(fill="x", pady=4)
            ttk.Button(bf, text="+ Add", command=self._add).pack(side="left")
            ttk.Button(bf, text="Remove", command=self._remove).pack(side="left", padx=4)
            ttk.Button(bf, text="Gen HW", command=self._gen_hw).pack(side="left")

            right = ttk.Frame(body)
            right.pack(side="left", fill="both", expand=True, padx=10)

            gen = ttk.LabelFrame(right, text="General")
            gen.pack(fill="x", pady=4)
            self._row(gen, 0, "Label", "label", None)
            self._row(gen, 1, "Game exe (this profile)", "game_exe", "ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¿ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¾ = ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â±ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â°ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¹ ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã†â€™Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â²ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂµÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢")
            self._row(gen, 2, "Windows user (opt.)", "user", None)
            self._row(gen, 3, "Password (opt.)", "password", None)
            self._row(gen, 4, "SOCKS5 proxy", "proxy", "user:pass@host:port")
            self._row(gen, 5, "Inject children", "inject_children", None, check=True)

            hw = ttk.LabelFrame(right, text="Fake hardware  (Gen HW fills realistic values)")
            hw.pack(fill="both", expand=True, pady=4)
            for i, (key, label) in enumerate(HW_FIELDS):
                self._row(hw, i, label, key, None)

            act = ttk.Frame(right)
            act.pack(fill="x", pady=6)
            ttk.Button(act, text="Start selected", command=lambda: self._start([self.current_id])).pack(side="left")
            ttk.Button(act, text="Stop selected", command=lambda: self._stop([self.current_id])).pack(side="left", padx=4)
            ttk.Button(act, text="START ALL", command=self._start_all).pack(side="left", padx=16)
            ttk.Button(act, text="STOP ALL", command=self._stop_all).pack(side="left")
            self.apply_btn = ttk.Button(act, text="Apply changes", command=self._apply_clicked)
            self.apply_btn.pack(side="right")

            bot = ttk.LabelFrame(self, text="Log")
            bot.pack(fill="both", expand=False, padx=8, pady=4)
            self.log = tk.Text(bot, height=8, state="disabled")
            self.log.pack(fill="both", expand=True)

        def _row(self, parent, r, label, key, hint, check=False):
            ttk.Label(parent, text=label, width=20, anchor="w").grid(row=r, column=0, sticky="w", padx=4, pady=1)
            if check:
                v = tk.BooleanVar()
                self.vars[key] = v
                ttk.Checkbutton(parent, variable=v).grid(row=r, column=1, sticky="w")
            else:
                v = tk.StringVar()
                self.vars[key] = v
                e = ttk.Entry(parent, textvariable=v, width=58)
                e.grid(row=r, column=1, sticky="w", padx=4, pady=1)
                self.entries[key] = e
                v.trace_add("write", lambda *_a, k=key: self._unmark_error(k))
                if hint:
                    ttk.Label(parent, text=hint, foreground="gray").grid(row=r, column=2, sticky="w")

        # ---------------------------------------------------------------- editor <-> model
        def _values_from_widgets(self):
            v = {}
            for k in ("label", "game_exe", "user", "password", "proxy"):
                v[k] = self.vars[k].get()
            v["inject_children"] = bool(self.vars["inject_children"].get())
            for k, _ in HW_FIELDS:
                v[k] = self.vars[k].get()
            return v

        def _load_into_editor(self, pid):
            p = self.model.find(pid)
            if not p:
                return
            self.vars["label"].set(p.label)
            self.vars["game_exe"].set(p.game_exe)
            self.vars["user"].set(p.user)
            self.vars["password"].set(p.password)
            self.vars["proxy"].set(p.proxy)
            self.vars["inject_children"].set(bool(p.inject_children))
            for k, _ in HW_FIELDS:
                self.vars[k].set(str(p.hw.get(k, "")))
            self._clear_error()

        def _try_commit_current(self):
            if self.current_id is None:
                return True
            try:
                self.model.commit(self.current_id, self._values_from_widgets())
                self._clear_error()
                return True
            except ValidationError as e:
                self._mark_error(e.field)
                messagebox.showerror("Invalid value", e.message)
                return False
            except ConfigError as e:
                messagebox.showerror("Save failed", str(e))
                return False

        # ---------------------------------------------------------------- selection
        def _on_select(self, _e):
            sel = self.listbox.curselection()
            if not sel:
                return
            target = self.model.profiles[sel[0]].id
            if target == self.current_id:
                return
            if not self._try_commit_current():
                self._reselect_listbox(self.current_id)
                return
            self.current_id = target
            self._load_into_editor(target)
            self._refresh_list()

        def _select_id(self, pid):
            self.current_id = pid
            self._load_into_editor(pid)
            self._reselect_listbox(pid)

        def _reselect_listbox(self, pid):
            self.listbox.selection_clear(0, "end")
            for i, p in enumerate(self.model.profiles):
                if p.id == pid:
                    self.listbox.selection_set(i)
                    self.listbox.see(i)
                    break

        # ---------------------------------------------------------------- helpers
        def _log(self, msg):
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")

        def _mark_error(self, key):
            e = self.entries.get(key)
            if e is not None:
                e.configure(style="Error.TEntry")
                self._errored.add(key)

        def _unmark_error(self, key):
            if key in self._errored:
                e = self.entries.get(key)
                if e is not None:
                    e.configure(style="TEntry")
                self._errored.discard(key)

        def _clear_error(self):
            for key in list(self._errored):
                self._unmark_error(key)

        def _refresh_list(self):
            self.listbox.delete(0, "end")
            for p in self.model.profiles:
                a = " ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â" if p.id in self.running else ""
                self.listbox.insert("end", "%s  [%s]%s" % (p.label or p.id, p.id, a))
            if self.current_id is not None:
                self._reselect_listbox(self.current_id)

        def _pick_game(self):
            from tkinter import filedialog
            p = filedialog.askopenfilename(filetypes=[("exe", "*.exe"), ("all", "*.*")])
            if p:
                self.game_var.set(p)

        def _save_game(self):
            self.model.game_exe = self.game_var.get()
            try:
                self.model.save()
            except ConfigError as e:
                messagebox.showerror("Save failed", str(e))
                return
            self._log("game exe saved")

        # ---------------------------------------------------------------- profile edit buttons
        def _apply_clicked(self):
            if self._try_commit_current():
                self._log("saved profile %s" % self.current_id)
                self._refresh_list()

        def _add(self):
            if not self._try_commit_current():
                return
            p = self.model.add()
            try:
                self.model.save()
            except ConfigError as e:
                self.model.remove(p.id)
                messagebox.showerror("Add failed", str(e))
                return
            self._refresh_list()
            self._select_id(p.id)
            self._log("added profile %s" % p.id)

        def _remove(self):
            if self.current_id is None:
                return
            pid = self.current_id
            if pid in self.running:
                if not messagebox.askyesno("Remove", "Profile running. Stop and remove?"):
                    return
                self._stop([pid])
            self.model.remove(pid)
            try:
                self.model.save()
            except ConfigError as e:
                messagebox.showerror("Remove failed", str(e))
                return
            self._log("removed profile %s" % pid)
            self.current_id = None
            self._refresh_list()
            if self.model.profiles:
                self._select_id(self.model.profiles[0].id)

        def _gen_hw(self):
            if self.current_id is None:
                return
            hw = hwgen_generate(self.current_id + os.urandom(2).hex())
            for k, _ in HW_FIELDS:
                self.vars[k].set(str(hw.get(k, "")))
            if not self._try_commit_current():
                return
            try:
                mdir = os.path.join(METADIR, "profile_%s" % self.current_id)
                shutil.rmtree(mdir, ignore_errors=True)
            except Exception:
                pass
            self._log("generated new realistic hardware for profile %s" % self.current_id)

        # ---------------------------------------------------------------- start/stop (non-blocking)
        def _start(self, ids):
            if not self._try_commit_current():
                return
            ids = [i for i in ids if i]
            if not ids:
                return
            game = self.game_var.get()
            snaps = {}
            for pid in ids:
                p = self.model.find(pid)
                if p is not None:
                    snaps[pid] = p.to_dict()
            self.cmd_q.put(("start", ids, game, snaps))

        def _stop(self, ids):
            ids = [i for i in ids if i]
            if ids:
                self.cmd_q.put(("stop", ids))

        def _start_all(self):
            self._start(self.model.ids())

        def _stop_all(self):
            self.cmd_q.put(("stop_all",))

        def _tick_poll(self):
            self.cmd_q.put(("poll",))
            self.after(self.POLL_MS, self._tick_poll)

        def _drain_events(self):
            try:
                while True:
                    kind, payload = self.evt_q.get_nowait()
                    if kind == "log":
                        self._log(payload)
                    elif kind == "running":
                        self.running = payload
                        self._refresh_list()
            except queue.Empty:
                pass
            self.after(self.DRAIN_MS, self._drain_events)

        def _on_close(self):
            try:
                self.cmd_q.put(("quit",))
            except Exception:
                pass
            self.destroy()

        # ---------------------------------------------------------------- worker thread (owns procs)
        def _emit(self, kind, payload):
            self.evt_q.put((kind, payload))

        def _worker_loop(self):
            procs = {}
            while True:
                cmd = self.cmd_q.get()
                op = cmd[0]
                if op == "quit":
                    break
                try:
                    if op == "start":
                        self._w_start(procs, cmd[1], cmd[2], cmd[3])
                    elif op == "stop":
                        self._w_stop(procs, cmd[1])
                    elif op == "stop_all":
                        self._w_stop(procs, list(procs.keys()))
                    elif op == "poll":
                        self._w_poll(procs)
                except Exception as e:
                    self._emit("log", "worker error on %s: %s" % (op, e))

        def _emit_running(self, procs):
            run = {}
            for pid, (pr, _h) in procs.items():
                try:
                    if alive(pr):
                        run[pid] = pr
                except Exception:
                    pass
            self._emit("running", run)

        def _title_loop(self, labels):
            """Keep per-instance window titles readable: '<label> — Launcher/RF Online'."""
            user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
            user32.SetWindowTextW.restype = wintypes.BOOL
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def cb(hwnd, lp):
                try:
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    p = wintypes.DWORD(0)
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(hwnd, buf, 256)
                    if not buf.value:
                        return True
                    label = labels.get(p.value)
                    is_game = False
                    if label is None:
                        q = p.value
                        for _ in range(6):
                            q = _parent_pid(q)
                            if not q:
                                break
                            if q in labels:
                                label = labels[q]
                                is_game = True
                                break
                    if label is None:
                        return True
                    if not is_game and "rf online" in buf.value.lower():
                        is_game = True
                    want = ("%s \u2014 RF Online" % label) if is_game else ("%s \u2014 Launcher" % label)
                    if buf.value != want:
                        user32.SetWindowTextW(hwnd, want)
                except Exception:
                    pass
                return True

            end = time.time() + 3600
            while time.time() < end:
                try:
                    user32.EnumWindows(CB(cb), 0)
                except Exception:
                    pass
                time.sleep(1.0)

        def _wait_windows(self, pids, timeout=20.0):
            """Wait for the real launcher window (not the splash), then a short settle."""
            need = set(pids)
            first = {}
            end = time.time() + timeout
            while need and time.time() < end:
                got = self._visible_windows()
                for pid, titles in got.items():
                    if pid not in need:
                        continue
                    if any("launcher" in t.lower() for t in titles):
                        need.discard(pid)
                    else:
                        first.setdefault(pid, time.time())
                        if time.time() - first[pid] > 3.0:
                            need.discard(pid)
                if need and not any(alive(pr) for pr in need):
                    break
                if need:
                    time.sleep(0.2)

        def _visible_windows(self):
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

        def _w_start(self, procs, ids, game, snaps):
            ensure_guard()
            ids = [i for i in ids if i]
            hts = {}
            for pid in ids:
                p = snaps.get(pid)
                if p is None:
                    continue
                exe = p.get("game_exe") or game
                if not exe or not os.path.isfile(exe):
                    self._emit("log", "profile %s: no valid game exe" % pid)
                    continue
                if pid in procs and alive(procs[pid][0]):
                    self._emit("log", "profile %s already running" % pid)
                    continue
                try:
                    pr, h, ht = start_profile(p, game, suspended=True)
                    procs[pid] = (pr, h)
                    hts[pid] = ht
                    self._emit("log", "started %s (pid %d, suspended)" % (pid, pr))
                except Exception as e:
                    self._emit("log", "start %s failed: %s" % (pid, e))
            for pid in list(hts):
                try:
                    resume(hts[pid])
                except Exception:
                    pass
            # Injecting before the CEF window is up is racy (the process can crash mid-init), so
            # wait for each window + a short settle first - the same timing rule launcher.py uses.
            started_pids = [pr for pr, _h in procs.values()]
            self._wait_windows(started_pids, timeout=20.0)
            time.sleep(2.0)
            main_dlls = {}
            for pid in ids:
                if pid not in procs:
                    continue
                pr, hproc = procs[pid]
                p = snaps.get(pid, {})
                if "_dll" not in p:
                    try:
                        prepare(p)
                    except Exception:
                        pass
                try:
                    inject_dll(pr, p.get("_dll"), hproc, cfg=p.get("_cfg"))
                    main_dlls[pr] = (p.get("_dll"), bool(p.get("inject_children")),
                                     p.get("_cfg"), str(pid))
                    self._emit("log", "manual-mapped full spoof into main %s (pid %d)" % (pid, pr))
                except Exception as e:
                    # fail-closed: a launcher without the spoofer must not stay up
                    self._emit("log", "FAIL-CLOSED: map main %s failed: %s - killing pid %d"
                               % (pid, e, pr))
                    try:
                        kill_pid(pr)
                    except Exception:
                        pass
                    stop_relay(pid)
                    procs.pop(pid, None)
            self._emit_running(procs)
            labels = {}
            for pid in ids:
                if pid in procs:
                    pr, _h = procs[pid]
                    p = snaps.get(pid) or {}
                    labels[pr] = p.get("label") or ("Instance %s" % pid)
            threading.Thread(target=self._title_loop, args=(labels,), daemon=True).start()
            threading.Thread(target=self._w_watch_children,
                             args=(game, dict(main_dlls)), daemon=True).start()

        def _w_watch_children(self, game, main_dlls):
            names = [(os.path.basename(game).lower(), False),
                     ("rf_online.bin", True), ("rf_online_4gb.bin", True)]
            seen = set(main_dlls.keys())
            first_seen = {}
            last_guard = 0.0
            while True:
                now = time.time()
                if now - last_guard > 5.0:
                    last_guard = now
                    if not guard_running():
                        self._emit("log", "guard is not running - restarting it")
                        ensure_guard()
                for name, is_game in names:
                    try:
                        pids = find_pids_by_name(name)
                    except Exception:
                        pids = []
                    for q in pids:
                        if q in seen:
                            continue
                        if q not in first_seen:
                            first_seen[q] = now
                            continue
                        if now - first_seen[q] < (0.05 if is_game else 1.5):
                            continue
                        dll, want, cfg, profile_id = self._dll_for_child(q, main_dlls)
                        if is_game and profile_id is not None:
                            try:
                                _p = rfprofiles.profile_by_id(profile_id)
                                if _p:
                                    cfg = rfprofiles.game_cfg(_p)
                            except Exception:
                                pass
                        if not is_game and not want:
                            seen.add(q)
                            continue
                        if not dll or not os.path.isfile(dll):
                            seen.add(q)
                            continue
                        if is_game and os.path.isfile(os.path.join(HERE, "game_map.off")):
                            seen.add(q)
                            self._emit("log", "  game %d left without the spoofer (game_map.off)" % q)
                            continue
                        try:
                            inject_dll(q, dll, cfg=cfg)
                            seen.add(q)
                            if is_game:
                                self._emit("log", "  game %d full spoof manual-mapped" % q)
                                self._emit("log", "  bot for game %d is mapped by rfguard" % q)
                            else:
                                self._emit("log", "  child %d full spoof manual-mapped" % q)
                        except Exception as e:
                            # retry: restart the settle timer, never mark it as covered
                            first_seen[q] = now
                            self._emit("log", "  %s %d map failed: %s"
                                       % ("game" if is_game else "child", q, e))
                time.sleep(0.05)


        def _dll_for_child(self, child_pid, main_dlls):
            try:
                ppid = _parent_pid(child_pid)
                guard = 0
                while ppid and guard < 10:
                    if ppid in main_dlls:
                        return main_dlls[ppid]
                    ppid = _parent_pid(ppid)
                    guard += 1
            except Exception:
                pass
            try:
                return next(iter(main_dlls.values()))
            except StopIteration:
                return (None, False, None, None)

        def _w_stop(self, procs, ids):
            for pid in ids:
                if pid in procs:
                    pr, _h = procs[pid]
                    try:
                        if alive(pr):
                            kill_pid(pr)
                        self._emit("log", "stopped %s (pid %d)" % (pid, pr))
                    except Exception as e:
                        self._emit("log", "stop %s failed: %s" % (pid, e))
                    stop_relay(pid)
                    procs.pop(pid, None)
            self._emit_running(procs)

        def _w_poll(self, procs):
            changed = False
            for pid, (pr, _h) in list(procs.items()):
                if not alive(pr):
                    self._emit("log", "profile %s exited" % pid)
                    stop_relay(pid)
                    procs.pop(pid, None)
                    changed = True
            if changed:
                self._emit_running(procs)

    App().mainloop()


# =========================================================================== entry point
def guard_running():
    h = kernel32.OpenMutexW(0x00100000, False, rfprofiles.guard_mutex_name())
    if not h:
        return False
    kernel32.CloseHandle(h)
    return True


def ensure_guard():
    """Start the always-on elevated guard in this (already elevated) process context."""
    if find_pids_by_name("watchinj_multi.exe"):
        try:
            os.makedirs(os.path.join(HERE, "re_hackshield", "logs"), exist_ok=True)
            open(os.path.join(HERE, "re_hackshield", "logs", "watch_inject_multi.stop"), "w").close()
            log("legacy watchinj_multi asked to stop")
        except Exception:
            pass
    if guard_running():
        return True
    py = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(py):
        py = sys.executable
    args = [py, os.path.join(HERE, "rfguard.py"), "--detach"]
    if is_admin():
        args.insert(2, "--elevated")   # already elevated: no extra UAC
    try:
        subprocess.Popen(args, cwd=HERE,
                         creationflags=0x08000000 | 0x00000008 | 0x00000200,
                         close_fds=True)
        log("guard started (%s)" % os.path.basename(py))
        return True
    except Exception as e:
        log("guard start failed: %s" % e)
        return False


def main():
    if not is_admin():
        try:
            shell32.ShellExecuteW(None, "runas", sys.executable, '"%s"' % os.path.abspath(__file__), HERE, 1)
            return
        except Exception:
            pass
    ensure_dll()
    ensure_guard()
    run_gui()


if __name__ == "__main__":
    main()
