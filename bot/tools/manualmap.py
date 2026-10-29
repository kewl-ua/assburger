r"""
manualmap.py - inject a 32-bit DLL into a 32-bit target process WITHOUT LoadLibrary.

Why: the loader-based LoadLibrary leaves the module in the process module list
(Module32First/Next, EnumProcessModules). This injector maps the PE by hand and then
UNLINKS the entry from the PEB loader lists, so anti-cheat module scans do not see it.

What it does, step by step (all via the target's own kernel32 resolved from ITS PEB):
  1. find the target pid (rf_online*/cerberus-games) and open it,
  2. read the DLL file, parse headers (MZ/PE, IMAGE_FILE_MACHINE_I386, relocs present),
  3. VirtualAllocEx a region at (preferred base if free, else anywhere) with the section rights,
  4. write headers + sections,
  5. apply base relocations (reloc table) against the chosen base,
  6. resolve the import table (kernel32/user32/msvcrt/...) by walking the target's PEB module list,
  7. write the resolved import thunks,
  8. alloc + write the DLL path (ASCII) and, if present, a config path,
  9. CreateRemoteThread at the mapped entry (DllMain) with DLL_PROCESS_ATTACH,
 10. unlink the LDR_DATA_TABLE_ENTRY from InLoadOrder/InMemoryOrder/InInitOrder lists,
 11. keep a mapping of the mapped base for later (used to unlink a second time if re-linked).

Bitness: run from 32- or 64-bit Python; a 32-bit target is handled through its 32-bit PEB.
"""

import ctypes
import os
import struct
import sys
import time
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
advapi = ctypes.WinDLL("advapi32", use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_READ = 0x0010
PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READONLY = 0x02
PAGE_EXECUTE_READ = 0x20

TH32CS_SNAPPROCESS = 0x2
TH32CS_SNAPMODULE = 0x8
TH32CS_SNAPMODULE32 = 0x10
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

IMAGE_SCN_MEM_WRITE = 0x80000000
IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_MEM_READ = 0x40000000

DIRECTORY_ENTRY_EXPORT = 0
DIRECTORY_ENTRY_IMPORT = 1
DIRECTORY_ENTRY_BASERELOC = 5

DLL_PROCESS_ATTACH = 1

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
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
kernel32.IsWow64Process.restype = wintypes.BOOL
kernel32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                      wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
kernel32.VirtualProtectEx.restype = wintypes.BOOL
kernel32.CreateFileA.argtypes = [wintypes.LPCSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateFileA.restype = wintypes.HANDLE

ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
ntdll.NtQueryInformationProcess.restype = ctypes.c_long


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


# ------------------------------------------------------------------ helpers
def _u16(b, o): return struct.unpack_from("<H", b, o)[0]
def _u32(b, o): return struct.unpack_from("<I", b, o)[0]


def enable_debug_privilege():
    try:
        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

        class LAA(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

        class TP(ctypes.Structure):
            _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LAA * 1)]

        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi.OpenProcessToken.restype = wintypes.BOOL
        advapi.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID)]
        advapi.LookupPrivilegeValueW.restype = wintypes.BOOL
        advapi.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TP),
                                                 wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        advapi.AdjustTokenPrivileges.restype = wintypes.BOOL
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE

        tok = wintypes.HANDLE()
        if not advapi.OpenProcessToken(kernel32.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(tok)):
            return False
        luid = LUID()
        if not advapi.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
            kernel32.CloseHandle(tok)
            return False
        tp = TP(); tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = 0x2
        ok = advapi.AdjustTokenPrivileges(tok, False, ctypes.byref(tp), 0, None, None)
        rc = ctypes.get_last_error()
        kernel32.CloseHandle(tok)
        return bool(ok) and rc == 0
    except Exception:
        return False


def find_pids_by_name(name_lower):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
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


