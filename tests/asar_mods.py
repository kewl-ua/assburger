import re
t=open(r"C:\SHARE\hwid\logs\asar\build_electron.js",encoding='utf-8',errors='replace').read()
for key in ["0x857:","0x1b2e:","0x107c","0x7e5","0x76b","0xfb1"]:
    print("="*100,key,"count",t.count(key))
    for m in list(re.finditer(re.escape(key),t))[:3]:
        s=m.start(); e=min(len(t),s+2500)
        print(" ".join(t[s:e].split())[:2400]); print("---")
