import ctypes, time, sys
from ctypes import wintypes
sys.path.insert(0, r"C:\SHARE\hwid")
import app
user32=ctypes.WinDLL("user32",use_last_error=True)
def win(pid):
    res=[]; CB=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def cb(h,lp):
        if user32.IsWindowVisible(h):
            p=wintypes.DWORD(0); user32.GetWindowThreadProcessId(h,ctypes.byref(p))
            if p.value==pid:
                b=ctypes.create_unicode_buffer(256); user32.GetWindowTextW(h,b,256)
                if b.value: res.append(b.value)
        return True
    user32.EnumWindows(CB(cb),0); return res
m=app.AppModel.load(); p=m.find("3").to_dict()
p["user"]=""; p["password"]=""; p["game_exe"]=r"C:\SHARE\CERBERUS2\CERBERUS-GAMES.exe"; p["inject_children"]=False
pid,h,ht=app.start_profile(p,p["game_exe"],suspended=True)
print("pid",pid,"relay",p.get("_relay_port"),"net",p.get("_netdll"),"full",p["_dll"])
app.resume(ht)
for _ in range(80):
    if win(pid): break
    time.sleep(0.25)
time.sleep(3.0)
app.inject_dll(pid,p["_dll"],h); print("NEW full injected (no net preload)")
for i in range(12):
    time.sleep(1); print("t=%ds alive=%s win=%s" % (i+1, app.alive(pid), win(pid)[:1]))
app.kill_pid(pid); time.sleep(1)
for q in app.find_pids_by_name("cerberus-games.exe"): app.kill_pid(q)
