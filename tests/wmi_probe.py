import sys, time, psutil
from ctypes import wintypes
sys.path.insert(0, r"C:\SHARE\hwid")
import app
m=app.AppModel.load(); p=m.find("3").to_dict()
p["user"]=""; p["password"]=""; p["game_exe"]=r"C:\SHARE\CERBERUS2\CERBERUS-GAMES.exe"; p["inject_children"]=True
t0=time.time()
pid,h,ht=app.start_profile(p,p["game_exe"],suspended=True)
app.resume(ht)
print("launcher pid", pid, "relay", p.get("_relay_port"))
seen=set()
for i in range(60):
    for pr in psutil.process_iter(['pid','name','ppid','cmdline','create_time']):
        try:
            nm=(pr.info['name'] or '').lower()
            if nm in ('powershell.exe','wmic.exe','cmd.exe','wmiprvse.exe','conhost.exe'):
                ct=pr.info['create_time'] or 0
                if ct >= t0-2 and pr.info['pid'] not in seen:
                    seen.add(pr.info['pid'])
                    print("PROC", pr.info['pid'], nm, "parent", pr.info['ppid'], "cmd", (pr.info['cmdline'] or [])[:12])
        except Exception: pass
    time.sleep(0.3)
print("seen", len(seen))
app.kill_pid(pid); time.sleep(1)
for q in app.find_pids_by_name("cerberus-games.exe"): app.kill_pid(q)
