import re
f=r"C:\SHARE\hwid\logs\asar\build_electron.js"; t=open(f,encoding='utf-8',errors='replace').read()
for term in ["_0x3e6c7d","_0x1cd137","HwID","'hwid'","\"hwid\"","protover","hashes"]:
    print("="*100); print(term, "count", t.count(term))
    for m in list(re.finditer(re.escape(term),t))[:6]:
        s=max(0,m.start()-1200); e=min(len(t),m.end()+1200)
        snip=" ".join(t[s:e].split())
        print(snip[:2200]); print("---")
