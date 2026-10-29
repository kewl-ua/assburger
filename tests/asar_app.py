import re, os
files=[r"C:\SHARE\hwid\logs\asar\build_electron.js", r"C:\SHARE\hwid\logs\asar\build_static_js_main.2f021bde.js"]
pat=re.compile(r'(systeminformation|si\.(?:cpu|system|baseboard|bios|diskLayout|graphics|mem|osInfo|networkInterfaces|uuid|chassis|blockDevices|fsSize|versions|users|processes|currentLoad|temp|battery|usb)|Get-CimInstance|Win32_|powershell|wmic|child_process|execFile|spawn|RF_Online|HackShield|VphwID|hwid|machineId|hardware)', re.I)
for f in files:
    print("="*100); print(os.path.basename(f))
    txt=open(f,encoding='utf-8',errors='replace').read()
    seen=set(); n=0
    for m in pat.finditer(txt):
        s=max(0,m.start()-90); e=min(len(txt),m.end()+140)
        snip=" ".join(txt[s:e].split())
        if snip in seen: continue
        seen.add(snip)
        if pat.search(snip):
            print(repr(snip[:300])); n+=1
            if n>=120: break
    print("shown",n)
