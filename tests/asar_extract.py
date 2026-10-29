import struct, json, re, os
p=r"C:\SHARE\CERBERUS\resources\app.asar"
b=open(p,'rb').read()
print("len",len(b),"first16",b[:16].hex())
hs=struct.unpack_from('<I',b,0)[0]; js=struct.unpack_from('<I',b,4)[0]
print("header_size",hs,"json_size",js)
try:
    h=json.loads(b[8:8+js].decode('utf-8'))
    print("json ok, top keys", list(h.keys())[:10])
except Exception as e:
    print("json err",e); raise SystemExit
data_start=8+hs
print("data_start",data_start)
kw=re.compile(r'(hwid|hardware|machine.?id|machineguid|mac.?addr|serial|uuid|bios|baseboard|fingerprint|adapter|GetAdapters|GetVolume|RF_Online|spawn|execFile|HackShield|VphwID|systeminformation|node-machine-id|computerName|hostname)', re.I)
found=[]
def walk(node, path):
    for name, val in node.get('files',{}).items():
        fp=path+"/"+name if path else name
        if 'files' in val: walk(val, fp)
        elif name.lower().endswith(('.js','.ts','.json')) and 'node_modules' not in fp.lower():
            off=val.get('offset'); size=val.get('size')
            if off is None or size is None: continue
            data=b[data_start+int(off):data_start+int(off)+int(size)]
            txt=data.decode('utf-8','replace')
            if kw.search(txt):
                hits=[]
                for m in kw.finditer(txt):
                    s=max(0,m.start()-100); e=min(len(txt),m.end()+140)
                    snip=" ".join(txt[s:e].split())
                    if snip not in hits: hits.append(snip)
                    if len(hits)>=6: break
                found.append((fp,size,hits))
walk(h,"")
print("app files with hits",len(found))
for fp,size,hits in found[:60]:
    print("="*80); print(fp,size)
    for x in hits: print("  ",x[:400])