def find_game_pids(want=None):
    """All matching game pids (rf_online*.bin / cerberus-games.exe), in creation order, 32-bit first."""
    rf = []
    cerb = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return []
    pe = PROCESSENTRY32(); pe.dwSize = ctypes.sizeof(pe)
    ok = kernel32.Process32First(snap, ctypes.byref(pe))
    while ok:
        n = pe.szExeFile.decode("latin1").lower()
        if want:
            w = want.lower()
            if n == w or n.startswith(w.replace(".exe", "")):
                rf.append(pe.th32ProcessID)
        elif n.startswith("rf_online") and (n.endswith(".bin") or n.endswith(".exe")):
            rf.append(pe.th32ProcessID)
        elif n == "cerberus-games.exe":
            cerb.append(pe.th32ProcessID)
        ok = kernel32.Process32Next(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    names = rf or cerb
    names = sorted(names, key=lambda p: not is_wow64(p))   # 32-bit clients first
    return names


def find_game_pid(want=None):
    rf = []
    cerb = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return None
    pe = PROCESSENTRY32(); pe.dwSize = ctypes.sizeof(pe)
    ok = kernel32.Process32First(snap, ctypes.byref(pe))
    while ok:
        n = pe.szExeFile.decode("latin1").lower()
        if want:
            w = want.lower()
            if n == w or n.startswith(w.replace(".exe", "")):
                rf.append(pe.th32ProcessID)
        elif n.startswith("rf_online") and (n.endswith(".bin") or n.endswith(".exe")):
            rf.append(pe.th32ProcessID)
        elif n == "cerberus-games.exe":
            cerb.append(pe.th32ProcessID)
        ok = kernel32.Process32Next(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    names = rf or cerb
    if not names:
        return None
    for p in names:
        if is_wow64(p):
            return p
    return names[0]


def is_wow64(pid):
    h = kernel32.OpenProcess(0x0400 | 0x1000, False, pid)
    if not h:
        return False
    b = wintypes.BOOL(0)
    r = kernel32.IsWow64Process(h, ctypes.byref(b))
    kernel32.CloseHandle(h)
    return bool(r) and bool(b.value)


def _rpm(h, addr, size):
    buf = (ctypes.c_char * size)()
    got = ctypes.c_size_t(0)
    if not kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
        return None
    return buf.raw[:got.value]


def _rpm32(h, addr):
    b = _rpm(h, addr, 4)
    return _u32(b, 0) if b else 0


def _rpm_wstr(h, addr, chars):
    b = _rpm(h, addr, chars * 2)
    return b.decode("utf-16le", "replace") if b else ""


def _wpm(h, addr, data):
    n = len(data)
    buf = ctypes.create_string_buffer(bytes(data), n)
    got = ctypes.c_size_t(0)
    if not kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        return False
    return got.value == n


def peb32(h):
    """32-bit PEB address of the (WOW64) target, via NtQueryInformationProcess ProcessWow64Information."""
    buf = ctypes.c_void_p(0)
    ret = wintypes.DWORD(0)
    if ntdll.NtQueryInformationProcess(wintypes.HANDLE(h), 26, ctypes.byref(buf),
                                       ctypes.sizeof(ctypes.c_void_p), ctypes.byref(ret)) != 0:
        return 0
    return buf.value & 0xFFFFFFFF


def peb_modules(h):
    """Yield (base, name_lower) for every module in the target PEB (InLoadOrder), 32-bit."""
    peb = peb32(h)
    if not peb:
        return
    ldr = _rpm32(h, peb + 0x0C)
    if not ldr:
        return
    head = ldr + 0x0C          # &InLoadOrderModuleList
    cur = _rpm32(h, head)
    for _ in range(1024):
        if not cur or cur == head:
            break
        base = _rpm32(h, cur + 0x18)
        name_len = _rpm32(h, cur + 0x2C) & 0xFFFF
        name_ptr = _rpm32(h, cur + 0x30)
        name = _rpm_wstr(h, name_ptr, min(name_len // 2, 128)).lower()
        yield base, name
        cur = _rpm32(h, cur)


def peb_entry_for(h, base):
    """Address of the LDR_DATA_TABLE_ENTRY whose DllBase == base."""
    peb = peb32(h)
    if not peb:
        return 0
    ldr = _rpm32(h, peb + 0x0C)
    if not ldr:
        return 0
    head = ldr + 0x0C
    cur = _rpm32(h, head)
    for _ in range(1024):
        if not cur or cur == head:
            break
        if _rpm32(h, cur + 0x18) == base:
            return cur
        cur = _rpm32(h, cur)
    return 0


def resolve_export(h, module_name, func):
    """RVA-resolve an export in a target module by walking its PE exports."""
    base = 0
    for b, n in peb_modules(h):
        if n == module_name.lower():
            base = b
            break
    if not base:
        return 0
    dos = _rpm(h, base, 0x40)
    if not dos or dos[:2] != b"MZ":
        return 0
    pe = base + _u32(dos, 0x3C)
    hdr = _rpm(h, pe, 0x100)
    if not hdr or hdr[:4] != b"PE\0\0":
        return 0
    opt = 0x18
    magic = _u16(hdr, opt)
    dd = opt + (0x60 if magic == 0x10B else 0x70)
    exp_rva = _u32(hdr, dd + DIRECTORY_ENTRY_EXPORT * 8)
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


def unlink_peb(h, base):
    """Unlink the LDR_DATA_TABLE_ENTRY (InLoadOrder/InMemory/InInit) so Module32 misses the module."""
    e = peb_entry_for(h, base)
    if not e:
        return False
    # LIST_ENTRY at +0 (InLoad), +8 (InMemory), +0x10 (InInit)
    for off in (0x00, 0x08, 0x10):
        flink = _rpm32(h, e + off)
        blink = _rpm32(h, e + off + 4)
        if not flink or not blink:
            continue
        _wpm(h, blink, struct.pack("<I", flink))      # blink->Flink = flink
        _wpm(h, flink + 4, struct.pack("<I", blink))  # flink->Blink = blink
    return True


# ------------------------------------------------------------------ manual map core
class PE:
    def __init__(self, path):
        self.raw = open(path, "rb").read()
        b = self.raw
        if b[:2] != b"MZ":
            raise ValueError("not a PE (MZ)")
        self.pe = _u32(b, 0x3C)
        if b[self.pe:self.pe + 4] != b"PE\0\0":
            raise ValueError("not a PE (PE sig)")
        self.machine = _u16(b, self.pe + 4)
        if self.machine != 0x14C:
            raise ValueError("not i386 (machine 0x%04X); rebuild the DLL for x86" % self.machine)
        self.nsec = _u16(b, self.pe + 6)
        self.opt = self.pe + 0x18
        self.magic = _u16(b, self.opt)
        if self.magic != 0x10B:
            raise ValueError("not PE32 (magic 0x%04X)" % self.magic)
        self.image_base = _u32(b, self.opt + 0x1C)
        self.size_of_image = _u32(b, self.opt + 0x38)
        self.size_of_headers = _u32(b, self.opt + 0x3C)
        self.entry_rva = _u32(b, self.opt + 0x10)
        self.dd = self.opt + 0x60
        self.reloc_rva = _u32(b, self.dd + DIRECTORY_ENTRY_BASERELOC * 8)
        self.reloc_size = _u32(b, self.dd + DIRECTORY_ENTRY_BASERELOC * 8 + 4)
        self.import_rva = _u32(b, self.dd + DIRECTORY_ENTRY_IMPORT * 8)
        if not self.reloc_rva:
            raise ValueError("no base relocations - cannot manual map")

    def sections(self):
        sec = self.pe + 0x18 + _u16(self.raw, self.pe + 0x14)
        for i in range(self.nsec):
            s = sec + i * 40
            name = self.raw[s:s + 8].rstrip(b"\0")
            vsize = _u32(self.raw, s + 8)
            vaddr = _u32(self.raw, s + 12)
            rawsize = _u32(self.raw, s + 16)
            rawptr = _u32(self.raw, s + 20)
            chars = _u32(self.raw, s + 36)
            yield name, vaddr, vsize, rawptr, rawsize, chars

    def rva_to_off(self, rva):
        for name, vaddr, vsize, rawptr, rawsize, chars in self.sections():
            if vaddr <= rva < vaddr + max(vsize, rawsize):
                return rawptr + (rva - vaddr)
        if rva < self.size_of_headers:
            return rva
        return None

    def _prot(self, chars):
        if chars & IMAGE_SCN_MEM_EXECUTE:
            return PAGE_EXECUTE_READWRITE if chars & IMAGE_SCN_MEM_WRITE else PAGE_EXECUTE_READ
        if chars & IMAGE_SCN_MEM_WRITE:
            return PAGE_READWRITE
        return PAGE_READONLY


def manual_map(pid, dll_path, log=print, then_unlink=True):
    """Map the DLL into pid. RF_MAP selects the mode: 'image' (SEC_IMAGE -> MEM_IMAGE, default),
    'private' (VirtualAllocEx -> MEM_PRIVATE), or 'auto' (image, fall back to private)."""
    mode = os.environ.get("RF_MAP", "image").lower()
    if mode in ("image", "auto"):
        try:
            return _manual_map_image(pid, dll_path, log=log, then_unlink=then_unlink)
        except Exception as e:
            # Fall back to private only when the image entry did NOT run: if it did run, a second private
            # copy would install the hooks twice. _manual_map_image raises _EntryRan when the entry ran.
            if mode == "image" and not isinstance(e, _EntryRan):
                log("SEC_IMAGE map failed (%s), falling back to private" % e)
            else:
                log("SEC_IMAGE map failed after the entry ran (%s): not falling back (would double-hook)" % e)
                raise
    return _manual_map_private(pid, dll_path, log=log, then_unlink=then_unlink)


class _EntryRan(Exception):
    """Raised by _manual_map_image when the entry already ran (the image is mapped and may have hooked):
    the caller must NOT fall back to the private mapper (that would install a second copy)."""


# --- ntdll section helpers (for the SEC_IMAGE mode) ---
class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]


class _OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                ("ObjectName", ctypes.c_void_p), ("Attributes", wintypes.ULONG),
                ("SecurityDescriptor", ctypes.c_void_p), ("SecurityQualityOfService", ctypes.c_void_p)]


def _manual_map_image(pid, dll_path, log=print, then_unlink=True):
    """Map the DLL as a SEC_IMAGE section -> the region is MEM_MAPPED/MEM_IMAGE, like a real module.

    The kernel applies the base relocations itself (the image is mapped away from its preferred base), so
    we only fix the IAT. The IAT sits in a read-only file-backed page, so the image is made RW while
    patching and the real section rights are restored before the entry runs.
    """
    dll_path = os.path.abspath(dll_path)
    pe = PE(dll_path)
    try:
        open(os.path.join(os.path.dirname(dll_path), "BotCore.log"), "w").close()
    except OSError:
        pass

    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        h = kernel32.OpenProcess(0x043A, False, pid)
    if not h:
        raise OSError("OpenProcess failed err=%d" % ctypes.get_last_error())

    fh = None
    sec = wintypes.HANDLE()
    try:
        fh = kernel32.CreateFileA(dll_path.encode("ascii", "replace"), 0x80000000 | 0x00100000, 1, None, 3, 0, None)
        if not fh or fh == wintypes.HANDLE(-1).value:
            raise OSError("CreateFileA failed err=%d" % ctypes.get_last_error())

        ntdll.NtCreateSection.restype = ctypes.c_long
        ntdll.NtCreateSection.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG,
                                          ctypes.POINTER(_OBJECT_ATTRIBUTES), ctypes.c_void_p,
                                          wintypes.ULONG, wintypes.ULONG, wintypes.HANDLE]
        oa = _OBJECT_ATTRIBUTES(); oa.Length = ctypes.sizeof(oa)
        # SEC_IMAGE needs PAGE_READONLY (or PAGE_EXECUTE_READ); PAGE_READWRITE is STATUS_ACCESS_DENIED.
        st = ntdll.NtCreateSection(ctypes.byref(sec), 0xF001F, ctypes.byref(oa), None, 0x02, 0x1000000, wintypes.HANDLE(fh))
        if st != 0:
            raise OSError("NtCreateSection status 0x%08X" % (st & 0xFFFFFFFF))

        ntdll.NtMapViewOfSection.restype = ctypes.c_long
        ntdll.NtMapViewOfSection.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p),
                                             ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p,
                                             ctypes.POINTER(ctypes.c_size_t), wintypes.ULONG, wintypes.ULONG, wintypes.ULONG]
        base = ctypes.c_void_p(0); viewsize = ctypes.c_size_t(0)
        st = ntdll.NtMapViewOfSection(sec, h, ctypes.byref(base), 0, 0, None, ctypes.byref(viewsize), 2, 0, 0x04)
        if st != 0 or not base.value:
            raise OSError("NtMapViewOfSection status 0x%08X" % (st & 0xFFFFFFFF))
        base = base.value & 0xFFFFFFFF
        log("mapped at 0x%08X (SEC_IMAGE, MEM_IMAGE)" % base)

        # make the image writable while we patch the IAT, then restore the real rights
        kernel32.VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                              wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        old_p = wintypes.DWORD(0)
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(base), pe.size_of_image, PAGE_READWRITE, ctypes.byref(old_p))
        _fix_imports(h, base, pe, log)
        for name, vaddr, vsize, rawptr, rawsize, chars in pe.sections():
            if vsize:
                kernel32.VirtualProtectEx(h, ctypes.c_void_p(base + vaddr), vsize, pe._prot(chars), ctypes.byref(old_p))

        # params + entry stub (reuse the same helpers as the private mapper)
        path_bytes = dll_path.encode("ascii", "replace") + b"\0"
        path_addr = kernel32.VirtualAllocEx(h, None, len(path_bytes), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not path_addr:
            raise OSError("VirtualAllocEx(path) failed err=%d" % ctypes.get_last_error())
        if not _wpm(h, path_addr, path_bytes):
            raise OSError("writing the DLL path failed")
        entry = base + pe.entry_rva
        stub_addr = _write_entry_stub(h, base, entry, path_addr)
        mapped = False
        try:
            method = _run_entry(pid, h, stub_addr, path_addr, log)
            mapped = True
        except Exception as e:
            # the thread may have started DllMain (and installed hooks) before timing out: keep the image,
            # do not let the caller fall back to private (double copy).
            _write_base_file(pid, base, dll_path)   # so a later eject can still find and free it
            raise _EntryRan("entry did not confirm: %s" % e)
        finally:
            # the stub and the path buffer are only needed until DllMain has read the path. If the entry
            # timed out (raised) the game thread may STILL run in them: keep them (RF_KEEPSTUB semantics).
            if mapped and not os.environ.get("RF_KEEPSTUB"):
                kernel32.VirtualFreeEx(h, ctypes.c_void_p(stub_addr), 0, MEM_RELEASE)
                kernel32.VirtualFreeEx(h, ctypes.c_void_p(path_addr), 0, MEM_RELEASE)

        try:
            if then_unlink:
                ok = unlink_peb(h, base)
                log("PEB unlink: %s" % ("done (module not in module list)" if ok else "entry not found"))
            _hide_headers(h, base, pe, log)
        except Exception as e:
            # the entry already ran (hooks may be installed): do NOT unmap here (a second copy would
            # double-hook). Leave the mapped image in place and report the failure.
            log("post-entry step failed (%s): image stays mapped at 0x%08X (hooks may be installed)" % (e, base))
        _write_base_file(pid, base, dll_path)
        return base
    finally:
        if fh:
            kernel32.CloseHandle(fh)
        if sec:
            kernel32.CloseHandle(sec)
        kernel32.CloseHandle(h)


def _manual_map_private(pid, dll_path, log=print, then_unlink=True):
    dll_path = os.path.abspath(dll_path)
    pe = PE(dll_path)
    # clear the module log so the entry-run check (APC) is reliable
    try:
        open(os.path.join(os.path.dirname(dll_path), "BotCore.log"), "w").close()
    except OSError:
        pass
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        h = kernel32.OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
                                 PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ, False, pid)
    if not h:
        raise OSError("OpenProcess failed (run as admin) err=%d" % ctypes.get_last_error())

    try:
        # all addresses below are 32-bit in the target
        # 1. reserve at the preferred base if free
        base = 0
        probe = kernel32.VirtualAllocEx(h, ctypes.c_void_p(pe.image_base), pe.size_of_image,
                                        MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
        if probe:
            base = probe
            log("mapped at preferred base 0x%08X" % base)
        else:
            # find a free hole big enough
            base = _find_free_region(h, pe.size_of_image)
            if not base:
                base = kernel32.VirtualAllocEx(h, None, pe.size_of_image,
                                               MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
            if not base:
                raise OSError("VirtualAllocEx failed")
            base = base & 0xFFFFFFFF
            log("preferred base busy, mapped at 0x%08X (needs relocations)" % base)

        delta = (base - pe.image_base) & 0xFFFFFFFF

        # 2. write headers
        hdr = bytearray(pe.raw[:pe.size_of_headers])
        if not _wpm(h, base, hdr):
            raise OSError("writing headers failed")

        # 3. write sections (keep everything RWX until relocs/imports are done)
        sec_ranges = []
        for name, vaddr, vsize, rawptr, rawsize, chars in pe.sections():
            if rawsize == 0:
                sec_ranges.append((vaddr, vsize, chars))
                continue
            sec_data = pe.raw[rawptr:rawptr + rawsize]
            if not _wpm(h, base + vaddr, sec_data):
                raise OSError("writing section %s failed" % name.decode("latin1", "replace"))
            if vsize > rawsize:
                _wpm(h, base + vaddr + rawsize, b"\0" * (vsize - rawsize))
            sec_ranges.append((vaddr, vsize, chars))

        # 4. relocations
        if delta:
            _apply_relocs(h, base, pe, delta, log)

        # 5. imports
        _fix_imports(h, base, pe, log)

        # 5b. now apply the real section protections
        for vaddr, vsize, chars in sec_ranges:
            old = wintypes.DWORD(0)
            kernel32.VirtualProtectEx(h, ctypes.c_void_p(base + vaddr), vsize,
                                      pe._prot(chars), ctypes.byref(old))

        # 5c. sanity: the entry bytes must match the file (relocation/import bugs stay out)
        off = pe.rva_to_off(pe.entry_rva)
        if off is not None:
            want = pe.raw[off:off + 16]
            got = _rpm(h, base + pe.entry_rva, 16)
            if got and got != want:
                log("WARNING: entry bytes differ after map:\n  want %s\n  got  %s"
                    % (want.hex(), got.hex()))
            else:
                log("entry verified at 0x%08X" % (base + pe.entry_rva))

        # 6. params: DLL path (ASCII) for GetModuleFileNameA fallback + config path
        path_bytes = dll_path.encode("ascii", "replace") + b"\0"
        path_addr = kernel32.VirtualAllocEx(h, None, len(path_bytes), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not path_addr:
            raise OSError("VirtualAllocEx(path) failed err=%d" % ctypes.get_last_error())
        if not _wpm(h, path_addr, path_bytes):
            raise OSError("writing the DLL path failed")
        log("dll path at 0x%08X" % path_addr)

        # 7. run the module entry (DllMain). Preferred: a queued APC on an existing game thread
        #    (no CreateRemoteThread trace); fallbacks: NtCreateThreadEx, then CreateRemoteThread.
        entry = base + pe.entry_rva
        stub_addr = _write_entry_stub(h, base, entry, path_addr)
        mapped = False
        try:
            method = _run_entry(pid, h, stub_addr, path_addr, log)
            mapped = True
        finally:
            # the entry stub and the DLL-path buffer are only needed until DllMain has read the path (it runs
            # synchronously and _run_entry waited for it). Free them so the process has no extra private RX/RW
            # one-page regions that belong to the injector. On an entry timeout keep them (the thread may still
            # be running inside). RF_KEEPSTUB=1 keeps them for probing.
            if mapped and not os.environ.get("RF_KEEPSTUB"):
                if stub_addr:
                    kernel32.VirtualFreeEx(h, ctypes.c_void_p(stub_addr), 0, MEM_RELEASE)
                if path_addr:
                    kernel32.VirtualFreeEx(h, ctypes.c_void_p(path_addr), 0, MEM_RELEASE)
                log("freed entry stub + path buffer")

        try:
            if then_unlink:
                ok = unlink_peb(h, base)
                log("PEB unlink: %s" % ("done (module not in module list)" if ok else "entry not found"))

            # 8. headless: zero the DOS/PE headers so a memory scan cannot spot a PE that is not in the module list,
            #    and drop RWX (final section rights), keep only a tiny RX stub.
            _hide_headers(h, base, pe, log)
        except Exception as e:
            # the entry already ran (hooks may be installed): keep the mapped image (a remap would double-hook).
            log("post-entry step failed (%s): image stays mapped at 0x%08X (hooks may be installed)" % (e, base))

        _write_base_file(pid, base, dll_path)
        return base
    finally:
        kernel32.CloseHandle(h)


def _thread_ids(pid):
    """All thread ids of the process (best effort)."""
    TH32CS_SNAPTHREAD = 0x4

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                    ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long), ("dwFlags", wintypes.DWORD)]

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == INVALID_HANDLE_VALUE:
        return []
    te = THREADENTRY32(); te.dwSize = ctypes.sizeof(te)
    out = []
    ok = kernel32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            out.append(te.th32ThreadID)
        ok = kernel32.Thread32Next(snap, ctypes.byref(te))
    kernel32.CloseHandle(snap)
    return out


def _run_entry(pid, h, stub, param, log):
    """Run the mapped entry stub in the target. Returns the method name used.

    Raises OSError("entry thread did not finish in time ...") when the entry did not signal its thread within
    ENTRY_TIMEOUT_MS: the caller must then NOT free the stub / path buffers (the thread may still run in them).
    """
    method = os.environ.get("RF_METHOD", "auto").lower()   # auto = NtCreateThreadEx -> CreateRemoteThread
    ENTRY_TIMEOUT_MS = 8000
    WAIT_OBJECT_0 = 0
    WAIT_TIMEOUT = 0x102

    # NtCreateThreadEx first: quieter than the Win32 CreateRemoteThread (anti-cheats hook the Win32 call).
    if method in ("auto", "nt"):
        try:
            ntdll.NtCreateThreadEx.restype = ctypes.c_long
            ntdll.NtCreateThreadEx.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                               ctypes.c_void_p, wintypes.HANDLE, ctypes.c_void_p,
                                               ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t,
                                               ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p]
            th = wintypes.HANDLE()
            st = ntdll.NtCreateThreadEx(ctypes.byref(th), 0x1FFFFF, None, h, ctypes.c_void_p(stub),
                                        ctypes.c_void_p(param), 0, 0, 0, 0, None)
            if st == 0 and th:
                wr = kernel32.WaitForSingleObject(th, ENTRY_TIMEOUT_MS)
                kernel32.CloseHandle(th)
                if wr == WAIT_TIMEOUT:
                    raise OSError("entry thread did not finish within %d ms (NtCreateThreadEx)" % ENTRY_TIMEOUT_MS)
                log("entry run via NtCreateThreadEx")
                return "NtCreateThreadEx"
            log("NtCreateThreadEx status=0x%08X, falling back" % (st & 0xFFFFFFFF))
        except OSError:
            raise
        except Exception as e:
            log("NtCreateThreadEx entry failed: %s" % e)

    # CreateRemoteThread fallback
    tid = wintypes.DWORD(0)
    th = kernel32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(stub), ctypes.c_void_p(param), 0, ctypes.byref(tid))
    if not th:
        raise OSError("all entry methods failed, last err=%d" % ctypes.get_last_error())
    wr = kernel32.WaitForSingleObject(th, ENTRY_TIMEOUT_MS)
    kernel32.CloseHandle(th)
    if wr == WAIT_TIMEOUT:
        raise OSError("entry thread did not finish within %d ms (CreateRemoteThread)" % ENTRY_TIMEOUT_MS)
    log("entry run via CreateRemoteThread")
    return "CreateRemoteThread"


