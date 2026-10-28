# -*- coding: utf-8 -*-
"""
hwgen.py - generate a realistic, self-consistent set of "hardware" values for one instance.

The values mimic what real gamer PCs report, so an anti-cheat/HWID check sees a plausible
machine instead of the obviously-synthetic defaults (serial 0x1...., DESKTOP-XXXX, ...).

Produces a dict consumed by launcher.py, which writes it into <profile>.cfg for rfspoof.dll.

Field reference (all optional; whatever is present overrides the DLL's id-derived default):
    serial      volume serial of C: as 8 hex digits
    cname       NetBIOS/computer name
    macaddr     primary NIC MAC  (AA:BB:CC:DD:EE:FF)
    guid        MachineGuid
    biosvendor  BIOS vendor string
    biosver     BIOS version string
    boardmfr    baseboard manufacturer
    boardprod   baseboard product
    sysmfr      system manufacturer
    sysprod     system product name
    sysver      system version
    monid       a monitor HardwareID token  (MONITOR\\PRMxxxx)
    diskserial  disk drive serial
    cpu         CPU marketing name
    build       Windows build number (e.g. 19045)
"""
import hashlib
import random

# --- pools of values that occur on real machines --------------------------------------------
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
    if isinstance(seed, str):
        seed = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    return random.Random(seed & 0xFFFFFFFF)


def generate(seed):
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


def blank():
    return {k: "" for k in ("serial", "cname", "macaddr", "guid", "biosvendor", "biosver",
                            "boardmfr", "boardprod", "sysmfr", "sysprod", "sysver",
                            "monid", "diskserial", "cpu", "biosserial", "boardserial", "uuid")} | {"build": 0, "rammb": 0}


if __name__ == "__main__":
    import sys
    s = sys.argv[1] if len(sys.argv) > 1 else "1"
    for k, v in generate(s).items():
        print("%-11s = %s" % (k, v))
