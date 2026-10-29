import re, sys
files=[r"C:\SHARE\CERBERUS\RF_Online.bin", r"C:\SHARE\hwid\RF_Online_4gb_dump.exe",
       r"C:\SHARE\CERBERUS\PurifierA.dll", r"C:\SHARE\CERBERUS\ABuse.dll", r"C:\SHARE\CERBERUS\Adv.dll",
       r"C:\SHARE\CERBERUS\StringLoaderA.dll"]
kw=re.compile(r'(hwid|hardware|serial|machineguid|machine.?id|mac.?addr|volume|disk|uuid|bios|baseboard|board|computer.?name|hostname|netbios|wmi|win32_|adapter|device.?id|client.?id|fingerprint|product.?id|cd.?key|regquery|machine|guid|rf_online|purifier|abuse|adv\.dll)', re.I)
dom=re.compile(rb'(?:https?://[^\x00\s"\'<>]{4,120}|[a-z0-9][a-z0-9.-]{2,60}\.(?:com|net|ru|org|io|me|cc|su|info))', re.I)
def strings(b, wide):
    if wide:
        out=[]; cur=[]
        for i in range(0,len(b)-1,2):
            c=b[i]|(b[i+1]<<8)
            if 32<=c<127: cur.append(chr(c))
            else:
                if len(cur)>=4: out.append("".join(cur))
                cur=[]
        if len(cur)>=4: out.append("".join(cur))
        return out
    out=[]; cur=bytearray()
    for c in b:
        if 32<=c<127: cur.append(c)
        else:
            if len(cur)>=4: out.append(cur.decode('latin1'))
            cur=bytearray()
    if len(cur)>=4: out.append(cur.decode('latin1'))
    return out
for f in files:
    print("="*80); print(f)
    try:
        b=open(f,'rb').read()
        s=strings(b,False)+strings(b,True)
        seen=set(); hits=[]
        for x in s:
            x=x.strip()
            if x in seen: continue
            seen.add(x)
            if kw.search(x) and len(x)<200:
                hits.append(x)
        for x in hits[:120]: print("  ",x)
        print("  -- hits:",len(hits))
        ds=set()
        for m in dom.finditer(b):
            d=m.group(0).decode('latin1','replace')
            if len(d)<120: ds.add(d)
        if ds:
            print("  -- domains/urls:")
            for d in sorted(ds)[:60]: print("    ",d)
    except Exception as e: print("ERR",e)
