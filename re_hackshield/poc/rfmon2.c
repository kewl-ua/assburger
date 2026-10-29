#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <winternl.h>
#include <wincrypt.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

static HANDLE g_log = INVALID_HANDLE_VALUE;
static CRITICAL_SECTION g_cs;
static DWORD g_rf_base, g_rf_end, g_game_base, g_game_end;
static volatile LONG g_init_done;
static int is_rf(void *ret) { DWORD r=(DWORD)(DWORD_PTR)ret; return g_rf_base && r>=g_rf_base && r<g_rf_end; }

static void hslog(const char *fmt, ...) {
    char buf[2048]; va_list ap; int n; DWORD wrote;
    if (g_log == INVALID_HANDLE_VALUE) return;
    va_start(ap, fmt); n = wvsprintfA(buf, fmt, ap); va_end(ap);
    if (n < 0) n = 0; if (n > (int)sizeof(buf) - 2) n = sizeof(buf) - 2;
    buf[n++] = '\r'; buf[n++] = '\n';
    EnterCriticalSection(&g_cs); WriteFile(g_log, buf, n, &wrote, NULL); LeaveCriticalSection(&g_cs);
}
static void loghex(const char *tag, const BYTE *p, int n) {
    char out[3*64+1]; int i,k=0;
    if (n > 48) n = 48;
    for (i=0;i<n;i++){ static const char *hx="0123456789abcdef"; out[k++]=hx[p[i]>>4]; out[k++]=hx[p[i]&15]; if(i+1<n) out[k++]=' '; }
    out[k]=0; hslog("%s len=%d [%s]", tag, n, out);
}
static void logcall(const char *api, void *ret, const char *extra) {
    DWORD r=(DWORD)(DWORD_PTR)ret;
    int rf=(g_rf_base && r>=g_rf_base && r<g_rf_end);
    int gm=(g_game_base && r>=g_game_base && r<g_game_end);
    hslog("%s caller=%08X%s%s %s", api, r, rf?" RF":"", gm?" GAME":"", extra?extra:"");
}

