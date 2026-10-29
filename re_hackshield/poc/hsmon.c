#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <iphlpapi.h>
#include <psapi.h>
#include <nb30.h>
#include <iptypes.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

typedef NCB *PNCB;
static HANDLE g_log = INVALID_HANDLE_VALUE;
static CRITICAL_SECTION g_cs;
static HMODULE g_game;
static BYTE *g_cb_target;
static BYTE g_cb_saved[5];
static int g_cb_installed;

static void hslog(const char *fmt, ...) {
    char buf[2048];
    va_list ap;
    int n;
    DWORD wrote;
    if (g_log == INVALID_HANDLE_VALUE) return;
    va_start(ap, fmt);
    n = wvsprintfA(buf, fmt, ap);
    va_end(ap);
    if (n < 0) n = 0;
    if (n > (int)sizeof(buf) - 2) n = sizeof(buf) - 2;
    buf[n++] = '\r'; buf[n++] = '\n';
    EnterCriticalSection(&g_cs);
    WriteFile(g_log, buf, n, &wrote, NULL);
    LeaveCriticalSection(&g_cs);
}

static void loghex(const char *tag, const BYTE *p, int n) {
    char out[3*64 + 1];
    int i, k = 0;
    if (n > 64) n = 64;
    for (i = 0; i < n; i++) {
        static const char *hx = "0123456789abcdef";
        out[k++] = hx[p[i] >> 4];
        out[k++] = hx[p[i] & 15];
        if (i + 1 < n) out[k++] = ' ';
    }
    out[k] = 0;
    hslog("%s len=%d [%s]", tag, n, out);
}

static void patch_jmp(BYTE *target, void *dest, BYTE *saved) {
    DWORD old;
    if (VirtualProtect(target, 5, PAGE_EXECUTE_READWRITE, &old)) {
        if (saved) memcpy(saved, target, 5);
        target[0] = 0xE9;
        *(int *)(target + 1) = (int)((BYTE *)dest - (target + 5));
        VirtualProtect(target, 5, old, &old);
        FlushInstructionCache(GetCurrentProcess(), target, 5);
    }
}

typedef int (__stdcall *ORIG_CB)(int, int, void *);
static ORIG_CB g_orig_cb;

static int __stdcall hook_cb(int code, int a2, void *data) {
    DWORD old;
    int r;
    char fn[129], mod[129];
    fn[0] = mod[0] = 0;
    if (code == 0x10101 && data) {
        lstrcpynA(fn, (const char *)data, 129);
        lstrcpynA(mod, (const char *)((BYTE *)data + 0x80), 129);
        hslog("HS_CB code=%X a2=%d data=%08X fn='%s' mod='%s'", code, a2, (DWORD)(DWORD_PTR)data, fn, mod);
    } else if (code == 0x10102 && data) {
        hslog("HS_CB code=%X a2=%d data=%08X automouse_flag=%u", code, a2, (DWORD)(DWORD_PTR)data, (unsigned)*(BYTE *)data);
    } else {
        hslog("HS_CB code=%X a2=%d data=%08X", code, a2, (DWORD)(DWORD_PTR)data);
    }
    if (VirtualProtect(g_cb_target, 5, PAGE_EXECUTE_READWRITE, &old)) {
        memcpy(g_cb_target, g_cb_saved, 5);
        VirtualProtect(g_cb_target, 5, old, &old);
        FlushInstructionCache(GetCurrentProcess(), g_cb_target, 5);
    }
    r = g_orig_cb(code, a2, data);
    patch_jmp(g_cb_target, (void *)hook_cb, NULL);
    return r;
}

