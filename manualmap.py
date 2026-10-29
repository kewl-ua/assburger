r"""
manualmap.py - generic 32-bit manual mapper for the CERBERUS spoofer (no LoadLibrary).

Why: a LoadLibrary'd DLL stays in the PEB module list (Module32 / EnumProcessModules). This mapper
maps the PE itself (SEC_IMAGE by default), fixes the IAT, runs the TLS callbacks (rfspoof is a MinGW
DLL with a .tls directory - unlike Bagnon), runs DllMain via NtCreateThreadEx, unlinks the PEB entry
and wipes the DOS/PE headers.

`reserved` contract for DllMain: a buffer with two NUL-terminated ASCII strings:
    "<dll path>\0<cfg path>\0"
spoof.c reads the first (fallback cfg next to the DLL) and the second (explicit per-profile cfg).
Bagnon reads only the first (its own mapper does the same).

One copy per process is enforced by spoof.c itself (Local\RFSpoofMutex_<pid>); the loader checks the
same name before mapping, and can poll Local\RFSpoofState_<pid> for ready/hooks.

Usage:
    python manualmap.py --check rfspoof.new.dll
    python manualmap.py --status --pid 1234
    python manualmap.py --map --pid 1234 --dll rfspoof.new.dll --cfg spoof_2.cfg
"""
import ctypes
import json
import os
import struct
import sys
import time
from ctypes import wintypes

import pefile

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state")
LOG_DIR = os.path.join(HERE, "logs")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
advapi = ctypes.WinDLL("advapi32", use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_CREATE_THREAD = 0x0002
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40

IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_MEM_WRITE = 0x80000000

TH32CS_SNAPPROCESS = 0x2
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
DLL_PROCESS_ATTACH = 1
DLL_PROCESS_DETACH = 0

RFS_STATE_MAGIC = 0x31534652   # "RFS1"
RFS_STATE_VERSION = 1
RFS_STATE_FMT = "<IIIIIII260s"
RFS_STATE_SIZE = struct.calcsize(RFS_STATE_FMT)

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                    wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
kernel32.VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                      wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
kernel32.VirtualProtectEx.restype = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.CreateRemoteThread.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
kernel32.CreateRemoteThread.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CreateFileA.argtypes = [wintypes.LPCSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateFileA.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenFileMappingW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.DWORD, ctypes.c_size_t]
kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]

ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
ntdll.NtQueryInformationProcess.restype = ctypes.c_long
ntdll.NtCreateThreadEx.restype = ctypes.c_long
ntdll.NtCreateThreadEx.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.HANDLE, ctypes.c_void_p,
                                    ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t,
                                    ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p]


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def enable_debug_privilege():
    try:
        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

        class LAA(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

        class TP(ctypes.Structure):
            _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LAA * 1)]

        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.HANDLE)]
        advapi.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                  ctypes.POINTER(LUID)]
        advapi.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL,
                                                  ctypes.POINTER(TP), wintypes.DWORD,
                                                  ctypes.c_void_p, ctypes.c_void_p]
        tok = wintypes.HANDLE()
        if not advapi.OpenProcessToken(kernel32.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(tok)):
            return False
        luid = LUID()
        advapi.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid))
        tp = TP()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = 0x2
        advapi.AdjustTokenPrivileges(tok, False, ctypes.byref(tp), 0, None, None)
        kernel32.CloseHandle(tok)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ target process helpers
class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


class MEMORY_BASIC_INFORMATION32(ctypes.Structure):
    _fields_ = [("BaseAddress", wintypes.DWORD), ("AllocationBase", wintypes.DWORD),
                ("AllocationProtect", wintypes.DWORD), ("RegionSize", wintypes.DWORD),
                ("State", wintypes.DWORD), ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    """VirtualQueryEx called from 64-bit Python returns the 64-bit layout even for a WOW64 target."""
    _fields_ = [("BaseAddress", ctypes.c_ulonglong), ("AllocationBase", ctypes.c_ulonglong),
                ("AllocationProtect", wintypes.DWORD), ("__a1", wintypes.DWORD),
                ("RegionSize", ctypes.c_ulonglong), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("__a2", wintypes.DWORD)]


class _OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                ("ObjectName", ctypes.c_void_p), ("Attributes", wintypes.ULONG),
                ("SecurityDescriptor", ctypes.c_void_p), ("SecurityQualityOfService", ctypes.c_void_p)]


def _rpm(h, addr, size):
    buf = (ctypes.c_char * size)()
    got = ctypes.c_size_t(0)
    if not kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
        return None
    return buf.raw[:got.value]


def _rpm32(h, addr):
    b = _rpm(h, addr, 4)
    return _u32(b, 0) if b and len(b) == 4 else 0


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
    v = buf.value
    return (v & 0xFFFFFFFF) if v else 0


