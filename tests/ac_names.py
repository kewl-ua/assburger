import re
files=[r"C:\SHARE\CERBERUS\RF_Online.bin", r"C:\SHARE\hwid\RF_Online_4gb_dump.exe"]
for f in files:
    print("="*90); print(f)
    b=open(f,'rb').read()
    # ascii+utf16 strings, look for anti-cheat module names / paths
    pat=re.compile(r'(HackShield|HShield|HSCore|HSUpdate|AhnLab|AHNLAB|hshield|HSP|Purifier|ABuse|Adv\.dll|VphwID|HSvc|Hack\.dll)', re.I)
    seen=set()
    for wide in (False,True):
        if wide:
            s=[]; cur=[]
            for i in range(0,len(b)-1,2):
                c=b[i]|(b[i+1]<<8)
                if 32<=c<127: cur.append(chr(c))
                else:
                    if len(cur)>=4: s.append("".join(cur)); cur=[]
                    else: cur=[]
            if len(cur)>=4: s.append("".join(cur))
        else:
            s=[]; cur=bytearray()
            for c in b:
                if 32<=c<127: cur.append(c)
                else:
                    if len(cur)>=4: s.append(cur.decode('latin1')); cur=bytearray()
            if len(cur)>=4: s.append(cur.decode('latin1'))
        for x in s:
            x=x.strip()
            if x in seen: continue
            if pat.search(x) and len(x)<160:
                seen.add(x); print(repr(x))