static int hook_iat(HMODULE mod, const char *dll, const char *func, void *newfn, void **orig) {
    IMAGE_DOS_HEADER *dos;
    IMAGE_NT_HEADERS *nt;
    IMAGE_IMPORT_DESCRIPTOR *imp;
    if (!mod) return 0;
    dos = (IMAGE_DOS_HEADER *)mod;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;
    nt = (IMAGE_NT_HEADERS *)((BYTE *)mod + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return 0;
    imp = (IMAGE_IMPORT_DESCRIPTOR *)((BYTE *)mod + nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress);
    for (; imp->Name; imp++) {
        const char *dn = (const char *)((BYTE *)mod + imp->Name);
        IMAGE_THUNK_DATA *thunk, *ot;
        if (_stricmp(dn, dll) != 0) continue;
        thunk = (IMAGE_THUNK_DATA *)((BYTE *)mod + imp->FirstThunk);
        ot = imp->OriginalFirstThunk ? (IMAGE_THUNK_DATA *)((BYTE *)mod + imp->OriginalFirstThunk) : thunk;
        for (; thunk->u1.Function; thunk++, ot++) {
            IMAGE_IMPORT_BY_NAME *ibn;
            DWORD old;
            if (ot->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;
            ibn = (IMAGE_IMPORT_BY_NAME *)((BYTE *)mod + ot->u1.AddressOfData);
            if (strcmp((const char *)ibn->Name, func) != 0) continue;
            if (orig) *orig = (void *)thunk->u1.Function;
            if (VirtualProtect(&thunk->u1.Function, sizeof(ULONG_PTR), PAGE_READWRITE, &old)) {
                thunk->u1.Function = (ULONG_PTR)newfn;
                VirtualProtect(&thunk->u1.Function, sizeof(ULONG_PTR), old, &old);
                hslog("IAT %s!%s %08X -> %08X", dll, func, (DWORD)(DWORD_PTR)(orig ? *orig : 0), (DWORD)(DWORD_PTR)newfn);
            }
            return 1;
        }
    }
    return 0;
}

typedef LONG (WINAPI *PRegQueryValueExA)(HKEY, LPCSTR, LPDWORD, LPDWORD, LPBYTE, LPDWORD);
static PRegQueryValueExA o_RegQueryValueExA;
static LONG WINAPI h_RegQueryValueExA(HKEY hKey, LPCSTR name, LPDWORD res, LPDWORD type, LPBYTE data, LPDWORD cb) {
    LONG r = o_RegQueryValueExA(hKey, name, res, type, data, cb);
    hslog("REG name='%s' r=%d type=%u cb=%u", name ? name : "(null)", (int)r, type ? *type : 0, cb ? *cb : 0);
    if (r == 0 && data && type && (*type == REG_SZ || *type == REG_EXPAND_SZ) && cb && *cb > 0) {
        char s[256]; DWORD n = *cb; if (n > 255) n = 255; memcpy(s, data, n); s[n] = 0;
        hslog("REG   data='%s'", s);
    } else if (r == 0 && data && cb && *cb >= 16 && *cb <= 64) {
        loghex("REG   data", data, *cb);
    }
    return r;
}

typedef UCHAR (WINAPI *PNetbios)(PNCB);
static PNetbios o_Netbios;
static UCHAR WINAPI h_Netbios(PNCB p) {
    UCHAR r = o_Netbios(p);
    if (p) {
        char name[17]; memcpy(name, p->ncb_callname, 16); name[16] = 0;
        hslog("NETBIOS cmd=%02X call='%s' r=%u", p->ncb_command, name, r);
    }
    return r;
}

typedef int (WSAAPI *Pgethostname)(char *, int);
static Pgethostname o_gethostname;
static int WSAAPI h_gethostname(char *name, int len) {
    int r = o_gethostname(name, len);
    hslog("GETHOSTNAME r=%d len=%d name='%s'", r, len, (r == 0 && name) ? name : "");
    return r;
}

typedef void (WINAPI *PGetSystemInfo)(LPSYSTEM_INFO);
static PGetSystemInfo o_GetSystemInfo;
static void WINAPI h_GetSystemInfo(LPSYSTEM_INFO si) {
    o_GetSystemInfo(si);
    if (si) hslog("GETSYSTEMINFO arch=%u procs=%u page=%u min=%08X max=%08X gran=%08X",
        si->wProcessorArchitecture, si->dwNumberOfProcessors, si->dwPageSize,
        (DWORD)(DWORD_PTR)si->lpMinimumApplicationAddress, (DWORD)(DWORD_PTR)si->lpMaximumApplicationAddress,
        si->dwAllocationGranularity);
}

typedef UINT (WINAPI *PGetDriveTypeA)(LPCSTR);
static PGetDriveTypeA o_GetDriveTypeA;
static UINT WINAPI h_GetDriveTypeA(LPCSTR root) {
    UINT r = o_GetDriveTypeA(root);
    hslog("GETDRIVETYPE root='%s' r=%u", root ? root : "", r);
    return r;
}

typedef BOOL (WINAPI *PGetComputerNameExW)(int, LPWSTR, LPDWORD);
static PGetComputerNameExW o_GetComputerNameExW;
static BOOL WINAPI h_GetComputerNameExW(int fmt, LPWSTR buf, LPDWORD size) {
    BOOL r = o_GetComputerNameExW(fmt, buf, size);
    if (r && buf) { char a[256]; WideCharToMultiByte(CP_ACP,0,buf,-1,a,sizeof(a),0,0); hslog("COMPUTERNAME fmt=%d '%s'", fmt, a); }
    return r;
}

typedef ULONG (WINAPI *PGetAdaptersAddresses)(ULONG, ULONG, PVOID, PIP_ADAPTER_ADDRESSES, PULONG);
static PGetAdaptersAddresses o_GetAdaptersAddresses;
static ULONG WINAPI h_GetAdaptersAddresses(ULONG fam, ULONG flags, PVOID res, PIP_ADAPTER_ADDRESSES aa, PULONG sz) {
    ULONG r = o_GetAdaptersAddresses(fam, flags, res, aa, sz);
    if (r == 0 && aa) {
        char mac[32]; int i, k = 0;
        for (i = 0; i < (int)aa->PhysicalAddressLength && i < 8 && k < 28; i++) {
            static const char *hx = "0123456789ABCDEF";
            if (i) mac[k++] = ':';
            mac[k++] = hx[aa->PhysicalAddress[i] >> 4];
            mac[k++] = hx[aa->PhysicalAddress[i] & 15];
        }
        mac[k] = 0;
        hslog("ADAPTERS fam=%u flags=%X mac='%s' iftype=%u", fam, flags, mac, aa->IfType);
    } else {
        hslog("ADAPTERS fam=%u flags=%X r=%u", fam, flags, r);
    }
    return r;
}

typedef UINT (WINAPI *PSendInput)(UINT, LPINPUT, int);
static PSendInput o_SendInput;
static UINT WINAPI h_SendInput(UINT n, LPINPUT p, int cb) {
    UINT r = o_SendInput(n, p, cb);
    if (p && n) hslog("SENDINPUT n=%u type=%u flags=%X dx=%d dy=%d r=%u", n, p->type, p->ki.dwFlags, p->mi.dx, p->mi.dy, r);
    else hslog("SENDINPUT n=%u r=%u", n, r);
    return r;
}

typedef BOOL (WINAPI *PSetCursorPos)(int, int);
static PSetCursorPos o_SetCursorPos;
static BOOL WINAPI h_SetCursorPos(int x, int y) {
    BOOL r = o_SetCursorPos(x, y);
    hslog("SETCURSORPOS x=%d y=%d r=%d", x, y, r);
    return r;
}

typedef void (WINAPI *Pmouse_event)(DWORD, DWORD, DWORD, DWORD, ULONG_PTR);
static Pmouse_event o_mouse_event;
static void WINAPI h_mouse_event(DWORD f, DWORD dx, DWORD dy, DWORD d, ULONG_PTR e) {
    o_mouse_event(f, dx, dy, d, e);
    hslog("MOUSE_EVENT flags=%X dx=%d dy=%d data=%d", f, dx, dy, d);
}

typedef BOOL (WINAPI *PPostMessageA)(HWND, UINT, WPARAM, LPARAM);
static PPostMessageA o_PostMessageA;
static BOOL WINAPI h_PostMessageA(HWND h, UINT m, WPARAM w, LPARAM l) {
    BOOL r = o_PostMessageA(h, m, w, l);
    if (m >= WM_MOUSEFIRST && m <= WM_MOUSELAST) hslog("POSTMSG hwnd=%08X msg=%X w=%X l=%X r=%d", (DWORD)(DWORD_PTR)h, m, (DWORD)w, (DWORD)l, r);
    return r;
}

static volatile LONG g_askey, g_curpos, g_keystate;
typedef SHORT (WINAPI *PGetAsyncKeyState)(int);
static PGetAsyncKeyState o_GetAsyncKeyState;
static SHORT WINAPI h_GetAsyncKeyState(int vk) {
    SHORT r = o_GetAsyncKeyState(vk);
    if ((InterlockedIncrement(&g_askey) % 500) == 0) hslog("GETASYNCKEY vk=%X r=%04X count=%ld", vk, (unsigned short)r, g_askey);
    return r;
}
typedef BOOL (WINAPI *PGetCursorPos)(LPPOINT);
static PGetCursorPos o_GetCursorPos;
static BOOL WINAPI h_GetCursorPos(LPPOINT p) {
    BOOL r = o_GetCursorPos(p);
    if ((InterlockedIncrement(&g_curpos) % 500) == 0) hslog("GETCURSORPOS r=%d x=%d y=%d count=%ld", r, p?p->x:0, p?p->y:0, g_curpos);
    return r;
}
typedef SHORT (WINAPI *PGetKeyState)(int);
static PGetKeyState o_GetKeyState;
static SHORT WINAPI h_GetKeyState(int vk) {
    SHORT r = o_GetKeyState(vk);
    if ((InterlockedIncrement(&g_keystate) % 500) == 0) hslog("GETKEYSTATE vk=%X r=%04X count=%ld", vk, (unsigned short)r, g_keystate);
    return r;
}

typedef int (WSAAPI *Psend)(SOCKET, const char *, int, int);
static Psend o_send;
static int WSAAPI h_send(SOCKET s, const char *b, int n, int f) {
    int r = o_send(s, b, n, f);
    if (b && n >= 4 && ((const BYTE *)b)[2] == 0x62) {
        hslog("SEND sock=%08X n=%d r=%d sub=%u", (DWORD)(DWORD_PTR)s, n, r, (unsigned)((const BYTE *)b)[3]);
        loghex("SEND data", (const BYTE *)b, n < 80 ? n : 80);
    }
    return r;
}

typedef int (WSAAPI *Precv)(SOCKET, char *, int, int);
static Precv o_recv;
static int WSAAPI h_recv(SOCKET s, char *b, int n, int f) {
    int r = o_recv(s, b, n, f);
    if (b && r >= 4 && ((const BYTE *)b)[2] == 0x62) {
        hslog("RECV sock=%08X n=%d r=%d sub=%u", (DWORD)(DWORD_PTR)s, n, r, (unsigned)((const BYTE *)b)[3]);
        loghex("RECV data", (const BYTE *)b, r < 80 ? r : 80);
    }
    return r;
}

typedef int (WSAAPI *PWSASend)(SOCKET, LPWSABUF, DWORD, LPDWORD, DWORD, LPWSAOVERLAPPED, LPWSAOVERLAPPED_COMPLETION_ROUTINE);
static PWSASend o_WSASend;
static int WSAAPI h_WSASend(SOCKET s, LPWSABUF bufs, DWORD nbuf, LPDWORD sent, DWORD flags, LPWSAOVERLAPPED ov, LPWSAOVERLAPPED_COMPLETION_ROUTINE cr) {
    int r = o_WSASend(s, bufs, nbuf, sent, flags, ov, cr);
    if (bufs && nbuf && bufs[0].buf && bufs[0].len) {
        static volatile LONG n;
        LONG c = InterlockedIncrement(&n);
        if (c < 4000 || bufs[0].len == 342 || bufs[0].len == 74) {
            loghex("WSASEND", (const BYTE *)bufs[0].buf, bufs[0].len < 64 ? bufs[0].len : 64);
            hslog("WSASEND len=%u r=%d n=%ld", bufs[0].len, r, c);
        }
    }
    return r;
}

typedef int (WSAAPI *PWSARecv)(SOCKET, LPWSABUF, DWORD, LPDWORD, LPDWORD, LPWSAOVERLAPPED, LPWSAOVERLAPPED_COMPLETION_ROUTINE);
static PWSARecv o_WSARecv;
static int WSAAPI h_WSARecv(SOCKET s, LPWSABUF bufs, DWORD nbuf, LPDWORD recvd, LPDWORD flags, LPWSAOVERLAPPED ov, LPWSAOVERLAPPED_COMPLETION_ROUTINE cr) {
    int r = o_WSARecv(s, bufs, nbuf, recvd, flags, ov, cr);
    if (bufs && nbuf && bufs[0].buf && bufs[0].len) {
        static volatile LONG n2;
        DWORD got = (recvd ? *recvd : bufs[0].len);
        LONG c = InterlockedIncrement(&n2);
        if (got && (c < 4000 || got == 342 || got == 74)) {
            loghex("WSARECV", (const BYTE *)bufs[0].buf, got < 64 ? got : 64);
            hslog("WSARECV len=%u got=%u r=%d n=%ld", bufs[0].len, got, r, c);
        }
    }
    return r;
}

typedef void (WINAPI *POutputDebugStringA)(LPCSTR);
static POutputDebugStringA o_OutputDebugStringA;
static void WINAPI h_OutputDebugStringA(LPCSTR s) {
    static volatile LONG n;
    if (s) {
        LONG c = InterlockedIncrement(&n);
        if (c < 400) hslog("ODS %ld '%s'", c, s);
    }
    o_OutputDebugStringA(s);
}

typedef int (WINAPI *PMessageBoxA)(HWND, LPCSTR, LPCSTR, UINT);
static PMessageBoxA o_MessageBoxA;
static int WINAPI h_MessageBoxA(HWND h, LPCSTR text, LPCSTR cap, UINT type) {
    hslog("MSGBOX cap='%s' text='%s' type=%X", cap ? cap : "", text ? text : "", type);
    return o_MessageBoxA(h, text, cap, type);
}

typedef HMODULE (WINAPI *PLoadLibraryA)(LPCSTR);
static PLoadLibraryA o_LoadLibraryA;
static HMODULE WINAPI h_LoadLibraryA(LPCSTR name) {
    HMODULE r = o_LoadLibraryA(name);
    hslog("LOADLIB '%s' -> %08X", name ? name : "", (DWORD)(DWORD_PTR)r);
    return r;
}

typedef BOOL (WINAPI *PCreateProcessA)(LPCSTR, LPSTR, LPSECURITY_ATTRIBUTES, LPSECURITY_ATTRIBUTES, BOOL, DWORD, LPVOID, LPCSTR, LPSTARTUPINFOA, LPPROCESS_INFORMATION);
static PCreateProcessA o_CreateProcessA;
static BOOL WINAPI h_CreateProcessA(LPCSTR app, LPSTR cmd, LPSECURITY_ATTRIBUTES pa, LPSECURITY_ATTRIBUTES ta, BOOL inh, DWORD flags, LPVOID env, LPCSTR dir, LPSTARTUPINFOA si, LPPROCESS_INFORMATION pi) {
    BOOL r = o_CreateProcessA(app, cmd, pa, ta, inh, flags, env, dir, si, pi);
    hslog("CREATEPROC app='%s' cmd='%s' r=%d", app ? app : "", cmd ? cmd : "", r);
    return r;
}

typedef DWORD (WINAPI *PGetPrivateProfileStringA)(LPCSTR, LPCSTR, LPCSTR, LPSTR, DWORD, LPCSTR);
static PGetPrivateProfileStringA o_GetPrivateProfileStringA;
static DWORD WINAPI h_GetPrivateProfileStringA(LPCSTR sec, LPCSTR key, LPCSTR def, LPSTR out, DWORD n, LPCSTR file) {
    DWORD r = o_GetPrivateProfileStringA(sec, key, def, out, n, file);
    hslog("INIGET file='%s' sec='%s' key='%s' r=%u val='%s'", file ? file : "", sec ? sec : "", key ? key : "", r, out ? out : "");
    return r;
}

static void hook_all(const char *dll, const char *func, void *newfn, void **orig) {
    HMODULE mods[1024];
    DWORD need = 0;
    int n, i, found = 0;
    if (!EnumProcessModules(GetCurrentProcess(), mods, sizeof(mods), &need)) return;
    n = need / sizeof(HMODULE);
    for (i = 0; i < n && i < 1024; i++) found += hook_iat(mods[i], dll, func, newfn, orig);
    hslog("IATALL %s!%s found=%d mods=%d", dll, func, found, n);
}

typedef struct { BYTE *target; BYTE saved[5]; } IH;
static IH g_ih_send, g_ih_recv, g_ih_wsasend, g_ih_wsarecv;

static void ih_install(IH *ih, void *target, void *handler) {
    if (!target) return;
    ih->target = (BYTE *)target;
    patch_jmp(ih->target, handler, ih->saved);
    hslog("IH install target=%08X handler=%08X", (DWORD)(DWORD_PTR)target, (DWORD)(DWORD_PTR)handler);
}
static void ih_restore(IH *ih) {
    DWORD old;
    if (!ih->target) return;
    if (VirtualProtect(ih->target, 5, PAGE_EXECUTE_READWRITE, &old)) {
        memcpy(ih->target, ih->saved, 5);
        VirtualProtect(ih->target, 5, old, &old);
        FlushInstructionCache(GetCurrentProcess(), ih->target, 5);
    }
}
static void ih_repatch(IH *ih, void *handler) {
    if (ih->target) patch_jmp(ih->target, handler, NULL);
}

static int WSAAPI hxi_send(SOCKET s, const char *b, int n, int f) {
    int r;
    static volatile LONG c;
    LONG k;
    ih_restore(&g_ih_send);
    r = ((Psend)g_ih_send.target)(s, b, n, f);
    ih_repatch(&g_ih_send, (void *)hxi_send);
    k = InterlockedIncrement(&c);
    if (b && n && (k < 3000 || n == 342 || n == 74)) {
        loghex("SEND", (const BYTE *)b, n < 48 ? n : 48);
        hslog("SEND len=%d r=%d n=%ld", n, r, k);
    }
    return r;
}
static int WSAAPI hxi_recv(SOCKET s, char *b, int n, int f) {
    int r;
    static volatile LONG c;
    LONG k;
    ih_restore(&g_ih_recv);
    r = ((Precv)g_ih_recv.target)(s, b, n, f);
    ih_repatch(&g_ih_recv, (void *)hxi_recv);
    k = InterlockedIncrement(&c);
    if (b && r > 0 && (k < 3000 || r == 342 || r == 74)) {
        loghex("RECV", (const BYTE *)b, r < 48 ? r : 48);
        hslog("RECV len=%d r=%d n=%ld", n, r, k);
    }
    return r;
}
static int WSAAPI hxi_wsasend(SOCKET s, LPWSABUF bufs, DWORD nbuf, LPDWORD sent, DWORD flags, LPWSAOVERLAPPED ov, LPWSAOVERLAPPED_COMPLETION_ROUTINE cr) {
    int r;
    static volatile LONG c;
    LONG k;
    ih_restore(&g_ih_wsasend);
    r = ((PWSASend)g_ih_wsasend.target)(s, bufs, nbuf, sent, flags, ov, cr);
    ih_repatch(&g_ih_wsasend, (void *)hxi_wsasend);
    k = InterlockedIncrement(&c);
    if (bufs && nbuf && bufs[0].buf && bufs[0].len && (k < 3000 || bufs[0].len == 342 || bufs[0].len == 74)) {
        loghex("WSASEND", (const BYTE *)bufs[0].buf, bufs[0].len < 48 ? bufs[0].len : 48);
        hslog("WSASEND len=%u r=%d n=%ld", bufs[0].len, r, k);
    }
    return r;
}
static int WSAAPI hxi_wsarecv(SOCKET s, LPWSABUF bufs, DWORD nbuf, LPDWORD recvd, LPDWORD flags, LPWSAOVERLAPPED ov, LPWSAOVERLAPPED_COMPLETION_ROUTINE cr) {
    int r;
    static volatile LONG c;
    DWORD got = recvd ? *recvd : 0;
    LONG k;
    ih_restore(&g_ih_wsarecv);
    r = ((PWSARecv)g_ih_wsarecv.target)(s, bufs, nbuf, recvd, flags, ov, cr);
    ih_repatch(&g_ih_wsarecv, (void *)hxi_wsarecv);
    k = InterlockedIncrement(&c);
    got = recvd ? *recvd : got;
    if (bufs && nbuf && bufs[0].buf && got && (k < 3000 || got == 342 || got == 74)) {
        loghex("WSARECV", (const BYTE *)bufs[0].buf, got < 48 ? got : 48);
        hslog("WSARECV got=%u r=%d n=%ld", got, r, k);
    }
    return r;
}

static int find_and_hook_cb(void) {
    static const BYTE sig[14] = {0x55,0x8B,0xEC,0x83,0xEC,0x1C,0x8B,0x45,0x08,0x89,0x45,0xF4,0x81,0x7D};
    DWORD addr = 0x400000;
    while (addr < 0x80000000) {
        MEMORY_BASIC_INFORMATION mbi;
        SIZE_T r = VirtualQuery((LPCVOID)(DWORD_PTR)addr, &mbi, sizeof(mbi));
        BYTE *b;
        SIZE_T i, n;
        if (!r) break;
        b = (BYTE *)mbi.BaseAddress;
        n = mbi.RegionSize;
        if (mbi.State == MEM_COMMIT && (mbi.Protect & (PAGE_EXECUTE|PAGE_EXECUTE_READ|PAGE_EXECUTE_READWRITE|PAGE_EXECUTE_WRITECOPY)) && (mbi.Protect & 0x02)) {
            for (i = 0; i + sizeof(sig) < n; i++) {
                if (b[i] == 0x55 && memcmp(b + i, sig, sizeof(sig)) == 0) {
                    g_cb_target = b + i;
                    g_orig_cb = (ORIG_CB)g_cb_target;
                    patch_jmp(g_cb_target, (void *)hook_cb, g_cb_saved);
                    g_cb_installed = 1;
                    hslog("CB lazy hook target=%08X saved=%02X %02X %02X %02X %02X", (DWORD)(DWORD_PTR)g_cb_target,
                        g_cb_saved[0], g_cb_saved[1], g_cb_saved[2], g_cb_saved[3], g_cb_saved[4]);
                    return 1;
                }
            }
        }
        addr = (DWORD)(DWORD_PTR)mbi.BaseAddress + (DWORD)mbi.RegionSize;
        if (addr <= (DWORD)(DWORD_PTR)mbi.BaseAddress) break;
    }
    return 0;
}

static DWORD WINAPI init_thread(LPVOID p) {
    char path[MAX_PATH];
    DWORD pid = GetCurrentProcessId();
    g_game = GetModuleHandleA(NULL);
    wsprintfA(path, "C:\\SHARE\\hwid\\re_hackshield\\logs\\hsmon6_%lu.log", pid);
    g_log = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    hslog("MON start pid=%lu game=%08X", pid, (DWORD)(DWORD_PTR)g_game);

    hook_all("KERNEL32.dll", "OutputDebugStringA", (void *)h_OutputDebugStringA, (void **)&o_OutputDebugStringA);
    hook_all("KERNEL32.dll", "LoadLibraryA", (void *)h_LoadLibraryA, (void **)&o_LoadLibraryA);
    hook_all("KERNEL32.dll", "CreateProcessA", (void *)h_CreateProcessA, (void **)&o_CreateProcessA);
    hook_all("KERNEL32.dll", "GetPrivateProfileStringA", (void *)h_GetPrivateProfileStringA, (void **)&o_GetPrivateProfileStringA);
    hook_all("USER32.dll", "MessageBoxA", (void *)h_MessageBoxA, (void **)&o_MessageBoxA);
    hook_all("ADVAPI32.dll", "RegQueryValueExA", (void *)h_RegQueryValueExA, (void **)&o_RegQueryValueExA);
    hook_all("NETAPI32.dll", "Netbios", (void *)h_Netbios, (void **)&o_Netbios);
    hook_all("WS2_32.dll", "gethostname", (void *)h_gethostname, (void **)&o_gethostname);
    hook_all("KERNEL32.dll", "GetSystemInfo", (void *)h_GetSystemInfo, (void **)&o_GetSystemInfo);
    hook_all("KERNEL32.dll", "GetDriveTypeA", (void *)h_GetDriveTypeA, (void **)&o_GetDriveTypeA);
    hook_all("KERNEL32.dll", "GetComputerNameExW", (void *)h_GetComputerNameExW, (void **)&o_GetComputerNameExW);
    hook_all("iphlpapi.dll", "GetAdaptersAddresses", (void *)h_GetAdaptersAddresses, (void **)&o_GetAdaptersAddresses);
    hook_all("USER32.dll", "SendInput", (void *)h_SendInput, (void **)&o_SendInput);
    hook_all("USER32.dll", "SetCursorPos", (void *)h_SetCursorPos, (void **)&o_SetCursorPos);
    hook_all("USER32.dll", "mouse_event", (void *)h_mouse_event, (void **)&o_mouse_event);
    hook_all("USER32.dll", "PostMessageA", (void *)h_PostMessageA, (void **)&o_PostMessageA);
    hook_all("USER32.dll", "GetAsyncKeyState", (void *)h_GetAsyncKeyState, (void **)&o_GetAsyncKeyState);
    hook_all("USER32.dll", "GetCursorPos", (void *)h_GetCursorPos, (void **)&o_GetCursorPos);
    hook_all("USER32.dll", "GetKeyState", (void *)h_GetKeyState, (void **)&o_GetKeyState);
    hook_all("WS2_32.dll", "send", (void *)h_send, (void **)&o_send);
    hook_all("WS2_32.dll", "recv", (void *)h_recv, (void **)&o_recv);
    hook_all("WS2_32.dll", "WSASend", (void *)h_WSASend, (void **)&o_WSASend);
    hook_all("WS2_32.dll", "WSARecv", (void *)h_WSARecv, (void **)&o_WSARecv);

    {
        HMODULE w = GetModuleHandleA("ws2_32.dll");
        if (w) {
            ih_install(&g_ih_send, (void *)GetProcAddress(w, "send"), (void *)hxi_send);
            ih_install(&g_ih_recv, (void *)GetProcAddress(w, "recv"), (void *)hxi_recv);
            ih_install(&g_ih_wsasend, (void *)GetProcAddress(w, "WSASend"), (void *)hxi_wsasend);
            ih_install(&g_ih_wsarecv, (void *)GetProcAddress(w, "WSARecv"), (void *)hxi_wsarecv);
        } else {
            hslog("IH ws2_32 not found");
        }
    }

    {
        IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)g_game;
        IMAGE_NT_HEADERS *nt = dos ? (IMAGE_NT_HEADERS *)((BYTE *)g_game + dos->e_lfanew) : NULL;
        DWORD imgsz = (nt && nt->Signature == IMAGE_NT_SIGNATURE) ? nt->OptionalHeader.SizeOfImage : 0;
        g_cb_target = (BYTE *)g_game + 0x731550;
        if (imgsz > 0x731560 && g_cb_target[0] == 0x55 && g_cb_target[1] == 0x8B && g_cb_target[2] == 0xEC) {
            g_orig_cb = (ORIG_CB)g_cb_target;
            patch_jmp(g_cb_target, (void *)hook_cb, g_cb_saved);
            g_cb_installed = 1;
            hslog("CB hook target=%08X saved=%02X %02X %02X %02X %02X", (DWORD)(DWORD_PTR)g_cb_target,
                g_cb_saved[0], g_cb_saved[1], g_cb_saved[2], g_cb_saved[3], g_cb_saved[4]);
        } else {
            hslog("CB hook skipped imgsz=%X bytes=%02X %02X %02X", imgsz, g_cb_target[0], g_cb_target[1], g_cb_target[2]);
            find_and_hook_cb();
        }
    }
    for (;;) {
        if (!g_cb_installed) find_and_hook_cb();
        Sleep(250);
    }
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