def peb_modules(h):
    peb = _peb32(h)
    if not peb:
        return
    ldr = _u32(_rpm(h, peb + 0x0C, 4) or b"\0\0\0\0", 0)
    if not ldr:
        return
    head = ldr + 0x0C
    cur = _u32(_rpm(h, head, 4) or b"\0\0\0\0", 0)
    for _ in range(2048):
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


def _module_base(h, name):
    name = name.lower()
    for b, n in peb_modules(h):
        if n == name:
            return b
    return 0


def _resolve_export_by_base(h, modbase, func):
    dos = _rpm(h, modbase, 0x40)
    if not dos or dos[:2] != b"MZ":
        return 0
    pe_off = modbase + _u32(dos, 0x3C)
    hdr = _rpm(h, pe_off, 0x100)
    if not hdr:
        return 0
    opt = 0x18
    dd = opt + 0x60
    exp_rva = _u32(hdr, dd)
    if not exp_rva:
        return 0
    exp = _rpm(h, modbase + exp_rva, 0x28)
    if not exp:
        return 0
    nnames = _u32(exp, 0x18)
    names_rva = _u32(exp, 0x20)
    ords_rva = _u32(exp, 0x24)
    funcs_rva = _u32(exp, 0x1C)
    names = _rpm(h, modbase + names_rva, nnames * 4)
    if not names:
        return 0
    for i in range(nnames):
        nr = _u32(names, i * 4)
        nb = _rpm(h, modbase + nr, 64)
        if not nb:
            continue
        nm = nb.split(b"\0")[0].decode("latin1")
        if nm == func:
            ords = _rpm(h, modbase + ords_rva, nnames * 2)
            idx = _u16(ords, i * 2)
            funcs = _rpm(h, modbase + funcs_rva, (idx + 1) * 4)
            return modbase + _u32(funcs, idx * 4)
    return 0


def _resolve_ordinal(h, modbase, ordinal):
    dos = _rpm(h, modbase, 0x40)
    if not dos:
        return 0
    pe_off = modbase + _u32(dos, 0x3C)
    hdr = _rpm(h, pe_off, 0x100)
    if not hdr:
        return 0
    exp_rva = _u32(hdr, 0x18 + 0x60)
    exp = _rpm(h, modbase + exp_rva, 0x28)
    if not exp:
        return 0
    base_ord = _u32(exp, 0x10)
    funcs_rva = _u32(exp, 0x1C)
    n = _u32(exp, 0x14)
    idx = ordinal - base_ord
    if idx < 0 or idx >= n:
        return 0
    funcs = _rpm(h, modbase + funcs_rva, (idx + 1) * 4)
    return modbase + _u32(funcs, idx * 4)


# ------------------------------------------------------------------ remote calls
def _start_thread(h, stub_addr, param=0, timeout=8000):
    """Run stub_addr in the target. Returns the thread exit code (EAX at `ret`)."""
    th = wintypes.HANDLE()
    st = ntdll.NtCreateThreadEx(ctypes.byref(th), 0x1FFFFF, None, h,
                                ctypes.c_void_p(stub_addr), ctypes.c_void_p(param), 0, 0, 0, 0, None)
    if st == 0 and th:
        wr = kernel32.WaitForSingleObject(th, timeout)
        code = wintypes.DWORD(0)
        kernel32.GetExitCodeThread(th, ctypes.byref(code))
        kernel32.CloseHandle(th)
        if wr == 0x102:
            raise OSError("remote call did not finish in %d ms" % timeout)
        return code.value & 0xFFFFFFFF
    tid = wintypes.DWORD(0)
    th = kernel32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(stub_addr),
                                     ctypes.c_void_p(param), 0, ctypes.byref(tid))
    if not th:
        raise OSError("all thread methods failed, err=%d" % ctypes.get_last_error())
    wr = kernel32.WaitForSingleObject(th, timeout)
    code = wintypes.DWORD(0)
    kernel32.GetExitCodeThread(th, ctypes.byref(code))
    kernel32.CloseHandle(th)
    if wr == 0x102:
        raise OSError("remote call did not finish in %d ms" % timeout)
    return code.value & 0xFFFFFFFF


def _exec_stub(h, blob, timeout=8000):
    addr = kernel32.VirtualAllocEx(h, None, len(blob), MEM_COMMIT | MEM_RESERVE,
                                   PAGE_EXECUTE_READWRITE)
    if not addr:
        raise OSError("VirtualAllocEx(stub) failed err=%d" % ctypes.get_last_error())
    ok = False
    try:
        if not _wpm(h, addr, blob):
            raise OSError("writing the remote stub failed")
        r = _start_thread(h, addr, 0, timeout)
        ok = True
        return r
    finally:
        if ok:
            kernel32.VirtualFreeEx(h, ctypes.c_void_p(addr), 0, MEM_RELEASE)


