import os, sys, time, json, urllib.request, websocket
sys.path.insert(0, r"C:\SHARE\hwid")
import app
DISCOVER="http://127.0.0.1:9232/json"; LOG=r"C:\SHARE\hwid\logs\hwid_payload.jsonl"
try: os.remove(LOG)
except OSError: pass
m=app.AppModel.load(); p=m.find("3").to_dict()
p["user"]=""; p["password"]=""; p["game_exe"]=r"C:\SHARE\CERBERUS2\CERBERUS-GAMES.exe"; p["inject_children"]=False
p["_extra_args"]="--inspect-brk=9232"
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
    ws=websocket.create_connection(url,suppress_origin=True); ws.settimeout(3)
    ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
    ws.send(json.dumps({"id":2,"method":"Debugger.enable"}))
    ws.send(json.dumps({"id":3,"method":"Debugger.setBreakpointByUrl","params":{"lineNumber":0,"urlRegex":".*build/electron\\.js.*"}}))
    ws.send(json.dumps({"id":4,"method":"Debugger.resume"}))
    expr=r'''(() => { try { const req = process.mainModule ? process.mainModule.require.bind(process.mainModule) : require; const fs=req('fs'); if(JSON.stringify.__hwidHooked) return 'already'; const orig=JSON.stringify; JSON.stringify=function(v){ try{ if(v&&v.args&&(v.args.hwid||v.args.hashes)) fs.appendFileSync('C:\\SHARE\\hwid\\logs\\hwid_payload.jsonl', orig(v)+'\n'); }catch(e){} return orig.apply(JSON,arguments); }; JSON.stringify.__hwidHooked=true; return 'ok'; }catch(e){ return 'ERR '+e.stack; } })()'''
    paused=False
    for _ in range(120):
        try:
            msg=json.loads(ws.recv())
        except Exception as e:
            print("recv timeout",e); break
        mname=msg.get("method"); mid=msg.get("id")
        if mid: print("CDP",mid,msg.get("result") or msg.get("error"))
        if mname:
            print("EV",mname, (msg.get("params",{}).get("reason") or msg.get("params",{}).get("url") or "")[:120])
            if mname=="Debugger.paused":
                paused=True
                ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":expr,"returnByValue":True}}))
                # wait for eval result then resume
            elif mname=="Debugger.scriptParsed" and "electron.js" in (msg.get("params",{}).get("url") or ""):
                print("SCRIPT",msg.get("params",{}).get("url"))
        if mid==10:
            print("HOOK",msg.get("result",{}).get("result",{}).get("value"))
            ws.send(json.dumps({"id":11,"method":"Debugger.resume"}))
            break
    print("paused",paused)
    time.sleep(2); ws.close()
time.sleep(15)
print("alive",app.alive(pid))
app.kill_pid(pid); time.sleep(1)
for q in app.find_pids_by_name("cerberus-games.exe"): app.kill_pid(q)
