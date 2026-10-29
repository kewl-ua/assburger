import re
t=open(r"C:\SHARE\hwid\logs\asar\build_electron.js",encoding='utf-8',errors='replace').read()
# find the module 0x857 region and nearby literal file-ish strings
i=t.find("0x857:function")
print("module at",i)
seg=t[i:i+200000]
for m in re.finditer(r"['\"]([^'\"]{3,120})['\"]", seg):
    s=m.group(1)
    if re.search(r'(System|\.json|\.dat|\.txt|\.cfg|seed|hwid|machine|1a0529|dir|path|AppData|Roaming|Local)', s, re.I):
        print(repr(s))
