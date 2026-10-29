import ctypes, sys, os, struct
from ctypes import wintypes

pid=int(sys.argv[1]); base=int(sys.argv[2],0); out=sys.argv[3]
k32=ctypes.WinDLL('kernel32',use_last_error=True)
psapi=ctypes.WinDLL('psapi',use_last_error=True)
h=k32.OpenProcess(0x0410,False,pid)
if not h: h=k32.OpenProcess(0x1010,False,pid)
print('h',h,'err',ctypes.get_last_error())
class MODULEINFO(ctypes.Structure):
    _fields_=[('lpBaseOfDll',ctypes.c_void_p),('SizeOfImage',wintypes.DWORD),('EntryPoint',ctypes.c_void_p)]
psapi.GetModuleInformation.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.POINTER(MODULEINFO),wintypes.DWORD]
mi=MODULEINFO()
ok=psapi.GetModuleInformation(h,ctypes.c_void_p(base),ctypes.byref(mi),ctypes.sizeof(mi))
print('GetModuleInformation',ok,'err',ctypes.get_last_error(),'size',hex(mi.SizeOfImage),'entry',hex(mi.EntryPoint or 0))
# read headers
k32.ReadProcessMemory.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
hdr=(ctypes.c_char*0x1000)()
got=ctypes.c_size_t()
k32.ReadProcessMemory(h,ctypes.c_void_p(base),hdr,0x1000,ctypes.byref(got))
print('hdr magic',hdr.raw[:2], 'got',got.value)
e_lfanew=struct.unpack_from('<I',hdr.raw,0x3c)[0]
print('e_lfanew',hex(e_lfanew))
size=mi.SizeOfImage
if e_lfanew+0x18+0x38 < 0x1000:
    opt=e_lfanew+0x18
    size=struct.unpack_from('<I',hdr.raw,opt+56)[0]
    ib=struct.unpack_from('<I',hdr.raw,opt+28)[0]
    print('SizeOfImage hdr',hex(size),'ImageBase',hex(ib))
size=min(max(size,0x1000),0x4000000)
buf=(ctypes.c_char*size)()
addr=base; off=0; chunk=0x100000
while off<size:
    n=min(chunk,size-off); g=ctypes.c_size_t()
    if not k32.ReadProcessMemory(h,ctypes.c_void_p(addr+off),ctypes.byref(buf,off),n,ctypes.byref(g)):
        print('read fail at',hex(addr+off),'err',ctypes.get_last_error()); break
    off+=g.value
    if g.value==0: break
open(out,'wb').write(buf.raw[:off])
print('wrote',out,off)
k32.CloseHandle(h)