def _hide_headers(h, base, pe, log):
    """Zero the DOS/PE headers of the mapped image (a scan for 'MZ'/'PE' stops finding it)."""
    if os.environ.get("RF_NOHEAD"):
        return
    try:
        # zero the DOS header (first 0x40) and the PE signature (4 bytes at e_lfanew): a scanner that
        # looks for 'MZ' at 0 or 'PE\0\0' at e_lfanew finds neither. The rest of the header block stays
        # readable so nothing that walks sections/data-dirs breaks. e_lfanew sits in the (already zeroed)
        # DOS header, so read it in the file: it equals the RVA of the header block.
        _wpm(h, base, b"\0" * 0x40)
        pe_off = _u32(pe.raw, 0x3C)
        if 0 < pe_off < 0x400:
            _wpm(h, base + pe_off, b"\0" * 4)   # wipe 'PE\0\0'
        # the header page is not executed: drop it from RWX to plain read-only (fewer red flags)
        old = wintypes.DWORD(0)
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(base), 0x1000, PAGE_READONLY, ctypes.byref(old))
        log("DOS+PE headers zeroed")
    except Exception as e:
        log("header zeroing failed: %s" % e)


def _base_file(dll=None):
    """The .mapped.json next to <dll> (per profile), so several clients do not share one record."""
    if dll:
        return os.path.join(os.path.dirname(os.path.abspath(dll)), ".mapped.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", ".mapped.json")


