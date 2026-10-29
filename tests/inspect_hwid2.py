import os, sys, time, json, urllib.request, websocket
sys.path.insert(0, r"C:\SHARE\hwid")
import app
DISCOVER="http://127.0.0.1:9230/json"; LOG=r"C:\SHARE\hwid\logs\hwid_payload.jsonl"
try: os.remove(LOG)
except OSError: pass
m=app.AppModel.load(); p=m.find("3").to_dict()
p["user"]=""; p["password"]=""; p["game_exe"]=r"C:\SHARE\CERBERUS2\CERBERUS-GAMES.exe"; p["inject_children"]=False
p["_extra_args"]="--inspect-brk=9230"
pid,h,ht=app.start_profile(p,p["game_exe"],suspended=True)
print("pid",pid); app.resume(ht)
url=None
for i in range(100):
    try:
        data=json.loads(urllib.request.urlopen(DISCOVER,timeout=1).read().decode())
        if data: url=data[0].get("webSocketDebuggerUrl"); break
    except Exception: pass
    time.sleep(0.1)
print("inspector",url)
if url:
    ws=websocket.create_connection(url,suppress_origin=True)
    ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
    ws.send(json.dumps({"id":2,"method":"Debugger.enable"}))
    expr=r'''(() => { try { const req = process.mainModule ? process.mainModule.require.bind(process.mainModule) : (typeof require==='function'?require:null); if(!req) return 'no-require'; const fs=req('fs'); if(JSON.stringify.__hwidHooked) return 'already'; const orig=JSON.stringify; JSON.stringify=function(v){ try{ if(v&&v.args&&(v.args.hwid||v.args.hashes)) fs.appendFileSync('C:\\SHARE\\hwid\\logs\\hwid_payload.jsonl', orig(v)+'\n'); }catch(e){} return orig.apply(JSON,arguments); }; JSON.stringify.__hwidHooked=true; return 'ok'; }catch(e){ return 'ERR '+e.stack; } })()'''
    ws.send(json.dumps({"id":3,"method":"Runtime.evaluate","params":{"expression":expr,"returnByValue":True}}))
    ok=False
    for _ in range(40):
        try:
            msg=json.loads(ws.recv())
            print("CDP",msg.get("id"),msg.get("result",{}).get("result",{}).get("value") or msg.get("error") or msg.get("method"))
            if msg.get("id")==3: ok=True; break
        except Exception as e: print("err",e); break
    ws.send(json.dumps({"id":4,"method":"Debugger.resume"}))
    print("resumed",ok)
    time.sleep(2)
    ws.close()
time.sleep(15)
print("alive",app.alive(pid))
app.kill_pid(pid); time.sleep(1)
for q in app.find_pids_by_name("cerberus-games.exe"): app.kill_pid(q)
