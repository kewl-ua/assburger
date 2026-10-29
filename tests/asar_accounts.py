import re
for f in [r"C:\SHARE\hwid\logs\asar\build_electron.js", r"C:\SHARE\hwid\logs\asar\build_static_js_main.2f021bde.js"]:
    t=open(f,encoding='utf-8',errors='replace').read()
    print("="*90, f, len(t))
    for term in ["accounts.json","accounts","Saved","saved","System","System\\\\","saveAccount","AccountList","AutoLogin","login"]:
        ms=list(re.finditer(re.escape(term),t,re.I))
        if ms:
            print("--",term,len(ms))
            for m in ms[:5]:
                s=max(0,m.start()-160); e=min(len(t),m.end()+240)
                print("  ", " ".join(t[s:e].split())[:450])