def newest_dll(default):
    """Pick the newest of <default> and its .new sibling (the build falls back to that name when
    Bagnon.dll is locked by the game launcher)."""
    d = os.path.dirname(default)
    b = os.path.splitext(os.path.basename(default))[0]
    candidates = [default, os.path.join(d, b + ".new.dll")]
    best = None
    for c in candidates:
        try:
            if os.path.isfile(c):
                if best is None or os.path.getmtime(c) > os.path.getmtime(best):
                    best = c
        except OSError:
            pass
    return best or default


def _write_base_file(pid, base, dll=None):
    try:
        import json
        with open(_base_file(dll), "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "base": base}, f)
    except Exception:
        pass


def read_base_file(dll=None):
    try:
        import json
        with open(_base_file(dll), encoding="utf-8") as f:
            d = json.load(f)
        return d.get("pid"), d.get("base")
    except Exception:
        return None, None


def free_mapped(pid, base, log=print):
    """Free a previously mapped image (after the module removed its own hooks, BOT_CMD_EJECT).

    A SEC_IMAGE / MEM_IMAGE region (NtMapViewOfSection) must be released with NtUnmapViewOfSection;
    a MEM_PRIVATE region (VirtualAllocEx) with VirtualFreeEx. Try the matching one first, fall back.
    """
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION, False, pid)
    if not h:
        raise OSError("OpenProcess failed err=%d" % ctypes.get_last_error())
    try:
        try:
            ntdll.NtUnmapViewOfSection.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
            ntdll.NtUnmapViewOfSection.restype = ctypes.c_long
            st = ntdll.NtUnmapViewOfSection(h, ctypes.c_void_p(base))
            if st == 0:
                log("NtUnmapViewOfSection(0x%08X): ok" % base)
                return True
            log("NtUnmapViewOfSection(0x%08X): status 0x%08X, falling back" % (base, st & 0xFFFFFFFF))
        except Exception as e:
            log("NtUnmapViewOfSection failed: %s" % e)
        ok = kernel32.VirtualFreeEx(h, ctypes.c_void_p(base), 0, MEM_RELEASE)
        log("VirtualFreeEx(0x%08X): %s" % (base, "ok" if ok else "failed err=%d" % ctypes.get_last_error()))
        return bool(ok)
    finally:
        kernel32.CloseHandle(h)


