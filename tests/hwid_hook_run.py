import os, sys, time, json, urllib.request, websocket
sys.path.insert(0, r"C:\SHARE\hwid")
import app
DISCOVER="http://127.0.0.1:9235/json"; LOG=r"C:\SHARE\hwid\logs\hwid_payload.jsonl"; STATUS=r"C:\SHARE\hwid\logs\hwid_hook_status.txt"
for f in (LOG, STATUS):
    try: os.remove(f)
    except OSError: pass
m=app.AppModel.load(); p=m.find("3").to_dict()
p["user"]=""; p["password"]=""; p["game_exe"]=r"C:\SHARE\CERBERUS2\CERBERUS-GAMES.exe"; p["inject_children"]=False
p["_extra_args"]="--inspect=9235"
pid,h,ht=app.start_profile(p,p["game_exe"],suspended=True)
open(STATUS,'w').write("started pid=%d\n" % pid)
app.resume(ht)
url=None
for i in range(100):
    try:
        data=json.loads(urllib.request.urlopen(DISCOVER,timeout=1).read().decode())
        if data: url=data[0].get("webSocketDebuggerUrl"); break
    except Exception: pass
    time.sleep(0.1)
open(STATUS,'a').write("inspector=%s\n" % url)
if url:
    ws=websocket.create_connection(url,suppress_origin=True); ws.settimeout(5)
    ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
    expr=r'''(() => { try { const req = process.mainModule ? process.mainModule.require.bind(process.mainModule) : require; const fs=req('fs'); if(JSON.stringify.__hwidHooked) return 'already'; const orig=JSON.stringify; JSON.stringify=function(v){ try{ if(v&&v.args&&(v.args.hwid||v.args.hashes)) fs.appendFileSync('C:\\SHARE\\hwid\\logs\\hwid_payload.jsonl', orig(v)+'\n'); }catch(e){} return orig.apply(JSON,arguments); }; JSON.stringify.__hwidHooked=true; return 'ok'; }catch(e){ return 'ERR '+e.stack; } })()'''
    ws.send(json.dumps({"id":2,"method":"Runtime.evaluate","params":{"expression":expr,"returnByValue":True}}))
    hook='?'
    for _ in range(20):
        try:
            msg=json.loads(ws.recv())
            if msg.get("id")==2:
                hook=msg.get("result",{}).get("result",{}).get("value"); break
        except Exception as e: hook='recv '+str(e); break
    open(STATUS,'a').write("hook=%s\n" % hook)
    try:
        ws.send(json.dumps({"id":3,"method":"Runtime.evaluate","params":{"expression":"JSON.stringify({args:{hwid:'TEST',hashes:[]}}); 'tested'","returnByValue":True}}))
        time.sleep(0.5)
    except Exception: pass
    ws.close()
open(STATUS,'a').write("sleeping; log in to the launcher window\n")
time.sleep(900)
