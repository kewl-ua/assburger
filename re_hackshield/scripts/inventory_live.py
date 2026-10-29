import ctypes, sys, os, struct, json, time
from ctypes import wintypes

pid = int(sys.argv[1])
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
if not h:
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
print("OpenProcess:", h, "err", ctypes.get_last_error())
if not h: sys.exit(1)

psapi.EnumProcessModulesEx.argtypes=[wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
psapi.EnumProcessModulesEx.restype=wintypes.BOOL
psapi.GetModuleFileNameExW.argtypes=[wintypes.HANDLE, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD]

mods = (ctypes.c_void_p * 4096)()
need = wintypes.DWORD()
ok = psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 0x03)
print("EnumProcessModulesEx:", ok, "need", need.value, "err", ctypes.get_last_error())
n = need.value // ctypes.sizeof(ctypes.c_void_p)
print("MODULES", n)
buf = ctypes.create_unicode_buffer(1024)
for i in range(n):
    base = mods[i] or 0
    psapi.GetModuleFileNameExW(h, ctypes.c_void_p(base), buf, 1024)
    print("%08X %-70s" % (base & 0xffffffff, buf.value))

# threads
TH32CS_SNAPTHREAD=0x4
class THREADENTRY32(ctypes.Structure):
    _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('th32ThreadID',wintypes.DWORD),('th32OwnerProcessID',wintypes.DWORD),('tpBasePri',wintypes.LONG),('tpDeltaPri',wintypes.LONG),('dwFlags',wintypes.DWORD)]
th=k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0)
te=THREADENTRY32(); te.dwSize=ctypes.sizeof(te)
thr=[]
if k32.Thread32First(th, ctypes.byref(te)):
    while True:
        if te.th32OwnerProcessID==pid: thr.append(te.th32ThreadID)
        if not k32.Thread32Next(th, ctypes.byref(te)): break
k32.CloseHandle(th)
print("THREADS",len(thr),thr)

# memory regions
class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_=[('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),('AllocationProtect',wintypes.DWORD),('RegionSize',ctypes.c_size_t),('State',wintypes.DWORD),('Protect',wintypes.DWORD),('Type',wintypes.DWORD)]
k32.VirtualQueryEx.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.POINTER(MEMORY_BASIC_INFORMATION),ctypes.c_size_t]
k32.VirtualQueryEx.restype=ctypes.c_size_t
addr=0; regs=[]
while addr < 0x80000000:
    mbi=MEMORY_BASIC_INFORMATION()
    r=k32.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(mbi),ctypes.sizeof(mbi))
    if not r: break
    regs.append((mbi.BaseAddress or 0, mbi.RegionSize, mbi.State, mbi.Protect, mbi.Type))
    addr = (mbi.BaseAddress or 0) + mbi.RegionSize
print("REGIONS",len(regs))
for b,sz,st,pr,ty in regs:
    if st==0x1000: # committed
        print("  %08X-%08X size=%08X prot=%08X type=%08X" % (b,b+sz,sz,pr,ty))

# search strings
k32.ReadProcessMemory.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype=wintypes.BOOL
needles=[b'VphwID', b'[HACKSHIELD] Already Hooked', b'[HACKSHIELD] Detect AutoMouse', b'HackShield Init Ok', b'HackShield Svr Init Ok', b'\\EHSvc.dll', b'SOFTWARE\\AHNLAB\\IOU\\HackShield', b'HSUpdate.exe', b'CNetMsgProcessor_HackShield', b'HackShield']
one=bytearray(0x100000)
hits={}
for b,sz,st,pr,ty in regs:
    if st!=0x1000 or not (pr & 0x02): continue  # readable
    off=0
    while off<sz:
        chunk=min(0x100000, sz-off)
        got=ctypes.c_size_t()
        if k32.ReadProcessMemory(h, ctypes.c_void_p(b+off), (ctypes.c_char*chunk).from_buffer(one), chunk, ctypes.byref(got)) and got.value:
            data=bytes(one[:got.value])
            for nd in needles:
                j=0
                while True:
                    j=data.find(nd,j)
                    if j<0: break
                    hits.setdefault(nd,[]).append(b+off+j)
                    j+=1
        off+=chunk
print("STRING HITS")
for nd,addrs in hits.items():
    print(nd.decode('latin1'), len(addrs), [hex(a) for a in addrs[:20]])
k32.CloseHandle(h)
