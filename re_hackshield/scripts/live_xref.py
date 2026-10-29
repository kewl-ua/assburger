import ctypes, sys, struct
from ctypes import wintypes
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

pid=int(sys.argv[1]); needle=bytes.fromhex(sys.argv[2])
k32=ctypes.WinDLL('kernel32',use_last_error=True)
h=k32.OpenProcess(0x0410,False,pid)
if not h: h=k32.OpenProcess(0x1010,False,pid)
class MBI(ctypes.Structure):
    _fields_=[('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),('AllocationProtect',wintypes.DWORD),('RegionSize',ctypes.c_size_t),('State',wintypes.DWORD),('Protect',wintypes.DWORD),('Type',wintypes.DWORD)]
k32.VirtualQueryEx.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.POINTER(MBI),ctypes.c_size_t]
k32.ReadProcessMemory.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype=wintypes.BOOL
def rd(addr,n):
    b=(ctypes.c_char*n)(); g=ctypes.c_size_t()
    if k32.ReadProcessMemory(h,ctypes.c_void_p(addr),b,n,ctypes.byref(g)) and g.value:
        return bytes(b[:g.value])
    return b''
md=Cs(CS_ARCH_X86,CS_MODE_32)
addr=0; hits=[]
while addr<0x80000000:
    m=MBI(); r=k32.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m))
    if not r: break
    if m.State==0x1000 and (m.Protect & 0x10 or m.Protect & 0x20 or m.Protect & 0x40) and (m.Protect & 0x02):
        data=rd(m.BaseAddress or 0, m.RegionSize)
        j=0
        while True:
            j=data.find(needle,j)
            if j<0: break
            hits.append((m.BaseAddress or 0)+j)
            j+=1
    addr=(m.BaseAddress or 0)+m.RegionSize
print('hits',len(hits),[hex(x) for x in hits[:30]])
for a in hits[:10]:
    start=a-24; code=rd(start,80)
    print('--- around %08X ---'%a)
    for ins in md.disasm(code,start):
        mark='>>' if ins.address<=a<ins.address+ins.size else '  '
        print('%s %08X: %-20s %s %s'%(mark,ins.address,ins.bytes.hex(),ins.mnemonic,ins.op_str))