def _call_stdcall(h, func, args=(), timeout=8000):
    """call a __stdcall function with 32-bit args; the callee pops them (Win32 ABI)."""
    stub = bytearray()
    for a in reversed(args):
        stub += b"\x68" + struct.pack("<I", a & 0xFFFFFFFF)
    stub += b"\xB8" + struct.pack("<I", func & 0xFFFFFFFF)   # mov eax, func
    stub += b"\xFF\xD0"                                       # call eax
    stub += b"\xC3"                                           # ret
    return _exec_stub(h, bytes(stub), timeout)


def _load_library(h, name):
    kbase = _module_base(h, "kernel32.dll") or _module_base(h, "kernelbase.dll")
    func = _get_proc(h, kbase, "LoadLibraryA") if kbase else 0
    if not func:
        func = _resolve_export_by_base(h, kbase, "LoadLibraryA")
    if not func:
        raise OSError("LoadLibraryA not found in target")
    data = name.encode("ascii", "replace") + b"\0"
    addr = kernel32.VirtualAllocEx(h, None, len(data), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    if not addr:
        raise OSError("VirtualAllocEx(import name) failed")
    try:
        _wpm(h, addr, data)
        return _call_stdcall(h, func, (addr,))
    finally:
        kernel32.VirtualFreeEx(h, ctypes.c_void_p(addr), 0, MEM_RELEASE)


def _get_proc_arg(h, modbase, lp_proc_name):
    func = _resolve_export_by_base(h, _module_base(h, "kernel32.dll"), "GetProcAddress")
    if not func:
        raise OSError("GetProcAddress not found in target")
    return _call_stdcall(h, func, (modbase, lp_proc_name))


def _get_proc(h, modbase, name):
    func = _resolve_export_by_base(h, _module_base(h, "kernel32.dll"), "GetProcAddress")
    if not func:
        raise OSError("GetProcAddress not found in target")
    data = name.encode("ascii", "replace") + b"\0"
    addr = kernel32.VirtualAllocEx(h, None, len(data), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    if not addr:
        raise OSError("VirtualAllocEx(proc name) failed")
    try:
        _wpm(h, addr, data)
        return _call_stdcall(h, func, (modbase, addr))
    finally:
        kernel32.VirtualFreeEx(h, ctypes.c_void_p(addr), 0, MEM_RELEASE)


# ------------------------------------------------------------------ PE
class PE(object):
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.pe = pefile.PE(self.path, fast_load=False)
        self.raw = open(self.path, "rb").read()
        oh = self.pe.OPTIONAL_HEADER
        self.image_base = oh.ImageBase
        self.size_of_image = oh.SizeOfImage
        self.size_of_headers = oh.SizeOfHeaders
        self.entry_rva = oh.AddressOfEntryPoint
        self.machine = self.pe.FILE_HEADER.Machine
        self.reloc_rva = 0
        self.reloc_size = 0
        try:
            self.reloc_rva = oh.DATA_DIRECTORY[5].VirtualAddress
            self.reloc_size = oh.DATA_DIRECTORY[5].Size
        except Exception:
            pass

    def sections(self):
        for s in self.pe.sections:
            name = s.Name.rstrip(b"\0").decode("latin1")
            yield (name, s.VirtualAddress, s.Misc_VirtualSize,
                   s.PointerToRawData, s.SizeOfRawData, s.Characteristics)

    def prot(self, chars):
        if chars & IMAGE_SCN_MEM_EXECUTE:
            return PAGE_EXECUTE_READWRITE if chars & IMAGE_SCN_MEM_WRITE else PAGE_EXECUTE_READ
        if chars & IMAGE_SCN_MEM_WRITE:
            return PAGE_READWRITE
        return PAGE_READONLY

    def imports(self):
        out = []
        for imp in getattr(self.pe, "DIRECTORY_ENTRY_IMPORT", []):
            dll = imp.dll.decode("latin1")
            items = []
            for f in imp.imports:
                if f.name:
                    items.append(("name", f.name.decode("latin1"), f.address - self.image_base))
                else:
                    items.append(("ord", f.ordinal, f.address - self.image_base))
            out.append((dll, items))
        return out


# ------------------------------------------------------------------ mapping internals
def _fix_imports(h, base, pe, log):
    modules = {}
    names = {n for _b, n in peb_modules(h)}
    total = 0
    for dll, items in pe.imports():
        dl = dll.lower()
        modbase = modules.get(dl)
        if not modbase:
            modbase = _module_base(h, dl)
            if not modbase:
                log("import dll %s not loaded, loading in target" % dll)
                modbase = _load_library(h, dll)
                if not modbase:
                    raise OSError("cannot load import dll %s in target" % dll)
            modules[dl] = modbase
            names.add(dl)
        for kind, what, iat_rva in items:
            if kind == "ord":
                # GetProcAddress(h, MAKEINTRESOURCE(ord)) handles forwarded ordinals too
                faddr = _get_proc_arg(h, modbase, 0x80000000 | (what & 0xFFFF))
                if not faddr:
                    faddr = _resolve_ordinal(h, modbase, what)
            else:
                # always go through the target's GetProcAddress: API-set/UCRT exports are
                # forwarders, and a raw export-RVA would point at the forwarder string.
                faddr = _get_proc(h, modbase, what)
                if not faddr:
                    faddr = _resolve_export_by_base(h, modbase, what)
            if not faddr:
                raise OSError("unresolved import %s!%s" % (dll, what))
            if not _wpm(h, base + iat_rva, struct.pack("<I", faddr & 0xFFFFFFFF)):
                raise OSError("writing IAT %s!%s failed" % (dll, what))
            total += 1
    log("imports resolved: %d" % total)


def _tls_dir(pe):
    try:
        return pe.pe.DIRECTORY_ENTRY_TLS.struct
    except Exception:
        return None


def _init_tls(h, base, pe, log, reason=DLL_PROCESS_ATTACH):
    t = _tls_dir(pe)
    if not t:
        return
    idx_rva = t.AddressOfIndex - pe.image_base
    cb_rva = t.AddressOfCallBacks - pe.image_base
    kbase = _module_base(h, "kernel32.dll")
    func = _get_proc(h, kbase, "TlsAlloc") if kbase else 0
    if not func:
        func = _resolve_export_by_base(h, kbase, "TlsAlloc")
    idx = 0
    if func:
        idx = _call_stdcall(h, func, ())
        if idx and idx != 0xFFFFFFFF and _wpm(h, base + idx_rva, struct.pack("<I", idx)):
            log("TLS index allocated: %d" % idx)
    if not cb_rva:
        return
    n = 0
    for i in range(32):
        cb = _rpm32(h, base + cb_rva + i * 4)
        if not cb:
            break
        _call_stdcall(h, cb, (base, reason, 0))
        n += 1
    if n:
        log("TLS callbacks run: %d (reason %d)" % (n, reason))


def _write_entry_stub(h, base, entry, param_addr):
    stub = bytearray()
    stub += b"\x68" + struct.pack("<I", param_addr)   # push reserved (dll\0cfg\0)
    stub += b"\x6A\x01"                               # push DLL_PROCESS_ATTACH
    stub += b"\x68" + struct.pack("<I", base)         # push hinst
    call_at = 5 + 2 + 5
    stub += b"\xE8\x00\x00\x00\x00"
    stub += b"\xC3"
    addr = kernel32.VirtualAllocEx(h, None, len(stub), MEM_COMMIT | MEM_RESERVE,
                                   PAGE_EXECUTE_READWRITE)
    if not addr:
        raise OSError("VirtualAllocEx(entry stub) failed")
    # the E8 is relative to the stub (allocated elsewhere), not to the image base
    struct.pack_into("<i", stub, call_at + 1, entry - (addr + call_at + 5))
    _wpm(h, addr, bytes(stub))
    old = wintypes.DWORD(0)
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(addr), len(stub), PAGE_EXECUTE_READ,
                              ctypes.byref(old))
    return addr


def _hide_headers(h, base, pe, log):
    if os.environ.get("RF_NOHEAD"):
        return
    _wpm(h, base, b"\0" * 0x40)
    pe_off = _u32(pe.raw, 0x3C)
    if 0 < pe_off < 0x400:
        _wpm(h, base + pe_off, b"\0" * 4)
    old = wintypes.DWORD(0)
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(base), 0x1000, PAGE_READONLY, ctypes.byref(old))
    log("DOS+PE headers zeroed")


