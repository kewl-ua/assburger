/* rfmon3.c - inline-hook monitor for RFOCliMod dynamic/system API calls (32-bit).
 * Logs caller addresses so a call made from RFOCliMod's region is visible even when it
 * resolves the API dynamically (IAT hooks in rfmon2 only see static imports).
 * Inject AFTER the game window is up, so RFOCliMod init is not raced.
 * Build: gcc -shared -s -O2 -o rfmon3.dll rfmon3.c -lpsapi -ladvapi32 -luser32
 */
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <winternl.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

static HANDLE g_log = INVALID_HANDLE_VALUE;
static CRITICAL_SECTION g_cs;
static DWORD g_rf_base, g_rf_end, g_game_base, g_game_end;

static void hslog(const char *fmt, ...) {
    char buf[2048]; va_list ap; int n; DWORD wrote;
    if (g_log == INVALID_HANDLE_VALUE) return;
    va_start(ap, fmt); n = wvsprintfA(buf, fmt, ap); va_end(ap);
    if (n < 0) n = 0; if (n > (int)sizeof(buf) - 2) n = sizeof(buf) - 2;
    buf[n++] = '\r'; buf[n++] = '\n';
    EnterCriticalSection(&g_cs); WriteFile(g_log, buf, n, &wrote, NULL); LeaveCriticalSection(&g_cs);
}
static void logcall(const char *api, void *ret, const char *extra) {
    DWORD r = (DWORD)(DWORD_PTR)ret;
    int rf = (g_rf_base && r >= g_rf_base && r < g_rf_end);
    int gm = (g_game_base && r >= g_game_base && r < g_game_end);
    hslog("%s caller=%08X%s%s %s", api, r, rf ? " RF" : "", gm ? " GAME" : "", extra ? extra : "");
}

/* small x86 length decoder (hot-patch prologues) */
static int insn_len(const BYTE *p) {
    const BYTE *s = p; int i;
    for (i = 0; i < 4; i++) {
        if (p[0] == 0x66 || p[0] == 0x67 || p[0] == 0xF0 || p[0] == 0xF2 || p[0] == 0xF3 ||
            p[0] == 0x2E || p[0] == 0x3E || p[0] == 0x26 || p[0] == 0x36 || p[0] == 0x64 || p[0] == 0x65)
            p++;
        else break;
    }
    switch (*p) {
    case 0xE9: case 0xE8: return (int)(p - s) + 5;
    case 0xEB: return (int)(p - s) + 2;
    case 0x9A: return (int)(p - s) + 7;
    case 0x8B: case 0x89: case 0x8D: case 0x03: case 0x2B:
    case 0x33: case 0x0B: case 0x23: case 0x3B: case 0x85: case 0x87: {
        int mod = (p[1] >> 6) & 3; int rm = p[1] & 7; int len = 2;
        if (mod != 3) { if (rm == 4) len++; len += 4; }
        else if (rm == 4) len++;
        return (int)(p - s) + len;
    }
    case 0xB8: case 0xB9: case 0xBA: case 0xBB: case 0xBC: case 0xBD: case 0xBE: case 0xBF:
        return (int)(p - s) + 5;
    default:
        if (*p >= 0x50 && *p <= 0x5F) return (int)(p - s) + 1;
        if (*p == 0x68) return (int)(p - s) + 5;
        if (*p == 0x6A) return (int)(p - s) + 2;
        return (int)(p - s) + 2;
    }
}

static void *InlineHook(void *target, void *hook) {
    BYTE *t = (BYTE *)target; BYTE *tr; DWORD old, copy = 0;
    if (!t || !hook) return target;
    if (t[0] == 0xE9) return target;
    while (copy < 5) {
        int l = insn_len(t + copy);
        if (l <= 0) l = 1;
        copy += l;
        if (copy > 16) break;
    }
    tr = (BYTE *)VirtualAlloc(NULL, 48, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!tr) return target;
    memcpy(tr, t, copy);
    tr[copy] = 0xE9;
    *(DWORD *)(tr + copy + 1) = (DWORD)(t + copy) - (DWORD)(tr + copy + 5);
    if (!VirtualProtect(t, copy, PAGE_EXECUTE_READWRITE, &old)) { VirtualFree(tr, 0, MEM_RELEASE); return target; }
    memset(t, 0x90, copy); t[0] = 0xE9;
    *(DWORD *)(t + 1) = (DWORD)hook - (DWORD)(t + 5);
    VirtualProtect(t, copy, old, &old);
    hslog("INLINE %p -> %p copy=%u", target, hook, copy);
    return tr;
}

