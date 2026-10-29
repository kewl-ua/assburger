import ctypes
import os
import struct
import sys
from ctypes import wintypes

RFBOT = r"C:\SHARE\rfbot2"
sys.path.insert(0, os.path.join(RFBOT, "tools"))
import manualmap as mm  # rfbot2 manual mapper

PID = int(sys.argv[1]) if len(sys.argv) > 1 else 10464
DLL = r"C:\SHARE\hwid\re_hackshield\poc\canary.dll"
SLOT = 0x00A41ED4
ORIG = 0x004038A0
LOG = r"C:\SHARE\hwid\re_hackshield\logs\canary.txt"

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = wintypes.HANDLE
k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")
    print(msg, flush=True)


def wp(h, addr, data):
    buf = ctypes.create_string_buffer(bytes(data), len(data))
    got = ctypes.c_size_t(0)
    if not k.WriteProcessMemory(h, ctypes.c_void_p(addr), buf, len(data), ctypes.byref(got)):
        raise OSError("WriteProcessMemory %08X err=%d" % (addr, ctypes.get_last_error()))
    return got.value


def rp32(h, addr):
    b = (ctypes.c_char * 4)()
    got = ctypes.c_size_t(0)
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), b, 4, ctypes.byref(got)):
        return None
    return struct.unpack("<I", b.raw)[0]


def main():
    mm.enable_debug_privilege()
    base = mm.manual_map(PID, DLL, log=log, then_unlink=True)
    log("canary base=0x%08X" % base)
    h = k.OpenProcess(0x1F0FFF, False, PID)
    if not h:
        h = k.OpenProcess(0x0002 | 0x0008 | 0x0010 | 0x0020 | 0x0400, False, PID)
    if not h:
        raise OSError("OpenProcess err=%d" % ctypes.get_last_error())
    try:
        # g_orig is an exported data pointer at RVA 0x3008; write the original vtable target
        wp(h, base + 0x3008, struct.pack("<I", ORIG))
        # write the canary function address (RVA 0x14a0) into the unused vtable slot
        old = wintypes.DWORD(0)
        k.VirtualProtectEx(h, ctypes.c_void_p(SLOT), 4, 0x04, ctypes.byref(old))
        wp(h, SLOT, struct.pack("<I", (base + 0x14A0) & 0xFFFFFFFF))
        k.VirtualProtectEx(h, ctypes.c_void_p(SLOT), 4, old.value, ctypes.byref(old))
        log("slot %08X = %08X (orig %08X)" % (SLOT, rp32(h, SLOT) or 0, ORIG))
        log("canary g_count=%s" % rp32(h, base + 0x602C))
    finally:
        k.CloseHandle(h)


if __name__ == "__main__":
    main()
