import re,glob,os
kw=re.compile(r'(hwid|hardware|machine.?id|machineguid|mac.?addr|serial|uuid|bios|baseboard|fingerprint|adapter|GetAdapters|GetVolume|RF_Online|spawn|execFile|HackShield|VphwID|systeminformation|node-machine-id|computerName|hostname|proxy|auth)', re.I)
for f in glob.glob(r"C:\SHARE\hwid\logs\asar\*"):
    if os.path.basename(f)=='build_config.json': continue
    txt=open(f,encoding='utf-8',errors='replace').read()
    print("="*90); print(os.path.basename(f), len(txt))
    seen=set(); n=0
    for m in kw.finditer(txt):
        s=max(0,m.start()-160); e=min(len(txt),m.end()+220)
        snip=" ".join(txt[s:e].split())
        if snip in seen: continue
        seen.add(snip); print("  ...",snip[:500]); n+=1
        if n>=80: break
