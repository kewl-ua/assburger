# -*- coding: utf-8 -*-
"""
config.py - profiles store for the multi-instance launcher.

profiles.json lives next to this file. Each profile describes one independent launcher window:
its own fake hardware, its own proxy, its own CEF user-data-dir.

Schema (version 1):
{
  "version": 1,
  "game_exe": "C:\\\\SHARE\\\\CERBERUS\\\\CERBERUS-GAMES.exe",
  "profiles": [
    {
      "id": "1",                         # unique, non-empty, used as SPOOF_ID / cfg name
      "label": "Instance 1",
      "user": "",                        # optional windows account; "" = same session
      "password": "",
      "proxy": "user:pass@host:port",    # SOCKS5; "" = direct
      "inject_children": false,
      "enabled": true,
      "game_exe": "",                    # per-profile override; "" = shared game_exe above
      "hw": { ...hwgen fields... }        # see hwgen.py; unknown keys are preserved as-is
    }
  ]
}

Public API:
    load(path=PROFILES_PATH)   -> cfg dict          (raises ConfigError on bad file)
    save(cfg, path=...)        -> normalized cfg     (atomic; raises ConfigError if invalid)
    validate(cfg)              -> None               (raises ConfigError on structural problems)
    normalize(cfg)            -> cfg                 (coerce types, fill defaults, keep unknowns)
    migrate(cfg)              -> cfg                 (bring any older schema up to SCHEMA_VERSION)
    default()                 -> cfg
    next_id(cfg)              -> str

Design notes:
  * Writes are atomic and durable: data -> temp file in the SAME directory -> flush+fsync ->
    os.replace() (atomic on NTFS when src/dst share a volume). A crash can never leave a
    half-written profiles.json; the old file survives intact until replace() succeeds.
  * A broken file raises ConfigError with a readable message instead of a raw JSONDecodeError
    /KeyError. The caller (GUI) decides what to do; the bad file is never overwritten implicitly.
  * Validation is strict about what matters (unique, non-empty ids; right container shapes) and
    forgiving about field types (coerced: build/rammb -> int, flags -> bool, text -> str). Unknown
    hw keys and unknown top-level profile keys are passed through untouched so nothing is lost.
"""
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES_PATH = os.path.join(HERE, "profiles.json")
DEFAULT_GAME = r"C:\SHARE\CERBERUS\CERBERUS-GAMES.exe"

SCHEMA_VERSION = 1

# Known general (non-hw) fields and their coercion.
_PROFILE_STR_FIELDS = ("label", "user", "password", "proxy", "game_exe")
_PROFILE_BOOL_FIELDS = (("inject_children", False), ("enabled", True))
# hw fields that must be integers; every other hw value is kept as loaded.
_HW_INT_FIELDS = ("build", "rammb")


class ConfigError(Exception):
    """Raised for any unusable config: unreadable file, invalid JSON, or schema violation."""
    pass


# --------------------------------------------------------------------------- coercion helpers
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


# --------------------------------------------------------------------------- migration
def _migrate_0_to_1(cfg):
    """Legacy files had no 'version' field. The layout is otherwise compatible, so this only
    stamps the version (done by migrate() after the chain). Future steps go here, one per jump."""
    return cfg


_MIGRATIONS = {
    0: _migrate_0_to_1,
}


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


# --------------------------------------------------------------------------- normalize
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
    # All other hw values (and any unknown top-level profile keys) are left untouched.
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


# --------------------------------------------------------------------------- validate
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


# --------------------------------------------------------------------------- default
def default():
    import hwgen
    return {
        "version": SCHEMA_VERSION,
        "game_exe": DEFAULT_GAME if os.path.isfile(DEFAULT_GAME) else "",
        "profiles": [
            {
                "id": "1", "label": "Instance 1", "user": "", "password": "",
                "proxy": "", "inject_children": True, "enabled": True,
                "game_exe": "", "hw": hwgen.generate("1"),
            },
            {
                "id": "2", "label": "Instance 2", "user": "", "password": "",
                "proxy": "", "inject_children": True, "enabled": True,
                "game_exe": "", "hw": hwgen.generate("2"),
            },
        ],
    }


# --------------------------------------------------------------------------- load / save
def load(path=PROFILES_PATH):
    """Read, migrate, normalize and validate profiles.json. Creates a default on first run.

    Raises ConfigError (with a readable message) on an unreadable file, invalid JSON, an
    unknown/newer schema version, or a structural violation such as a duplicate id. The on-disk
    file is never modified on error.
    """
    if not os.path.isfile(path):
        cfg = default()
        save(cfg, path)
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


def _fsync_dir(dirpath):
    """Best-effort durability of the directory entry after a rename. No-op on Windows, where
    a directory handle can't be fsync'd and os.replace() is already atomic on NTFS."""
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


def save(cfg, path=PROFILES_PATH):
    """Normalize, validate, then write *cfg* atomically and durably. Returns the normalized cfg.

    Refuses to write an invalid config (raises ConfigError) so profiles.json can never be left
    in a broken state by us. The temp file is created in the target directory (same volume) and
    is removed if anything fails before the rename.
    """
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