static void *export_of(const char *mod, const char *name) {
    HMODULE m = GetModuleHandleA(mod);
    if (!m) m = LoadLibraryA(mod);
    return m ? (void *)GetProcAddress(m, name) : NULL;
}

/* ---- hooks ---- */
typedef BOOL (WINAPI *PK32Enum)(HANDLE, HMODULE *, DWORD, LPDWORD);
static PK32Enum o_K32Enum;
static BOOL WINAPI h_K32Enum(HANDLE p, HMODULE *mods, DWORD cb, LPDWORD need) {
    BOOL r = o_K32Enum(p, mods, cb, need);
    char e[64]; wsprintfA(e, "need=%u", need ? *need : 0);
    logcall("K32EnumProcessModules", __builtin_return_address(0), e);
    return r;
}
typedef BOOL (WINAPI *PEnum)(HANDLE, HMODULE *, DWORD, LPDWORD);
static PEnum o_Enum;
static BOOL WINAPI h_Enum(HANDLE p, HMODULE *mods, DWORD cb, LPDWORD need) {
    BOOL r = o_Enum(p, mods, cb, need);
    char e[64]; wsprintfA(e, "need=%u", need ? *need : 0);
    logcall("EnumProcessModules", __builtin_return_address(0), e);
    return r;
}
typedef SIZE_T (WINAPI *PVQ)(LPCVOID, PMEMORY_BASIC_INFORMATION, SIZE_T);
typedef SIZE_T (WINAPI *PVQX)(HANDLE, LPCVOID, PMEMORY_BASIC_INFORMATION, SIZE_T);
static PVQ o_VQ;
static PVQX o_VQX;
static SIZE_T WINAPI h_VQ(LPCVOID a, PMEMORY_BASIC_INFORMATION m, SIZE_T n) {
    SIZE_T r = o_VQ(a, m, n);
    char e[128]; wsprintfA(e, "addr=%08X size=%u prot=%08X", (DWORD)(DWORD_PTR)a, m ? m->RegionSize : 0, m ? m->Protect : 0);
    logcall("VirtualQuery", __builtin_return_address(0), e);
    return r;
}
static SIZE_T WINAPI h_VQX(HANDLE p, LPCVOID a, PMEMORY_BASIC_INFORMATION m, SIZE_T n) {
    SIZE_T r = o_VQX(p, a, m, n);
    char e[128]; wsprintfA(e, "pid=%u addr=%08X size=%u", (DWORD)(DWORD_PTR)p, (DWORD)(DWORD_PTR)a, m ? m->RegionSize : 0);
    logcall("VirtualQueryEx", __builtin_return_address(0), e);
    return r;
}
typedef BOOL (WINAPI *PRPM)(HANDLE, LPCVOID, LPVOID, SIZE_T, SIZE_T *);
static PRPM o_RPM;
static BOOL WINAPI h_RPM(HANDLE p, LPCVOID a, LPVOID b, SIZE_T n, SIZE_T *got) {
    BOOL r = o_RPM(p, a, b, n, got);
    char e[128]; wsprintfA(e, "addr=%08X size=%u got=%u", (DWORD)(DWORD_PTR)a, n, got ? *got : 0);
    logcall("ReadProcessMemory", __builtin_return_address(0), e);
    return r;
}
typedef NTSTATUS (NTAPI *PNQIP)(HANDLE, ULONG, PVOID, ULONG, PULONG);
static PNQIP o_NQIP;
static NTSTATUS NTAPI h_NQIP(HANDLE p, ULONG cls, PVOID buf, ULONG len, PULONG ret) {
    NTSTATUS r = o_NQIP(p, cls, buf, len, ret);
    char e[64]; wsprintfA(e, "class=%u", cls);
    logcall("NtQueryInformationProcess", __builtin_return_address(0), e);
    return r;
}
typedef BOOL (WINAPI *PIDP)(void);
static PIDP o_IDP;
static BOOL WINAPI h_IDP(void) {
    BOOL r = o_IDP();
    logcall("IsDebuggerPresent", __builtin_return_address(0), r ? "1" : "0");
    return r;
}
typedef HANDLE (WINAPI *PCT32)(DWORD, DWORD);
static PCT32 o_CT32;
static HANDLE WINAPI h_CT32(DWORD flags, DWORD pid) {
    HANDLE r = o_CT32(flags, pid);
    char e[64]; wsprintfA(e, "flags=%X pid=%u", flags, pid);
    logcall("CreateToolhelp32Snapshot", __builtin_return_address(0), e);
    return r;
}