def _find_free_region(h, size):
    addr = 0x10000000
    mbi = MEMORY_BASIC_INFORMATION32()
    while addr < 0x7F000000:
        if not kernel32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        if mbi.State == 0x10000:  # MEM_FREE
            region = mbi.RegionSize
            # align
            start = (addr + 0xFFFF) & ~0xFFFF
            if start >= addr and start + size <= addr + region:
                r = kernel32.VirtualAllocEx(h, ctypes.c_void_p(start), size,
                                            MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
                if r:
                    return r & 0xFFFFFFFF
        nxt = mbi.BaseAddress + mbi.RegionSize
        if nxt <= addr:
            break
        addr = nxt
    return 0


def _write_entry_stub(h, base, entry, param_addr):
    """Remote stub run by CreateRemoteThread(lpParameter = 0).

    DllMain(hinst, reason, reserved): push reserved, push reason, push hinst, call entry, ret.
    hinst = base (the mapped image), reason = DLL_PROCESS_ATTACH,
    reserved = param_addr (the DLL path, so the module can find its own folder).
    """
    stub = bytearray()
    stub += b"\x68" + struct.pack("<I", param_addr)     # push reserved (dll path)
    stub += b"\x6A\x01"                                  # push DLL_PROCESS_ATTACH
    stub += b"\x68" + struct.pack("<I", base)            # push hinst (mapped base)
    stub += b"\xE8\x00\x00\x00\x00"                      # placeholder, patched below
    stub += b"\xC3"                                      # ret
    addr = kernel32.VirtualAllocEx(h, None, len(stub), MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    call_at = addr + 12                                 # offset of the E8 byte (5+2+5 push bytes)
    struct.pack_into("<i", stub, 12 + 1, entry - (call_at + 5))
    _wpm(h, addr, bytes(stub))
    # stub never changes after this: drop it from RWX to RX
    old = wintypes.DWORD(0)
    kernel32.VirtualProtectEx(h, ctypes.c_void_p(addr), len(stub), PAGE_EXECUTE_READ, ctypes.byref(old))
    return addr


def _apply_relocs(h, base, pe, delta, log):
    off0 = pe.rva_to_off(pe.reloc_rva)
    if off0 is None:
        log("WARNING: reloc directory RVA 0x%X not in any section" % pe.reloc_rva)
        return
    data = pe.raw[off0:off0 + pe.reloc_size]
    off = 0
    count = 0
    while off + 8 <= len(data):
        page_rva = _u32(data, off)
        block_size = _u32(data, off + 4)
        if block_size < 8:
            break
        n = (block_size - 8) // 2
        for i in range(n):
            entry = _u16(data, off + 8 + i * 2)
            typ = entry >> 12
            rva = entry & 0xFFF
            if typ == 3:  # HIGHLOW
                a = base + page_rva + rva
                cur = _rpm32(h, a)
                new = (cur + delta) & 0xFFFFFFFF
                _wpm(h, a, struct.pack("<I", new))
                count += 1
        off += block_size
    log("relocations applied: %d (delta 0x%X)" % (count, delta))


def _fix_imports(h, base, pe, log):
    if not pe.import_rva:
        return
    desc = base + pe.import_rva
    dll_cache = {}
    total = 0
    while True:
        ilt = _rpm32(h, desc + 0)      # OriginalFirstThunk (names)
        name_rva = _rpm32(h, desc + 12)
        iat = _rpm32(h, desc + 16)     # FirstThunk
        if not name_rva and not ilt and not iat:
            break
        dll = _rpm(h, base + name_rva, 64).split(b"\0")[0].decode("latin1")
        dll_l = dll.lower()
        # find module base in target by name
        modbase = 0
        if dll_l in dll_cache:
            modbase = dll_cache[dll_l]
        else:
            for b, n in peb_modules(h):
                if n == dll_l:
                    modbase = b
                    break
            dll_cache[dll_l] = modbase
        if not modbase:
            log("WARNING: import dll '%s' not found in target" % dll)
        thunk = ilt if ilt else iat
        k = 0
        while True:
            val = _rpm32(h, base + thunk + k * 4)
            if val == 0:
                break
            if val & 0x80000000:  # ordinal
                fname = "ord_%d" % (val & 0xFFFF)
                faddr = _resolve_ordinal(h, modbase, val & 0xFFFF) if modbase else 0
            else:
                nb = _rpm(h, base + val, 64)
                fname = nb[2:].split(b"\0")[0].decode("latin1")
                faddr = resolve_export(h, dll_l, fname) if modbase else 0
            if not faddr and modbase:
                faddr = _resolve_ordinal_scan(h, modbase, fname)
            _wpm(h, base + iat + k * 4, struct.pack("<I", faddr & 0xFFFFFFFF))
            total += 1
            k += 1
        desc += 20
    log("imports resolved: %d" % total)


def _resolve_ordinal(h, modbase, ordinal):
    dos = _rpm(h, modbase, 0x40)
    if not dos:
        return 0
    pe = modbase + _u32(dos, 0x3C)
    hdr = _rpm(h, pe, 0x100)
    opt = 0x18
    dd = opt + 0x60
    exp_rva = _u32(hdr, dd + 0)
    exp = _rpm(h, modbase + exp_rva, 0x28)
    base_ord = _u32(exp, 0x10)
    funcs_rva = _u32(exp, 0x1C)
    n = _u32(exp, 0x14)
    idx = ordinal - base_ord
    if idx < 0 or idx >= n:
        return 0
    funcs = _rpm(h, modbase + funcs_rva, (idx + 1) * 4)
    return modbase + _u32(funcs, idx * 4)


def _resolve_ordinal_scan(h, modbase, fname):
    # fallback: only for "ord_N" style names -> resolve by export ordinal index
    if fname.startswith("ord_"):
        return _resolve_ordinal(h, modbase, int(fname[4:]))
    return 0


# ------------------------------------------------------------------ cli
def main():
    enable_debug_privilege()
    args = sys.argv[1:]
    want = None
    if "--exe" in args:
        i = args.index("--exe")
        want = args[i + 1]
        del args[i:i + 2]
    then_unlink = "--keep" not in args
    if "--keep" in args:
        args.remove("--keep")
    dll = args[0] if args else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "..", "build", "Bagnon.dll")
    pid = find_game_pid(want)
    if not pid:
        print("target not running (looked for %s)" % (want or "rf_online*/cerberus-games"))
        return 1
    print("pid = %d, manual-mapping %s" % (pid, dll))
    try:
        base = manual_map(pid, dll, then_unlink=then_unlink)
    except Exception as e:
        print("manual map failed: %s" % e)
        return 1
    print("mapped at 0x%08X%s" % (base, "" if then_unlink else " (PEB entry kept)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
