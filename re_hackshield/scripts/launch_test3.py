import ctypes, time, sys, os, subprocess
from ctypes import wintypes
sys.path.insert(0, r"C:\SHARE\hwid")
import app
user32 = ctypes.WinDLL("user32", use_last_error=True)

def wins(pid):
    res=[]
    CB=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def cb(hwnd,lp):
        if user32.IsWindowVisible(hwnd):
            p=wintypes.DWORD(0); user32.GetWindowThreadProcessId(hwnd,ctypes.byref(p))
            if p.value==pid:
                b=ctypes.create_unicode_buffer(256); user32.GetWindowTextW(hwnd,b,256)
                if b.value: res.append(b.value)
        return True
    user32.EnumWindows(CB(cb),0); return res

m=app.AppModel.load(); p=m.find("3").to_dict()
p["user"]=""; p["password"]=""; p["game_exe"]=r"C:\SHARE\CERBERUS3\CERBERUS-GAMES.exe"; p["inject_children"]=False
print("starting profile3", p.get("proxy"), flush=True)
pid,h,ht=app.start_profile(p,p["game_exe"],suspended=False)
print("launcher pid",pid,"relay",p.get("_relay_port"),"net",p.get("_netdll"),flush=True)
t0=time.time(); seen={}
while time.time()-t0<75:
    procs=subprocess.run(['powershell','-NoProfile','-Command',"Get-CimInstance Win32_Process | Where-Object {$_.Name -match 'RF_Online|CERBERUS'} | ForEach-Object { '{0}|{1}|{2}|{3}' -f $_.ProcessId,$_.ParentProcessId,$_.Name,$_.ExecutablePath }"],capture_output=True,text=True).stdout
    for line in procs.splitlines():
        if line.strip() and line not in seen:
            seen[line]=time.time()-t0
            print("proc +%.1fs %s"%(time.time()-t0,line),flush=True)
            try:
                q=int(line.split('|')[0]); print("   wins",wins(q),flush=True)
            except Exception: pass
    time.sleep(2)
print("done watch",flush=True)
print("launcher alive",app.alive(pid),flush=True)