static void find_modules(void) {
    HMODULE mods[1024]; DWORD need = 0; int n, i; wchar_t path[1024];
    if (!EnumProcessModules(GetCurrentProcess(), mods, sizeof(mods), &need)) return;
    n = need / sizeof(HMODULE);
    for (i = 0; i < n && i < 1024; i++) {
        MODULEINFO mi; char a[1024];
        if (!GetModuleInformation(GetCurrentProcess(), mods[i], &mi, sizeof(mi))) continue;
        if (!GetModuleFileNameExW(GetCurrentProcess(), mods[i], path, 1024)) continue;
        WideCharToMultiByte(CP_ACP, 0, path, -1, a, sizeof(a), 0, 0);
        if (strstr(a, "RFOCliMod")) {
            g_rf_base = (DWORD)(DWORD_PTR)mi.lpBaseOfDll; g_rf_end = g_rf_base + mi.SizeOfImage;
            hslog("RFOCliMod base=%08X end=%08X path=%s", g_rf_base, g_rf_end, a);
        }
        if (!g_game_base && strstr(a, "RF_Online_4gb.bin")) {
            g_game_base = (DWORD)(DWORD_PTR)mi.lpBaseOfDll; g_game_end = g_game_base + mi.SizeOfImage;
            hslog("game base=%08X end=%08X", g_game_base, g_game_end);
        }
    }
}

static void hook_export(const char *mod, const char *name, void *hook, void **orig) {
    void *p = export_of(mod, name);
    if (!p) { hslog("MISS %s!%s", mod, name); return; }
    *orig = InlineHook(p, hook);
}

static DWORD WINAPI init_thread(LPVOID p) {
    char path[MAX_PATH]; DWORD pid = GetCurrentProcessId();
    wsprintfA(path, "C:\\SHARE\\hwid\\re_hackshield\\logs\\rfmon3_%lu.log", pid);
    g_log = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    hslog("RFMON3 start pid=%lu", pid);
    find_modules();
    hook_export("KERNEL32.dll", "K32EnumProcessModules", (void *)h_K32Enum, (void **)&o_K32Enum);
    hook_export("PSAPI.dll", "EnumProcessModules", (void *)h_Enum, (void **)&o_Enum);
    hook_export("KERNEL32.dll", "VirtualQuery", (void *)h_VQ, (void **)&o_VQ);
    hook_export("KERNEL32.dll", "VirtualQueryEx", (void *)h_VQX, (void **)&o_VQX);
    hook_export("KERNEL32.dll", "ReadProcessMemory", (void *)h_RPM, (void **)&o_RPM);
    hook_export("ntdll.dll", "NtQueryInformationProcess", (void *)h_NQIP, (void **)&o_NQIP);
    hook_export("KERNEL32.dll", "IsDebuggerPresent", (void *)h_IDP, (void **)&o_IDP);
    hook_export("KERNEL32.dll", "CreateToolhelp32Snapshot", (void *)h_CT32, (void **)&o_CT32);
    hslog("RFMON3 hooks installed");
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID r) {
    if (reason == DLL_PROCESS_ATTACH) {
        InitializeCriticalSection(&g_cs);
        DisableThreadLibraryCalls(h);
        CreateThread(NULL, 0, init_thread, NULL, 0, NULL);
    }
    return TRUE;
}
