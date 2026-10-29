import re
p = r"C:\SHARE\hwid\re_hackshield\poc\hsmon.c"
s = open(p, encoding="utf-8").read()
s = s.replace("hsmon4_%lu.log", "hsmon5_%lu.log")
s = s.replace('#include <iphlpapi.h>', '#include <iphlpapi.h>\n#include <psapi.h>')
s = s.replace('static void hook_iat(HMODULE mod, const char *dll, const char *func, void *newfn, void **orig) {',
              'static int hook_iat(HMODULE mod, const char *dll, const char *func, void *newfn, void **orig) {')
s = s.replace('    if (!mod) return;\n', '    if (!mod) return 0;\n')
s = s.replace('    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return;\n', '    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;\n')
s = s.replace('    if (nt->Signature != IMAGE_NT_SIGNATURE) return;\n', '    if (nt->Signature != IMAGE_NT_SIGNATURE) return 0;\n')
s = s.replace('            return;\n        }\n    }\n    hslog("IAT MISS %s!%s", dll, func);\n}',
              '            return 1;\n        }\n    }\n    return 0;\n}')
s = s.replace('static int find_and_hook_cb(void) {', '''static void hook_all(const char *dll, const char *func, void *newfn, void **orig) {
    HMODULE mods[1024];
    DWORD need = 0;
    int n, i, found = 0;
    if (!EnumProcessModules(GetCurrentProcess(), mods, sizeof(mods), &need)) return;
    n = need / sizeof(HMODULE);
    for (i = 0; i < n && i < 1024; i++) found += hook_iat(mods[i], dll, func, newfn, orig);
    hslog("IATALL %s!%s found=%d mods=%d", dll, func, found, n);
}

static int find_and_hook_cb(void) {''')
s = re.sub(r'hook_iat\(g_game,\s*', 'hook_all(', s)
open(p, "w", encoding="utf-8").write(s)
print("patched", s.count("hook_all("))