def _reserved_blob(dll_path, cfg):
    blob = os.path.abspath(dll_path).encode("ascii", "replace") + b"\0"
    if cfg:
        blob += os.path.abspath(cfg).encode("ascii", "replace") + b"\0"
    else:
        blob += b"\0"
    return blob


def _write_record(pid, base, dll, cfg, kind="spoof", method=""):
    try:
        d = os.path.join(STATE_DIR, str(pid))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "%s.json" % kind), "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "base": base, "dll": os.path.abspath(dll),
                       "cfg": os.path.abspath(cfg) if cfg else "", "method": method,
                       "time": time.time()}, f)
    except Exception:
        pass


def read_record(pid, kind="spoof"):
    try:
        with open(os.path.join(STATE_DIR, str(pid), "%s.json" % kind), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _manual_map_image(h, pid, dll_path, cfg, log, then_unlink=True):
    dll_path = os.path.abspath(dll_path)
    pe = PE(dll_path)
    fh = kernel32.CreateFileA(dll_path.encode("ascii", "replace"), 0x80000000 | 0x00100000,
                              1, None, 3, 0, None)
    if not fh or fh == wintypes.HANDLE(-1).value:
        raise OSError("CreateFileA(%s) failed err=%d" % (dll_path, ctypes.get_last_error()))
    sec = wintypes.HANDLE()
    try:
        ntdll.NtCreateSection.restype = ctypes.c_long
        ntdll.NtCreateSection.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG,
                                          ctypes.POINTER(_OBJECT_ATTRIBUTES), ctypes.c_void_p,
                                          wintypes.ULONG, wintypes.ULONG, wintypes.HANDLE]
        oa = _OBJECT_ATTRIBUTES()
        oa.Length = ctypes.sizeof(oa)
        st = ntdll.NtCreateSection(ctypes.byref(sec), 0xF001F, ctypes.byref(oa), None,
                                    PAGE_READONLY, 0x1000000, wintypes.HANDLE(fh))   # SEC_IMAGE
        if st != 0:
            raise OSError("NtCreateSection status 0x%08X" % (st & 0xFFFFFFFF))
        ntdll.NtMapViewOfSection.restype = ctypes.c_long
        ntdll.NtMapViewOfSection.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
                                              ctypes.POINTER(ctypes.c_void_p),
                                              ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p,
                                              ctypes.POINTER(ctypes.c_size_t), wintypes.ULONG,
                                              wintypes.ULONG, wintypes.ULONG]
        # Prefer the DLL's own ImageBase, exactly where LoadLibrary used to put it. An
        # arbitrary free hole can be reserved by the game/RFOCliMod later and then the image
        # (and its hooks) is overwritten. Fall back to an arbitrary base if it is busy.
        base = ctypes.c_void_p(pe.image_base)
        vsize = ctypes.c_size_t(0)
        st = ntdll.NtMapViewOfSection(sec, h, ctypes.byref(base), 0, 0, None,
                                      ctypes.byref(vsize), 2, 0, PAGE_READWRITE)
        if st != 0 or not base.value:
            base = ctypes.c_void_p(0)
            vsize = ctypes.c_size_t(0)
            st = ntdll.NtMapViewOfSection(sec, h, ctypes.byref(base), 0, 0, None,
                                          ctypes.byref(vsize), 2, 0, PAGE_READWRITE)
        if st != 0 or not base.value:
            raise OSError("NtMapViewOfSection status 0x%08X" % (st & 0xFFFFFFFF))
        base = base.value & 0xFFFFFFFF
        log("mapped at 0x%08X (SEC_IMAGE, MEM_IMAGE)" % base)

        old = wintypes.DWORD(0)
        if not kernel32.VirtualProtectEx(h, ctypes.c_void_p(base), pe.size_of_image,
                                         PAGE_READWRITE, ctypes.byref(old)):
            raise OSError("VirtualProtectEx(image RW) failed err=%d" % ctypes.get_last_error())
        try:
            _fix_imports(h, base, pe, log)
            for _name, vaddr, vsize, _rawptr, _rawsize, chars in pe.sections():
                if vsize:
                    kernel32.VirtualProtectEx(h, ctypes.c_void_p(base + vaddr), vsize,
                                               pe.prot(chars), ctypes.byref(old))
            _init_tls(h, base, pe, log)
        except Exception:
            # entry has not run yet: drop the half-prepared image so a retry does not leak it
            try:
                ntdll.NtUnmapViewOfSection.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
                ntdll.NtUnmapViewOfSection.restype = ctypes.c_long
                ntdll.NtUnmapViewOfSection(h, ctypes.c_void_p(base))
            except Exception:
                pass
            raise

        blob = _reserved_blob(dll_path, cfg)
        path_addr = kernel32.VirtualAllocEx(h, None, len(blob), MEM_COMMIT | MEM_RESERVE,
                                            PAGE_READWRITE)
        if not path_addr:
            raise OSError("VirtualAllocEx(path) failed")
        if not _wpm(h, path_addr, blob):
            raise OSError("writing reserved path failed")
        stub = _write_entry_stub(h, base, base + pe.entry_rva, path_addr)
        method = "NtCreateThreadEx"
        entry_ok = False
        try:
            try:
                _start_thread(h, stub, 0, 8000)
                entry_ok = True
                log("entry run via NtCreateThreadEx")
            except OSError as e:
                # the thread may just be slow: the status block is the real proof
                if wait_spoof_ready(pid, 5.0):
                    entry_ok = True
                    log("entry timeout but spoof status is ready (%s)" % e)
                else:
                    raise
        finally:
            # on a timeout the thread may still run inside the stub/path buffers: keep them
            if entry_ok and not os.environ.get("RF_KEEPSTUB"):
                kernel32.VirtualFreeEx(h, ctypes.c_void_p(stub), 0, MEM_RELEASE)
                kernel32.VirtualFreeEx(h, ctypes.c_void_p(path_addr), 0, MEM_RELEASE)
        try:
            if then_unlink:
                ok = unlink_peb(h, base)
                if ok:
                    log("PEB unlink: done")
            _hide_headers(h, base, pe, log)
        except Exception as e:
            log("post-entry step failed (%s): image stays mapped" % e)
        _write_record(pid, base, dll_path, cfg, "spoof", method)
        return base
    finally:
        if fh:
            kernel32.CloseHandle(fh)
        if sec:
            kernel32.CloseHandle(sec)


