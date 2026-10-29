import re
f=r"C:\SHARE\CERBERUS\resources\app.asar"; b=open(f,'rb').read()
kw=re.compile(rb'(hwid|hardware|machine.?id|machineguid|mac.?addr|serial|uuid|bios|baseboard|fingerprint|adapter|GetAdapters|GetVolume|RF_Online|spawn|child_process|execFile|HackShield|VphwID)', re.I)
seen=set(); n=0
for m in kw.finditer(b):
    s=max(0,m.start()-120); e=min(len(b),m.end()+160)
    ctx=b[s:e]
    txt=ctx.decode('latin1','replace')
    txt=" ".join("".join(c if 32<=ord(c)<127 else " " for c in txt).split())
    if txt in seen: continue
    seen.add(txt); print(txt); n+=1
    if n>=120: break
print("total matches", len(list(kw.finditer(b))))
