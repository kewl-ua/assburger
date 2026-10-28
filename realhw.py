# -*- coding: utf-8 -*-
"""realhw.py - read the REAL hardware values of this PC in the same format hwgen uses."""
import ctypes
import os
import subprocess
import uuid
from ctypes import wintypes

k = ctypes.WinDLL("kernel32", use_last_error=True)
iphlp = ctypes.WinDLL("iphlpapi", use_last_error=True)


def _vol(drive="C:\\"):
    try:
        k.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                            ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
        s = wintypes.DWORD(0)
        if k.GetVolumeInformationW(drive, None, 0, ctypes.byref(s), None, None, None, 0):
            return "%08X" % s.value
    except Exception:
        pass
    return ""


def _name():
    try:
        b = ctypes.create_unicode_buffer(256); n = wintypes.DWORD(256)
        if k.GetComputerNameW(b, ctypes.byref(n)):
            return b.value
    except Exception:
        pass
    return os.environ.get("COMPUTERNAME", "")


def _guid():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as kh:
            return winreg.QueryValueEx(kh, "MachineGuid")[0]
    except Exception:
        return ""


def _mac():
    try:
        class A(ctypes.Structure):
            pass
        A._fields_ = [("p", ctypes.POINTER(A)), ("i", wintypes.DWORD), ("an", ctypes.c_char * 260),
                      ("d", ctypes.c_char * 132), ("al", wintypes.UINT), ("ad", ctypes.c_ubyte * 8)]
        sz = wintypes.ULONG(0)
        iphlp.GetAdaptersInfo(None, ctypes.byref(sz))
        buf = (ctypes.c_ubyte * sz.value)()
        if iphlp.GetAdaptersInfo(ctypes.cast(buf, ctypes.c_void_p), ctypes.byref(sz)) == 0:
            p = ctypes.cast(buf, ctypes.POINTER(A))
            while p:
                a = p.contents
                if a.al >= 6:
                    return ":".join("%02X" % a.ad[i] for i in range(6))
                p = a.p
    except Exception:
        pass
    return ""


def _wmi(cls, prop):
    try:
        out = subprocess.run(["powershell", "-nop", "-c",
                              "(Get-CimInstance %s).%s" % (cls, prop)],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        return out
    except Exception:
        return ""


def _ram():
    try:
        class M(ctypes.Structure):
            _fields_ = [("l", wintypes.DWORD), ("load", wintypes.DWORD), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                        ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
        m = M(); m.l = ctypes.sizeof(m)
        k.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.total // (1024 * 1024)
    except Exception:
        return 0


def real():
    """Return the real PC's values in the hwgen schema."""
    return {
        "serial": _vol("C:\\"), "cname": _name(), "macaddr": _mac(), "guid": _guid(),
        "biosserial": _wmi("Win32_BIOS", "SerialNumber"),
        "boardserial": _wmi("Win32_BaseBoard", "SerialNumber"),
        "uuid": _wmi("Win32_ComputerSystemProduct", "UUID"),
        "rammb": _ram(),
    }


if __name__ == "__main__":
    for a, b in real().items():
        print("%-12s = %s" % (a, b))