def _apply_relocs(h, base, pe, delta, log):
    off0 = pe.pe.get_offset_from_rva(pe.reloc_rva)
    data = pe.raw[off0:off0 + pe.reloc_size]
    off = 0
    count = 0
    while off + 8 <= len(data):
        page_rva = _u32(data, off)
        block_size = _u32(data, off + 4)
        if block_size < 8:
            break
        for i in range((block_size - 8) // 2):
            entry = _u16(data, off + 8 + i * 2)
            if (entry >> 12) == 3:   # HIGHLOW
                a = base + page_rva + (entry & 0xFFF)
                _wpm(h, a, struct.pack("<I", (_rpm32(h, a) + delta) & 0xFFFFFFFF))
                count += 1
        off += block_size
    log("relocations applied: %d (delta 0x%X)" % (count, delta))


def _manual_map_private(h, pid, dll_path, cfg, log, then_unlink=True):
    dll_path = os.path.abspath(dll_path)
    pe = PE(dll_path)
    base = kernel32.VirtualAllocEx(h, ctypes.c_void_p(pe.image_base), pe.size_of_image,
                                   MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not base:
        base = kernel32.VirtualAllocEx(h, None, pe.size_of_image, MEM_COMMIT | MEM_RESERVE,
                                       PAGE_EXECUTE_READWRITE)
    if not base:
        raise OSError("VirtualAllocEx image failed")
    base = base & 0xFFFFFFFF
    delta = (base - pe.image_base) & 0xFFFFFFFF
    log("mapped at 0x%08X (private, delta 0x%X)" % (base, delta))
    if not _wpm(h, base, pe.raw[:pe.size_of_headers]):
        raise OSError("writing headers failed")
    ranges = []
    for name, vaddr, vsize, rawptr, rawsize, chars in pe.sections():
        if rawsize:
            if not _wpm(h, base + vaddr, pe.raw[rawptr:rawptr + rawsize]):
                raise OSError("writing section %s failed" % name)
            if vsize > rawsize:
                _wpm(h, base + vaddr + rawsize, b"\0" * (vsize - rawsize))
        ranges.append((vaddr, vsize, chars))
    if delta:
        _apply_relocs(h, base, pe, delta, log)
    _fix_imports(h, base, pe, log)
    _init_tls(h, base, pe, log)
    old = wintypes.DWORD(0)
    for vaddr, vsize, chars in ranges:
        if vsize:
            kernel32.VirtualProtectEx(h, ctypes.c_void_p(base + vaddr), vsize,
                                       pe.prot(chars), ctypes.byref(old))
    blob = _reserved_blob(dll_path, cfg)
    path_addr = kernel32.VirtualAllocEx(h, None, len(blob), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    if not path_addr or not _wpm(h, path_addr, blob):
        raise OSError("writing reserved path failed")
    stub = _write_entry_stub(h, base, base + pe.entry_rva, path_addr)
    entry_ok = False
    try:
        try:
            _start_thread(h, stub, 0, 8000)
            entry_ok = True
            log("entry run via NtCreateThreadEx")
        except OSError as e:
            if wait_spoof_ready(pid, 5.0):
                entry_ok = True
                log("entry timeout but spoof status is ready (%s)" % e)
            else:
                raise
    finally:
        if entry_ok and not os.environ.get("RF_KEEPSTUB"):
            kernel32.VirtualFreeEx(h, ctypes.c_void_p(stub), 0, MEM_RELEASE)
            kernel32.VirtualFreeEx(h, ctypes.c_void_p(path_addr), 0, MEM_RELEASE)
    try:
        if then_unlink:
            unlink_peb(h, base)
        _hide_headers(h, base, pe, log)
    except Exception as e:
        log("post-entry step failed (%s)" % e)
    _write_record(pid, base, dll_path, cfg, "spoof", "NtCreateThreadEx")
    return base


def unlink_peb(h, base):
    peb = _peb32(h)
    if not peb:
        return False
    ldr = _u32(_rpm(h, peb + 0x0C, 4) or b"\0\0\0\0", 0)
    if not ldr:
        return False
    head = ldr + 0x0C
    cur = _u32(_rpm(h, head, 4) or b"\0\0\0\0", 0)
    for _ in range(2048):
        if not cur or cur == head:
            break
        b = _u32(_rpm(h, cur + 0x18, 4) or b"\0\0\0\0", 0)
        if b == base:
            flink = _u32(_rpm(h, cur, 4) or b"\0\0\0\0", 0)
            blink = _u32(_rpm(h, cur + 4, 4) or b"\0\0\0\0", 0)
            _wpm(h, blink, struct.pack("<I", flink))
            _wpm(h, flink + 4, struct.pack("<I", blink))
            return True
        cur = _u32(_rpm(h, cur, 4) or b"\0\0\0\0", 0)
    return False


# ------------------------------------------------------------------ public API
def spoof_mutex_exists(pid):
    name = "Local\\RFSpoofMutex_%d" % pid
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    m = kernel32.OpenMutexW(0x00100000, False, name)   # SYNCHRONIZE
    if not m:
        return False
    kernel32.CloseHandle(m)
    return True


def spoof_modules(pid):
    """Names of any LoadLibrary'd legacy spoofer modules in the target (pre-manual-map clients)."""
    h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        return []
    try:
        return [n for _b, n in peb_modules(h) if "rfspoof" in n]
    finally:
        kernel32.CloseHandle(h)


def spoof_state(pid):
    name = "Local\\RFSpoofState_%d" % pid
    hmap = kernel32.OpenFileMappingW(0x0004, False, name)   # FILE_MAP_READ
    if not hmap:
        return None
    p = kernel32.MapViewOfFile(hmap, 0x0004, 0, 0, RFS_STATE_SIZE)
    try:
        if not p:
            return None
        buf = ctypes.string_at(p, RFS_STATE_SIZE)
    finally:
        if p:
            kernel32.UnmapViewOfFile(ctypes.c_void_p(p))
        kernel32.CloseHandle(hmap)
    magic, version, spid, tick, ready, hooks, cfg_len, cfg = struct.unpack(RFS_STATE_FMT, buf)
    age = (int(kernel32.GetTickCount()) - int(tick)) & 0xFFFFFFFF
    return {"magic": magic, "version": version, "pid": spid, "tick": tick, "age": age,
            "ready": bool(ready), "hooks": hooks,
            "cfg": cfg.split(b"\0")[0].decode("latin1", "replace")}


def spoof_live(pid, max_age=10000):
    if not spoof_mutex_exists(pid):
        return False
    st = spoof_state(pid)
    if not st:
        return False
    return (st["magic"] == RFS_STATE_MAGIC and st["version"] == RFS_STATE_VERSION
            and st["pid"] == pid and st["ready"] and st["age"] < max_age)


def wait_spoof_ready(pid, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        st = spoof_state(pid)
        if st and st["magic"] == RFS_STATE_MAGIC and st["version"] == RFS_STATE_VERSION \
                and st["pid"] == pid and st["ready"] and st["age"] < 15000:
            return st
        time.sleep(0.1)
    return None


def map_module(pid, dll_path, cfg=None, log=print, then_unlink=True, mode=None,
               allow_reuse=True, wait_ready=True, ready_timeout=15.0):
    """Map dll_path into pid. Returns (base, reused). Raises on failure (fail-closed)."""
    enable_debug_privilege()
    dll_path = os.path.abspath(dll_path)
    if not os.path.isfile(dll_path):
        raise OSError("missing %s" % dll_path)
    pe = PE(dll_path)
    if pe.machine != 0x14C:
        raise OSError("%s is not i386 (machine 0x%X)" % (dll_path, pe.machine))
    if not pe.reloc_rva and mode != "preferred":
        raise OSError("%s has no .reloc section; SEC_IMAGE needs relocations" % dll_path)
    if allow_reuse and spoof_mutex_exists(pid):
        st = spoof_state(pid)
        rec = read_record(pid) or {}
        base = (rec or {}).get("base") or 0
        log("spoof already present in pid %d (ready=%s base=0x%08X), reuse"
            % (pid, bool(st and st["ready"]), base))
        if wait_ready and not (st and st["ready"]):
            st = wait_spoof_ready(pid, ready_timeout)
            if not st:
                raise OSError("spoof mutex exists in pid %d but status is not ready" % pid)
        return base, True

    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        h = kernel32.OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
                                 PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ,
                                 False, pid)
    if not h:
        raise OSError("OpenProcess(pid=%d) failed err=%d (run elevated)"
                      % (pid, ctypes.get_last_error()))
    # serialize app.py and the guard when both see a new pid at the same moment
    lock = kernel32.CreateMutexW(None, False, "Local\\RFSpoofLoad_%d" % pid)
    if lock:
        kernel32.WaitForSingleObject(lock, 30000)
    try:
        if allow_reuse and spoof_mutex_exists(pid):
            st = spoof_state(pid)
            if wait_ready and not (st and st["ready"]):
                st = wait_spoof_ready(pid, ready_timeout)
            if st and st["ready"]:
                rec = read_record(pid) or {}
                log("spoof mapped by a concurrent loader in pid %d, reuse" % pid)
                return (rec or {}).get("base") or 0, True
        mode = (mode or os.environ.get("RF_MAP", "image")).lower()
        if mode in ("image", "auto"):
            try:
                base = _manual_map_image(h, pid, dll_path, cfg, log, then_unlink)
            except Exception as e:
                if mode == "image":
                    raise
                log("SEC_IMAGE map failed (%s), falling back to private" % e)
                base = _manual_map_private(h, pid, dll_path, cfg, log, then_unlink)
        else:
            base = _manual_map_private(h, pid, dll_path, cfg, log, then_unlink)
    finally:
        if lock:
            kernel32.ReleaseMutex(lock)
            kernel32.CloseHandle(lock)
        kernel32.CloseHandle(h)

    if wait_ready:
        st = wait_spoof_ready(pid, ready_timeout)
        if not st:
            raise OSError("mapped at 0x%08X but spoof status is not ready after %.1fs"
                          % (base, ready_timeout))
        log("spoof status ready: hooks=%d cfg=%s" % (st["hooks"], st["cfg"]))
    return base, False


def mapped_region(pid, base):
    """True when base is a committed image view in pid (used to trust a .mapped record)."""
    h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        return False
    try:
        mbi = MEMORY_BASIC_INFORMATION64()
        n = kernel32.VirtualQueryEx(h, ctypes.c_void_p(base), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if not n:
            return False
        return mbi.State == 0x1000 and mbi.Type in (0x1000000, 0x20000)   # MEM_IMAGE / MEM_PRIVATE
    finally:
        kernel32.CloseHandle(h)


def free_mapped(pid, base, log=print):
    enable_debug_privilege()
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION, False, pid)
    if not h:
        raise OSError("OpenProcess failed err=%d" % ctypes.get_last_error())
    try:
        ntdll.NtUnmapViewOfSection.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        ntdll.NtUnmapViewOfSection.restype = ctypes.c_long
        st = ntdll.NtUnmapViewOfSection(h, ctypes.c_void_p(base))
        if st == 0:
            log("NtUnmapViewOfSection(0x%08X): ok" % base)
            return True
        ok = kernel32.VirtualFreeEx(h, ctypes.c_void_p(base), 0, MEM_RELEASE)
        log("VirtualFreeEx(0x%08X): %s" % (base, "ok" if ok else "failed"))
        return bool(ok)
    finally:
        kernel32.CloseHandle(h)


# ------------------------------------------------------------------ static check / cli
def check_dll(path):
    pe = PE(path)
    tls = _tls_dir(pe)
    callbacks = []
    if tls:
        rva = tls.AddressOfCallBacks - pe.image_base
        off = pe.pe.get_offset_from_rva(rva) if rva else None
        if off is not None:
            for i in range(16):
                v = _u32(pe.raw, off + i * 4)
                if not v:
                    break
                callbacks.append(v)
    out = {
        "path": os.path.abspath(path),
        "machine": "i386" if pe.machine == 0x14C else "0x%X" % pe.machine,
        "image_base": "0x%08X" % pe.image_base,
        "size_of_image": "0x%X" % pe.size_of_image,
        "entry_rva": "0x%X" % pe.entry_rva,
        "reloc": bool(pe.reloc_rva),
        "reloc_rva": "0x%X" % pe.reloc_rva,
        "tls": bool(tls),
        "tls_index_rva": "0x%X" % ((tls.AddressOfIndex - pe.image_base) if tls else 0),
        "tls_callbacks": len(callbacks),
        "imports": [d for d, _ in pe.imports()],
        "sections": [s[0] for s in pe.sections()],
        "timestamp": pe.pe.FILE_HEADER.TimeDateStamp,
    }
    return out


def find_pids_by_name(name_lower):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return []
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(pe)
    out = []
    ok = kernel32.Process32First(snap, ctypes.byref(pe))
    while ok:
        if pe.szExeFile.decode("latin1").lower() == name_lower:
            out.append(pe.th32ProcessID)
        ok = kernel32.Process32Next(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    return out


def main(argv=None):
    argv = argv or sys.argv[1:]
    if "--check" in argv:
        p = argv[argv.index("--check") + 1]
        print(json.dumps(check_dll(p), indent=2))
        return 0
    if "--status" in argv:
        pid = int(argv[argv.index("--pid") + 1])
        print(json.dumps({"mutex": spoof_mutex_exists(pid), "state": spoof_state(pid)}, indent=2))
        return 0
    if "--map" in argv:
        pid = int(argv[argv.index("--pid") + 1])
        dll = argv[argv.index("--dll") + 1]
        cfg = argv[argv.index("--cfg") + 1] if "--cfg" in argv else None
        base, reused = map_module(pid, dll, cfg)
        print("pid=%d base=0x%08X reused=%s" % (pid, base, reused))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
