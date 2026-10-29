import os, sys, time
sys.path.insert(0, r"C:\SHARE\hwid")
os.environ["NODE_OPTIONS"] = "--require=C:\\SHARE\\hwid\\tests\\node_hook.js"
os.environ["HWID_TAG"] = "p3"
os.environ["HWID_LOG"] = "C:\\SHARE\\hwid\\logs\\hwid_payload.jsonl"
import app
m=app.AppModel.load(); p=m.find("3").to_dict()
p["user"]=""; p["password"]=""; p["game_exe"]=r"C:\SHARE\CERBERUS2\CERBERUS-GAMES.exe"; p["inject_children"]=False
pid,h,ht=app.start_profile(p,p["game_exe"],suspended=True)
print("pid",pid,"relay",p.get("_relay_port"))
app.resume(ht)
time.sleep(12)
print("alive",app.alive(pid))
app.kill_pid(pid); time.sleep(1)
for q in app.find_pids_by_name("cerberus-games.exe"): app.kill_pid(q)
