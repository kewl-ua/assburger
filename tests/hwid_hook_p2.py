import os, sys, time, json, urllib.request, websocket
sys.path.insert(0, r"C:\SHARE\hwid")
import app
DISCOVER="http://127.0.0.1:9236/json"; LOG=r"C:\Users\Public\hwid_payload_p2.jsonl"; STATUS=r"C:\SHARE\hwid\logs\hwid_hook_status_p2.txt"
for f in (LOG, STATUS):
    try: os.remove(f)
    except OSError: pass
m=app.AppModel.load(); p=m.find("2").to_dict()
p["game_exe"]=r"C:\SHARE\CERBERUS2\CERBERUS-GAMES.exe"; p["inject_children"]=True
p["_extra_args"]="--inspect=9236"
open(STATUS,'w',encoding='utf-8').write("profile2 user=%r exe=%s\n" % (p.get("user"), p.get("game_exe")))
try:
    pid,h,ht=app.start_profile(p,p["game_exe"],suspended=True)
    open(STATUS,'a',encoding='utf-8').write("started pid=%d relay=%s\n" % (pid, p.get("_relay_port")))
    app.resume(ht)
except Exception as e:
    open(STATUS,'a',encoding='utf-8').write("start failed: %r\n" % (e,)); raise
url=None
for i in range(100):
    try:
        data=json.loads(urllib.request.urlopen(DISCOVER,timeout=1).read().decode())
        if data: url=data[0].get("webSocketDebuggerUrl"); break
    except Exception: pass
    time.sleep(0.1)
open(STATUS,'a',encoding='utf-8').write("inspector=%s\n" % url)
if url:
    ws=websocket.create_connection(url,suppress_origin=True); ws.settimeout(5)
    ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
    expr=r'''(() => { try { const req = process.mainModule ? process.mainModule.require.bind(process.mainModule) : require; const fs=req('fs'); if(JSON.stringify.__hwidHooked) return 'already'; const orig=JSON.stringify; JSON.stringify=function(v){ try{ if(v&&v.args&&(v.args.hwid||v.args.hashes)) fs.appendFileSync('C:\\Users\\Public\\hwid_payload_p2.jsonl', orig(v)+'\n'); }catch(e){} return orig.apply(JSON,arguments); }; JSON.stringify.__hwidHooked=true; return 'ok'; }catch(e){ return 'ERR '+e.stack; } })()'''
    ws.send(json.dumps({"id":2,"method":"Runtime.evaluate","params":{"expression":expr,"returnByValue":True}}))
    hook='?'
    for _ in range(20):
        try:
            msg=json.loads(ws.recv())
            if msg.get("id")==2:
                hook=msg.get("result",{}).get("result",{}).get("value"); break
        except Exception as e: hook='recv '+str(e); break
    open(STATUS,'a',encoding='utf-8').write("hook=%s\n" % hook)
    try:
        ws.send(json.dumps({"id":3,"method":"Runtime.evaluate","params":{"expression":"JSON.stringify({args:{hwid:'TEST2',hashes:[]}}); 'tested'","returnByValue":True}}))
        time.sleep(0.5)
    except Exception: pass
    ws.close()
open(STATUS,'a',encoding='utf-8').write("sleeping; log in to the profile-2 launcher window\n")
time.sleep(900)
