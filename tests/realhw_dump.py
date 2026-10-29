import ctypes, os, json, subprocess, sys
from ctypes import wintypes
k = ctypes.WinDLL("kernel32", use_last_error=True)
ip = ctypes.WinDLL("iphlpapi", use_last_error=True)
def vol():
    s=wintypes.DWORD(0)
    k.GetVolumeInformationW.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.DWORD),wintypes.LPWSTR,wintypes.DWORD]
    if k.GetVolumeInformationW("C:\\",None,0,ctypes.byref(s),None,None,None,0): return "%08X"%s.value
    return ""
def name():
    b=ctypes.create_unicode_buffer(256); n=wintypes.DWORD(256)
    if k.GetComputerNameW(b,ctypes.byref(n)): return b.value
    return os.environ.get("COMPUTERNAME","")
def guid():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as kh:
            return winreg.QueryValueEx(kh,"MachineGuid")[0]
    except Exception as e: return "ERR:%s"%e
def macs():
    out=[]
    try:
        class A(ctypes.Structure): pass
        A._fields_=[("p",ctypes.POINTER(A)),("i",wintypes.DWORD),("an",ctypes.c_char*260),("d",ctypes.c_char*132),("al",wintypes.UINT),("ad",ctypes.c_ubyte*8)]
        sz=wintypes.ULONG(0); ip.GetAdaptersInfo(None,ctypes.byref(sz))
        buf=(ctypes.c_ubyte*sz.value)()
        if ip.GetAdaptersInfo(ctypes.cast(buf,ctypes.c_void_p),ctypes.byref(sz))==0:
            p=ctypes.cast(buf,ctypes.POINTER(A))
            while p:
                a=p.contents
                out.append({"desc":a.d.decode("latin1","replace"),"mac":":".join("%02X"%a.ad[i] for i in range(min(a.al,6)))})
                p=a.p
    except Exception as e: out.append({"err":str(e)})
    return out
def ram():
    class M(ctypes.Structure):
        _fields_=[("l",wintypes.DWORD),("load",wintypes.DWORD),("total",ctypes.c_ulonglong),("avail",ctypes.c_ulonglong),("tp",ctypes.c_ulonglong),("ap",ctypes.c_ulonglong),("tv",ctypes.c_ulonglong),("av",ctypes.c_ulonglong),("ae",ctypes.c_ulonglong)]
    m=M(); m.l=ctypes.sizeof(m); k.GlobalMemoryStatusEx(ctypes.byref(m)); return m.total//(1024*1024)
def wmi(cls,prop):
    try:
        return subprocess.run(["powershell","-nop","-c","(Get-CimInstance %s).%s"%(cls,prop)],capture_output=True,text=True,timeout=25).stdout.strip()
    except Exception: return ""
d={"computer":name(),"volume_serial":vol(),"machine_guid":guid(),"macs":macs(),"ram_mb":ram(),
   "bios":{ "vendor":wmi("Win32_BIOS","Manufacturer"),"version":wmi("Win32_BIOS","SMBIOSBIOSVersion"),"serial":wmi("Win32_BIOS","SerialNumber")},
   "board":{"mfr":wmi("Win32_BaseBoard","Manufacturer"),"product":wmi("Win32_BaseBoard","Product"),"serial":wmi("Win32_BaseBoard","SerialNumber")},
   "system":{"mfr":wmi("Win32_ComputerSystem","Manufacturer"),"product":wmi("Win32_ComputerSystem","Model")},
   "cpu":wmi("Win32_Processor","Name"),"uuid":wmi("Win32_ComputerSystemProduct","UUID")}
print(json.dumps(d,ensure_ascii=False,indent=2))