static int hook_iat(HMODULE mod, const char *dll, const char *func, void *newfn, void **orig) {
    IMAGE_DOS_HEADER *dos; IMAGE_NT_HEADERS *nt; IMAGE_IMPORT_DESCRIPTOR *imp;
    if (!mod) return 0;
    dos=(IMAGE_DOS_HEADER*)mod; if (dos->e_magic!=IMAGE_DOS_SIGNATURE) return 0;
    nt=(IMAGE_NT_HEADERS*)((BYTE*)mod+dos->e_lfanew); if (nt->Signature!=IMAGE_NT_SIGNATURE) return 0;
    imp=(IMAGE_IMPORT_DESCRIPTOR*)((BYTE*)mod+nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress);
    for (; imp->Name; imp++) {
        const char *dn=(const char*)((BYTE*)mod+imp->Name);
        IMAGE_THUNK_DATA *thunk,*ot;
        if (_stricmp(dn,dll)!=0) continue;
        thunk=(IMAGE_THUNK_DATA*)((BYTE*)mod+imp->FirstThunk);
        ot=imp->OriginalFirstThunk?(IMAGE_THUNK_DATA*)((BYTE*)mod+imp->OriginalFirstThunk):thunk;
        for (; thunk->u1.Function; thunk++,ot++) {
            IMAGE_IMPORT_BY_NAME *ibn; DWORD old;
            if (ot->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;
            ibn=(IMAGE_IMPORT_BY_NAME*)((BYTE*)mod+ot->u1.AddressOfData);
            if (strcmp((const char*)ibn->Name,func)!=0) continue;
            if (orig) *orig=(void*)thunk->u1.Function;
            if (VirtualProtect(&thunk->u1.Function,sizeof(ULONG_PTR),PAGE_READWRITE,&old)) {
                thunk->u1.Function=(ULONG_PTR)newfn;
                VirtualProtect(&thunk->u1.Function,sizeof(ULONG_PTR),old,&old);
            }
            return 1;
        }
    }
    return 0;
}
static void hook_all(const char *dll, const char *func, void *newfn, void **orig) {
    HMODULE mods[1024]; DWORD need=0; int n,i,found=0;
    if (!EnumProcessModules(GetCurrentProcess(),mods,sizeof(mods),&need)) return;
    n=need/sizeof(HMODULE);
    for (i=0;i<n && i<1024;i++) found+=hook_iat(mods[i],dll,func,newfn,orig);
    hslog("IATALL %s!%s found=%d mods=%d",dll,func,found,n);
}

typedef LONG (WINAPI *PRegQueryValueExW)(HKEY,LPCWSTR,LPDWORD,LPDWORD,LPBYTE,LPDWORD);
static PRegQueryValueExW o_RQVW;
static LONG WINAPI h_RQVW(HKEY hk,LPCWSTR name,LPDWORD res,LPDWORD type,LPBYTE data,LPDWORD cb) {
    LONG r=o_RQVW(hk,name,res,type,data,cb);
    char n[256]; n[0]=0;
    if (name) WideCharToMultiByte(CP_ACP,0,name,-1,n,sizeof(n),0,0);
    logcall("RegQueryValueExW",__builtin_return_address(0),n);
    if (r==0 && data && type && (*type==REG_SZ||*type==REG_EXPAND_SZ) && cb && *cb>0) {
        char v[256]; DWORD k=*cb; if(k>255)k=255; memcpy(v,data,k); v[k]=0;
        hslog("  value '%s'", v);
    } else if (r==0 && data && cb && *cb<=64) loghex("  data",data,*cb);
    return r;
}
typedef LONG (WINAPI *PRegQueryValueExA)(HKEY,LPCSTR,LPDWORD,LPDWORD,LPBYTE,LPDWORD);
static PRegQueryValueExA o_RQVA;
static LONG WINAPI h_RQVA(HKEY hk,LPCSTR name,LPDWORD res,LPDWORD type,LPBYTE data,LPDWORD cb) {
    LONG r=o_RQVA(hk,name,res,type,data,cb);
    logcall("RegQueryValueExA",__builtin_return_address(0),name?name:"");
    if (r==0 && data && type && (*type==REG_SZ||*type==REG_EXPAND_SZ) && cb && *cb>0) {
        char v[256]; DWORD k=*cb; if(k>255)k=255; memcpy(v,data,k); v[k]=0;
        hslog("  value '%s'", v);
    } else if (r==0 && data && cb && *cb<=64) loghex("  data",data,*cb);
    return r;
}
typedef LONG (WINAPI *PRegOpenKeyExA)(HKEY,LPCSTR,DWORD,REGSAM,PHKEY);
static PRegOpenKeyExA o_ROKA;
static LONG WINAPI h_ROKA(HKEY hk,LPCSTR sub,DWORD opt,REGSAM sam,PHKEY out) {
    LONG r=o_ROKA(hk,sub,opt,sam,out);
    logcall("RegOpenKeyExA",__builtin_return_address(0),sub?sub:"");
    return r;
}

typedef LONG (WINAPI *PRegOpenKeyExW)(HKEY,LPCWSTR,DWORD,REGSAM,PHKEY);
static PRegOpenKeyExW o_ROKW;
static LONG WINAPI h_ROKW(HKEY hk,LPCWSTR sub,DWORD opt,REGSAM sam,PHKEY out) {
    LONG r=o_ROKW(hk,sub,opt,sam,out);
    char n[512]; n[0]=0; if(sub) WideCharToMultiByte(CP_ACP,0,sub,-1,n,sizeof(n),0,0);
    logcall("RegOpenKeyExW",__builtin_return_address(0),n);
    return r;
}

typedef BOOL (WINAPI *PK32Enum)(HANDLE,HMODULE*,DWORD,LPDWORD);
static PK32Enum o_K32Enum;
static BOOL WINAPI h_K32Enum(HANDLE p,HMODULE *mods,DWORD cb,LPDWORD need) {
    BOOL r=o_K32Enum(p,mods,cb,need);
    char e[64]; wsprintfA(e,"need=%u",need?*need:0);
    logcall("K32EnumProcessModules",__builtin_return_address(0),e);
    return r;
}
typedef BOOL (WINAPI *PEnum)(HANDLE,HMODULE*,DWORD,LPDWORD);
static PEnum o_Enum;
static BOOL WINAPI h_Enum(HANDLE p,HMODULE *mods,DWORD cb,LPDWORD need) {
    BOOL r=o_Enum(p,mods,cb,need);
    char e[64]; wsprintfA(e,"need=%u",need?*need:0);
    logcall("EnumProcessModules",__builtin_return_address(0),e);
    return r;
}
typedef SIZE_T (WINAPI *PVQ)(LPCVOID,PMEMORY_BASIC_INFORMATION,SIZE_T);
static PVQ o_VQ;
static SIZE_T WINAPI h_VQ(LPCVOID a,PMEMORY_BASIC_INFORMATION m,SIZE_T n) {
    SIZE_T r=o_VQ(a,m,n);
    char e[128]; wsprintfA(e,"addr=%08X size=%u prot=%08X",(DWORD)(DWORD_PTR)a,m?m->RegionSize:0,m?m->Protect:0);
    logcall("VirtualQuery",__builtin_return_address(0),e);
    return r;
}
typedef BOOL (WINAPI *PRPM)(HANDLE,LPCVOID,LPVOID,SIZE_T,SIZE_T*);
static PRPM o_RPM;
static BOOL WINAPI h_RPM(HANDLE p,LPCVOID a,LPVOID b,SIZE_T n,SIZE_T *got) {
    BOOL r=o_RPM(p,a,b,n,got);
    char e[128]; wsprintfA(e,"addr=%08X size=%u got=%u",(DWORD)(DWORD_PTR)a,n,got?*got:0);
    logcall("ReadProcessMemory",__builtin_return_address(0),e);
    return r;
}
typedef HANDLE (WINAPI *PCT32)(DWORD,DWORD);
static PCT32 o_CT32;
static HANDLE WINAPI h_CT32(DWORD flags,DWORD pid) {
    HANDLE r=o_CT32(flags,pid);
    char e[64]; wsprintfA(e,"flags=%X pid=%u",flags,pid);
    logcall("CreateToolhelp32Snapshot",__builtin_return_address(0),e);
    return r;
}
typedef NTSTATUS (NTAPI *PNQIP)(HANDLE,ULONG,PVOID,ULONG,PULONG);
static PNQIP o_NQIP;
static NTSTATUS NTAPI h_NQIP(HANDLE p,ULONG cls,PVOID buf,ULONG len,PULONG ret) {
    NTSTATUS r=o_NQIP(p,cls,buf,len,ret);
    char e[64]; wsprintfA(e,"class=%u",cls);
    logcall("NtQueryInformationProcess",__builtin_return_address(0),e);
    return r;
}
typedef BOOL (WINAPI *PIDP)(void);
static PIDP o_IDP;
static BOOL WINAPI h_IDP(void) {
    BOOL r=o_IDP();
    logcall("IsDebuggerPresent",__builtin_return_address(0),r?"1":"0");
    return r;
}

typedef BOOL (WINAPI *PCHD)(HCRYPTHASH,const BYTE*,DWORD,DWORD);
static PCHD o_CHD;
static BOOL WINAPI h_CHD(HCRYPTHASH h,const BYTE *d,DWORD n,DWORD flags) {
    BOOL r=o_CHD(h,d,n,flags);
    char e[64]; wsprintfA(e,"len=%u",n);
    logcall("CryptHashData",__builtin_return_address(0),e);
    if (d && n) loghex("  hashdata",d,n<32?n:32);
    return r;
}
typedef BOOL (WINAPI *PCGHP)(HCRYPTHASH,DWORD,BYTE*,DWORD*,DWORD);
static PCGHP o_CGHP;
static BOOL WINAPI h_CGHP(HCRYPTHASH h,DWORD param,BYTE *data,DWORD *cb,DWORD flags) {
    BOOL r=o_CGHP(h,param,data,cb,flags);
    char e[64]; wsprintfA(e,"param=%u cb=%u",param,cb?*cb:0);
    logcall("CryptGetHashParam",__builtin_return_address(0),e);
    if (r && data && cb && *cb<=64) loghex("  hash",data,*cb);
    return r;
}

typedef SHORT (WINAPI *PGKS)(int);
static PGKS o_GKS;
static SHORT WINAPI h_GKS(int vk) { SHORT r=o_GKS(vk); if (is_rf(__builtin_return_address(0))) { char e[32]; wsprintfA(e,"vk=%X r=%04X",vk,(unsigned short)r); logcall("GetKeyState",__builtin_return_address(0),e);} return r; }
typedef SHORT (WINAPI *PGAS)(int);
static PGAS o_GAS;
static SHORT WINAPI h_GAS(int vk) { SHORT r=o_GAS(vk); if (is_rf(__builtin_return_address(0))) { char e[32]; wsprintfA(e,"vk=%X r=%04X",vk,(unsigned short)r); logcall("GetAsyncKeyState",__builtin_return_address(0),e);} return r; }
typedef BOOL (WINAPI *PPM)(HWND,UINT,WPARAM,LPARAM);
static PPM o_PMA, o_PMW;
static BOOL WINAPI h_PMA(HWND h,UINT m,WPARAM w,LPARAM l) { BOOL r=o_PMA(h,m,w,l); if(m>=WM_KEYFIRST&&m<=WM_KEYLAST) { char e[96]; wsprintfA(e,"msg=%X w=%X l=%X",m,(DWORD)w,(DWORD)l); logcall("PostMessageA",__builtin_return_address(0),e);} return r; }
static BOOL WINAPI h_PMW(HWND h,UINT m,WPARAM w,LPARAM l) { BOOL r=o_PMW(h,m,w,l); if(m>=WM_KEYFIRST&&m<=WM_KEYLAST) { char e[96]; wsprintfA(e,"msg=%X w=%X l=%X",m,(DWORD)w,(DWORD)l); logcall("PostMessageW",__builtin_return_address(0),e);} return r; }

static void find_modules(void) {
    HMODULE mods[1024]; DWORD need=0; int n,i; wchar_t path[1024];
    if (!EnumProcessModules(GetCurrentProcess(),mods,sizeof(mods),&need)) return;
    n=need/sizeof(HMODULE);
    for (i=0;i<n && i<1024;i++) {
        MODULEINFO mi; char a[1024];
        if (!GetModuleInformation(GetCurrentProcess(),mods[i],&mi,sizeof(mi))) continue;
        if (!GetModuleFileNameExW(GetCurrentProcess(),mods[i],path,1024)) continue;
        WideCharToMultiByte(CP_ACP,0,path,-1,a,sizeof(a),0,0);
        if (strstr(a,"RFOCliMod")) { g_rf_base=(DWORD)(DWORD_PTR)mi.lpBaseOfDll; g_rf_end=g_rf_base+mi.SizeOfImage; hslog("RFOCliMod base=%08X end=%08X path=%s",g_rf_base,g_rf_end,a); }
        if (!g_game_base && strstr(a,"RF_Online_4gb.bin")) { g_game_base=(DWORD)(DWORD_PTR)mi.lpBaseOfDll; g_game_end=g_game_base+mi.SizeOfImage; hslog("game base=%08X end=%08X",g_game_base,g_game_end); }
    }
}

static DWORD WINAPI late_find(LPVOID p) {
    Sleep(2500);
    find_modules();
    hslog("late find rf_base=%08X rf_end=%08X",g_rf_base,g_rf_end);
    return 0;
}

static DWORD WINAPI init_thread(LPVOID p) {
    char path[MAX_PATH]; DWORD pid=GetCurrentProcessId();
    wsprintfA(path,"C:\\SHARE\\hwid\\re_hackshield\\logs\\rfmon2_%lu.log",pid);
    g_log=CreateFileA(path,FILE_APPEND_DATA,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
    hslog("RFMON start pid=%lu",pid);
    find_modules();
    hook_all("ADVAPI32.dll","RegQueryValueExW",(void*)h_RQVW,(void**)&o_RQVW);
    hook_all("ADVAPI32.dll","RegOpenKeyExW",(void*)h_ROKW,(void**)&o_ROKW);
    hook_all("ADVAPI32.dll","RegQueryValueExA",(void*)h_RQVA,(void**)&o_RQVA);
    hook_all("ADVAPI32.dll","RegOpenKeyExA",(void*)h_ROKA,(void**)&o_ROKA);
    hook_all("KERNEL32.dll","K32EnumProcessModules",(void*)h_K32Enum,(void**)&o_K32Enum);
    hook_all("PSAPI.dll","EnumProcessModules",(void*)h_Enum,(void**)&o_Enum);
    hook_all("KERNEL32.dll","VirtualQuery",(void*)h_VQ,(void**)&o_VQ);
    hook_all("KERNEL32.dll","ReadProcessMemory",(void*)h_RPM,(void**)&o_RPM);
    hook_all("KERNEL32.dll","CreateToolhelp32Snapshot",(void*)h_CT32,(void**)&o_CT32);
    hook_all("ntdll.dll","NtQueryInformationProcess",(void*)h_NQIP,(void**)&o_NQIP);
    hook_all("KERNEL32.dll","IsDebuggerPresent",(void*)h_IDP,(void**)&o_IDP);
    hook_all("ADVAPI32.dll","CryptHashData",(void*)h_CHD,(void**)&o_CHD);
    hook_all("ADVAPI32.dll","CryptGetHashParam",(void*)h_CGHP,(void**)&o_CGHP);
    hook_all("USER32.dll","GetKeyState",(void*)h_GKS,(void**)&o_GKS);
    hook_all("USER32.dll","GetAsyncKeyState",(void*)h_GAS,(void**)&o_GAS);
    hook_all("USER32.dll","PostMessageA",(void*)h_PMA,(void**)&o_PMA);
    hook_all("USER32.dll","PostMessageW",(void*)h_PMW,(void**)&o_PMW);
    InterlockedExchange(&g_init_done,1);
    hslog("RFMON hooks installed");
    CreateThread(NULL,0,late_find,NULL,0,NULL);
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID r) {
    if (reason == DLL_PROCESS_ATTACH) { InitializeCriticalSection(&g_cs); DisableThreadLibraryCalls(h); CreateThread(NULL,0,init_thread,NULL,0,NULL); }
    return TRUE;
}
