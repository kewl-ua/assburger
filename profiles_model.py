# -*- coding: utf-8 -*-
"""
profiles_model.py - headless model layer for the launcher GUI.

No tkinter, no launcher imported here: this is pure data + validation, so it can be unit-tested
without a display and reused by any front-end. gui.py's Tk view binds widgets to this model and
never touches the raw config dicts directly - that is what keeps edits from being lost on a
profile switch and keeps the numeric validation in one testable place.

Layers:
    ProfileModel - one profile as a dataclass. from_dict()/to_dict() round-trip losslessly:
                   unknown hw keys (e.g. sysmfr/sysver) and unknown top-level keys are preserved.
    AppModel     - the whole store (game_exe + list[ProfileModel]) plus load()/save()/commit().
    apply_values - validate a dict of raw editor strings and write them into a ProfileModel.
                   Validation happens BEFORE any mutation, so a bad value aborts cleanly with
                   nothing changed and nothing written.
"""
from dataclasses import dataclass, field

import config
import hwgen

# (key, label) pairs shown in the editor, in display order. Mirrors the on-disk hw schema.
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
HW_INT_FIELDS = ("build", "rammb")
_HW_KEYS = [k for k, _ in HW_FIELDS]

# Editable general (non-hw) string fields in the editor.
GENERAL_STR_FIELDS = ("label", "game_exe", "user", "password", "proxy")
# Fields trimmed on commit (matches the original GUI behavior).
_STRIP_FIELDS = ("game_exe", "proxy")


class ValidationError(ValueError):
    """Raised by apply_values() when a numeric editor field holds something that isn't a number.
    Carries .field (the offending key) so the view can highlight the right entry."""

    def __init__(self, field_key, message):
        super().__init__(message)
        self.field = field_key
        self.message = message


def validate_hw_int(key, text):
    """Parse an editor string for an integer hw field. '' -> 0 (allowed); digits -> int;
    anything else -> ValidationError. Only non-negative values are accepted (build/rammb)."""
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
        pid = config._as_str(d.pop("id", "")).strip()
        label = config._as_str(d.pop("label", ""))
        user = config._as_str(d.pop("user", ""))
        password = config._as_str(d.pop("password", ""))
        proxy = config._as_str(d.pop("proxy", ""))
        game_exe = config._as_str(d.pop("game_exe", ""))
        inject_children = config._as_bool(d.pop("inject_children", False), False)
        enabled = config._as_bool(d.pop("enabled", True), True)
        hw = dict(d.pop("hw", {}) or {})
        for f in HW_INT_FIELDS:
            if f in hw:
                hw[f] = config._as_int(hw.get(f))
        # whatever is left in d is unknown -> keep it so a round-trip loses nothing
        return cls(pid, label, user, password, proxy, game_exe,
                   inject_children, enabled, hw, d)

    def to_dict(self):
        out = dict(self.extra)                      # unknown keys first...
        out.update({                                # ...known keys always win
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

    values: dict of raw widget contents - strings for text/number fields, bool for checkboxes.
    Numeric fields are validated first; on failure a ValidationError is raised and *profile* is
    left completely unchanged. Only editor-known hw keys are overwritten, so hw keys the editor
    doesn't show (sysmfr, sysver, ...) are preserved.
    """
    # 1) validate everything that can fail, before touching the model
    hw_ints = {}
    for key in HW_INT_FIELDS:
        hw_ints[key] = validate_hw_int(key, values.get(key, ""))

    # 2) commit general fields
    profile.label = config._as_str(values.get("label", ""))
    profile.user = config._as_str(values.get("user", ""))
    profile.password = config._as_str(values.get("password", ""))
    profile.game_exe = config._as_str(values.get("game_exe", "")).strip()
    profile.proxy = config._as_str(values.get("proxy", "")).strip()
    profile.inject_children = bool(values.get("inject_children", False))

    # 3) commit hw: overwrite only the keys the editor knows; keep the rest
    for key in _HW_KEYS:
        if key in HW_INT_FIELDS:
            profile.hw[key] = hw_ints[key]
        else:
            profile.hw[key] = config._as_str(values.get(key, "")).strip()


@dataclass
class AppModel:
    game_exe: str = ""
    profiles: list = field(default_factory=list)          # list[ProfileModel]
    version: int = config.SCHEMA_VERSION
    path: str = config.PROFILES_PATH

    @classmethod
    def load(cls, path=config.PROFILES_PATH):
        """Load via config.load() (which migrates/validates). Propagates config.ConfigError."""
        cfg = config.load(path)
        profs = [ProfileModel.from_dict(p) for p in cfg.get("profiles", [])]
        return cls(game_exe=cfg.get("game_exe", ""),
                   profiles=profs,
                   version=cfg.get("version", config.SCHEMA_VERSION),
                   path=path)

    def to_cfg(self):
        return {
            "version": self.version,
            "game_exe": self.game_exe,
            "profiles": [p.to_dict() for p in self.profiles],
        }

    def save(self):
        """Atomic, validated write via config.save(). Raises config.ConfigError if invalid."""
        config.save(self.to_cfg(), self.path)

    def find(self, pid):
        for p in self.profiles:
            if p.id == pid:
                return p
        return None

    def ids(self):
        return [p.id for p in self.profiles]

    def next_id(self):
        return config.next_id(self.to_cfg())

    def add(self):
        pid = self.next_id()
        p = ProfileModel.from_dict({
            "id": pid, "label": "Instance %s" % pid,
            "user": "", "password": "", "proxy": "",
            "inject_children": False, "enabled": True,
            "game_exe": "", "hw": hwgen.generate(pid),
        })
        self.profiles.append(p)
        return p

    def remove(self, pid):
        self.profiles = [p for p in self.profiles if p.id != pid]

    def commit(self, pid, values):
        """Validate+apply editor *values* to profile *pid*, then persist the whole store.

        Raises ValidationError (nothing saved) if a numeric field is bad. This is the single
        choke point the view calls on every profile switch, Apply, Add, Remove and Start, which
        is why switching profiles can't lose an in-progress edit: the edit is committed first.
        """
        p = self.find(pid)
        if p is None:
            return
        apply_values(p, values)   # may raise -> model untouched, save skipped
        self.save()
