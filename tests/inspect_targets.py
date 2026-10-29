import os, sys, time, json, urllib.request
sys.path.insert(0, r"C:\SHARE\hwid")
import app
m=app.AppModel.load(); p=m.find("3").to_dict()
p["user"]=""; p["password"]=""; p["game_exe"]=r"C:\SHARE\CERBERUS2\CERBERUS-GAMES.exe"; p["inject_children"]=False
p["_extra_args"]="--inspect-brk=9231"
pid,h,ht=app.start_profile(p,p["game_exe"],suspended=True)
print("pid",pid); app.resume(ht)
for i in range(60):
    try:
        data=json.loads(urllib.request.urlopen("http://127.0.0.1:9231/json",timeout=1).read().decode())
        print(json.dumps(data,indent=2)[:3000]); break
    except Exception as e: pass
    time.sleep(0.2)
app.kill_pid(pid); time.sleep(1)
for q in app.find_pids_by_name("cerberus-games.exe"): app.kill_pid(q)
