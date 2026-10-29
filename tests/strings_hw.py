import re
files=[r"C:\SHARE\CERBERUS\RF_Online.bin", r"C:\SHARE\hwid\RF_Online_4gb_dump.exe"]
pat=re.compile(r'(SOFTWARE|HKEY|Cryptography|MachineGuid|Machine.?Id|CD.?Key|Product.?Id|InstallDate|SerialNumber|BaseBoard|BIOS|Win32_|Adapter|ComputerName|HostName|Netbios|Volume|UUID|HWID|Hardware|MAC|Ethernet|Disk|Drive|Processor)', re.I)
for f in files:
    print("="*80); print(f)
    b=open(f,'rb').read(); s=[]; cur=bytearray()
    for c in b:
        if 32<=c<127: cur.append(c)
        else:
            if len(cur)>=4: s.append(cur.decode('latin1'))
            cur=bytearray()
    if len(cur)>=4: s.append(cur.decode('latin1'))
    seen=set(); n=0
    for x in s:
        x=x.strip()
        if len(x)<4 or len(x)>160 or x in seen: continue
        if pat.search(x):
            seen.add(x); print("  ",x); n+=1
            if n>=200: break
    # utf16
    s2=[]; cur=[]
    for i in range(0,len(b)-1,2):
        c=b[i]|(b[i+1]<<8)
        if 32<=c<127: cur.append(chr(c))
        else:
            if len(cur)>=4: s2.append("".join(cur)); cur=[]
            else: cur=[]
    if len(cur)>=4: s2.append("".join(cur))
    for x in s2:
        x=x.strip()
        if len(x)<4 or len(x)>160 or x in seen: continue
        if pat.search(x):
            seen.add(x); print("  W:",x); n+=1
            if n>=200: break
