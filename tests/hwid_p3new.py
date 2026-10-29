import os,sys,time,json,urllib.request,websocket
sys.path.insert(0,r"C:\SHARE\hwid")
import app
DISCOVER="http://127.0.0.1:9238/json"; LOG=r"C:\SHARE\hwid\logs\hwid_payload_p3new.jsonl"; STATUS=r"C:\SHARE\hwid\logs\hwid_p3new_status.txt"
for f in (LOG,STATUS):
    try: os.remove(f)
    except OSError: pass
m=app.AppModel.load(); p=m.find("3").to_dict()
p["user"]=""; p["password"]=""; p["inject_children"]=False; p["_extra_args"]="--inspect=9238"
pid,h,ht=app.start_profile(p,p["game_exe"],suspended=True); open(STATUS,'w').write("pid %d exe %s\n"%(pid,p["game_exe"])); app.resume(ht)
url=None
for i in range(100):
    try:
        d=json.loads(urllib.request.urlopen(DISCOVER,timeout=1).read().decode())
        if d: url=d[0].get("webSocketDebuggerUrl"); break
    except Exception: pass
    time.sleep(.1)
open(STATUS,'a').write("inspector %s\n"%url)
if url:
    ws=websocket.create_connection(url,suppress_origin=True); ws.settimeout(5)
    ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
    expr=r'''(() => { try { const req=process.mainModule?process.mainModule.require.bind(process.mainModule):require; const fs=req('fs'); if(JSON.stringify.__h3) return 'already'; const orig=JSON.stringify; JSON.stringify=function(v){ try{ if(v&&v.args&&(v.args.hwid||v.args.hashes)) fs.appendFileSync('C:\\SHARE\\hwid\\logs\\hwid_payload_p3new.jsonl', orig(v)+'\n'); }catch(e){} return orig.apply(JSON,arguments); }; JSON.stringify.__h3=true; return 'ok'; }catch(e){return 'ERR '+e.stack;} })()'''
    ws.send(json.dumps({"id":2,"method":"Runtime.evaluate","params":{"expression":expr,"returnByValue":True}}))
    for _ in range(20):
        try:
            msg=json.loads(ws.recv())
            if msg.get("id")==2: open(STATUS,'a').write("hook %s\n"%msg.get("result",{}).get("result",{}).get("value")); break
        except Exception: break
    ws.close()
time.sleep(12)
print(open(STATUS).read()); print("--- log ---"); print(open(LOG).read() if os.path.exists(LOG) else "(none)")
print("alive", app.alive(pid))
app.kill_pid(pid); time.sleep(1)
for q in app.find_pids_by_name("cerberus-games.exe"):
    if q != 18116: app.kill_pid(q)
