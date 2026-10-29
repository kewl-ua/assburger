import ctypes, sys, struct
from ctypes import wintypes
pid=int(sys.argv[1])
needles=[]
for a in sys.argv[2:]:
    if a.startswith('hex:'):
        needles.append((a, bytes.fromhex(a[4:])))
    elif a.startswith('u16:'):
        needles.append((a, a[4:].encode('utf-16le')))
    else:
        needles.append((a, a.encode('latin1')))
k32=ctypes.WinDLL('kernel32',use_last_error=True)
h=k32.OpenProcess(0x0410,False,pid)
if not h: h=k32.OpenProcess(0x1010,False,pid)
print('h',h,'err',ctypes.get_last_error())
class MBI(ctypes.Structure):
    _fields_=[('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),('AllocationProtect',wintypes.DWORD),('RegionSize',ctypes.c_size_t),('State',wintypes.DWORD),('Protect',wintypes.DWORD),('Type',wintypes.DWORD)]
k32.VirtualQueryEx.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.POINTER(MBI),ctypes.c_size_t]
k32.ReadProcessMemory.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
addr=0; res={}
buf=(ctypes.c_char*0x100000)()
while addr<0x80000000:
    m=MBI(); r=k32.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m))
    if not r: break
    if m.State==0x1000 and (m.Protect & 0x02):
        off=0
        while off<m.RegionSize:
            n=min(0x100000,m.RegionSize-off); got=ctypes.c_size_t()
            if k32.ReadProcessMemory(h,ctypes.c_void_p((m.BaseAddress or 0)+off),buf,n,ctypes.byref(got)) and got.value:
                data=bytes(buf[:got.value])
                for name,nd in needles:
                    j=0
                    while True:
                        j=data.find(nd,j)
                        if j<0: break
                        res.setdefault(name,[]).append((m.BaseAddress or 0)+off+j)
                        j+=1
            off+=n
    addr=(m.BaseAddress or 0)+m.RegionSize
for name,nd in needles:
    a=res.get(name,[])
    print('%-45s %d %s' % (name,len(a),[hex(x) for x in a[:15]]))
k32.CloseHandle(h)
