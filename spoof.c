/*
 * spoof.dll - per-process HWID spoofer for CERBERUS-GAMES.exe.
 *
 * Injected into the LAUNCHER process (no anti-cheat there), it IAT-hooks the few Win32 APIs the
 * launcher uses to build a HWID and returns per-instance fake values. The real PC is untouched,
 * so several launcher windows on one PC each see a different "machine".
 *
 * Instance id comes from the env var SPOOF_ID (set by the run wrapper). Values are derived from it.
 * Optional log file: env SPOOF_LOG.
 *
 * Build (MinGW): gcc -shared -O2 -o spoof.dll spoof.c -lkernel32 -luser32
 */
#define WINVER 0x0601
#define _WIN32_WINNT 0x0601
#define _WINSOCKAPI_
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <iphlpapi.h>
#include <tlhelp32.h>
#include <winnls.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>

#ifndef GeoISOString
#define GeoISOString 23
#endif
#ifndef PRODUCT_PROFESSIONAL
#define PRODUCT_PROFESSIONAL 48
#endif
#ifndef WSAID_CONNECTEX
static const GUID _wsaid_connectex = { 0x25a207b9, 0xddf3, 0x4660, { 0x8e, 0xe9, 0x76, 0xe5, 0x8c, 0x74, 0x06, 0x3e } };
#define WSAID_CONNECTEX _wsaid_connectex
#endif
static void logline(const char *fmt, ...);

typedef BOOL (WINAPI *PCGVIW)(LPCWSTR, LPWSTR, DWORD, LPDWORD, LPDWORD, LPDWORD, LPWSTR, DWORD);
typedef BOOL (WINAPI *PCGCNW)(LPWSTR, LPDWORD);
typedef BOOL (WINAPI *PGetVersionExW)(LPOSVERSIONINFOW);
typedef BOOL (WINAPI *PGetProductInfo)(DWORD, DWORD, DWORD, DWORD, PDWORD);
typedef INT  (WINAPI *PGetGeoInfoW)(UINT, GEOTYPE, LPWSTR, int, LANGID);

static PCGVIW     o_GetVolumeInformationW;
static PCGCNW     o_GetComputerNameW;
static PGetVersionExW o_GetVersionExW;
static PGetProductInfo o_GetProductInfo;
static PGetGeoInfoW  o_GetGeoInfoW;

/* ---- extra HWID surfaces (SMBIOS, disk serial, monitors, host, RAM) ---- */
typedef LONG (WINAPI *PNtQSI)(ULONG, PVOID, ULONG, PULONG);
typedef DWORD (WINAPI *PGetSystemFirmwareTable)(DWORD, DWORD, PVOID, DWORD);
typedef BOOL (WINAPI *PEnumSystemFirmwareTables)(DWORD, PVOID, DWORD);
typedef BOOL (WINAPI *PDeviceIoControl)(HANDLE, DWORD, PVOID, DWORD, PVOID, DWORD, LPDWORD, LPOVERLAPPED);
typedef BOOL (WINAPI *PEnumDisplayDevicesW)(LPCWSTR, DWORD, PVOID, DWORD);
typedef BOOL (WINAPI *PSetupDiGetDeviceRegistryPropertyW)(HANDLE, PVOID, DWORD, PDWORD, PBYTE, DWORD, PDWORD);
typedef BOOL (WINAPI *PGlobalMemoryStatusEx)(PVOID);
typedef int  (WINAPI *PGetHostNameW)(PWCHAR, int);
typedef BOOL (WINAPI *PSetupDiGetDeviceRegistryPropertyW)(void *, void *, DWORD, PDWORD, PBYTE, DWORD, PDWORD);
static PSetupDiGetDeviceRegistryPropertyW o_SetupDiGetDeviceRegistryPropertyW;
typedef BOOL (WINAPI *PGetFileInformationByHandle)(HANDLE, PVOID);
static PGetFileInformationByHandle o_GetFileInformationByHandle;
typedef BOOL (WINAPI *PGetUserNameW)(LPWSTR, LPDWORD);
static PGetUserNameW o_GetUserNameW;
static WCHAR g_username[64];

/* CreateFileW redirect for the hidden HWID marker file (ProgramData\Microsoft\DeviceSync\vcredist_x86.exe) */
typedef HANDLE (WINAPI *PCreateFileW)(LPCWSTR, DWORD, DWORD, PVOID, DWORD, DWORD, HANDLE);
static PCreateFileW o_CreateFileW;
static WCHAR g_metaPath[MAX_PATH];  /* per-profile marker file (kept for reference) */
static WCHAR g_metaDir[MAX_PATH];  /* per-profile directory that replaces ...\DeviceSync\ */
static WCHAR g_metaTail[64];

static PNtQSI    o_NtQSI;
static PGetSystemFirmwareTable o_GetSystemFirmwareTable;
static PEnumSystemFirmwareTables o_EnumSystemFirmwareTables;
static PDeviceIoControl o_DeviceIoControl;
static PEnumDisplayDevicesW o_EnumDisplayDevicesW;
static PGlobalMemoryStatusEx o_GlobalMemoryStatusEx;
static PGetHostNameW o_GetHostNameW;

static int g_smbios = 1, g_disk = 1, g_mon = 1, g_host = 1, g_ram = 1;
static int g_nocex = 0;  /* test: disable ConnectEx inline hook */
static int g_noinline = 0;/* test: disable connect/WSAConnect inline hooks (keep IAT) */
static int g_nogpa = 0;   /* test: do not hook GetProcAddress */
static int g_noiat = 0;   /* test: do not IAT-hook connect/WSAConnect/ConnectEx */
static int g_nohooks = 0; /* test: map the module, install no hooks at all */
static int g_proxyMain = 0; /* 1 = also proxy the browser/main process (may freeze UI) */

static DWORD g_serial;
static WCHAR g_name[64];
static DWORD g_build;

static char g_logPath[MAX_PATH];
static char g_cfgPath[MAX_PATH];
static char g_cfgId[32] = "1";
static char g_cfgProxy[192];
static HMODULE g_hself;
/* manual-map: the mapper passes "<dll path>\0<cfg path>\0" as `reserved`; GetModuleFileNameA
   fails for an unlinked module, so keep the paths here. */
static char g_reservedPath[MAX_PATH];
static char g_reservedCfg[MAX_PATH];

/* one live copy per process: a named mutex + a small status block the loader/guard can poll */
#define RFS_STATE_MAGIC   0x31534652u   /* "RFS1" */
#define RFS_STATE_VERSION 1
typedef struct {
  DWORD magic;
  DWORD version;
  DWORD pid;
  DWORD tick;
  DWORD ready;
  DWORD hooks;
  DWORD cfgLen;
  char  cfg[MAX_PATH];
} RFS_STATE;
static HANDLE  g_stateMutex;
static HANDLE  g_stateMap;
static RFS_STATE *g_stateView;
static int     g_alreadyPresent;
static int g_min;
static int g_net = 1, g_reg = 1, g_extra = 1, g_macOn = 1, g_ver = 1, g_prod = 1, g_geo = 1, g_delay = 1;
static int g_rega = 0;  /* RegQueryValueExA hook (off by default; CEF uses the W variant) */
static int g_vol = 1, g_cname = 1;
static int g_reghw = 1;  /* reg hook also substitutes BIOS/board/etc (not just MachineGuid) */
static int g_regsub = 1; /* actually substitute values in RegQueryValueExW (else just pass through) */
static DWORD g_t0;

/* ---- raw hardware overrides from cfg (empty = derive from id) ---- */
static char g_cfgSerial[16];   /* 8 hex digits, e.g. 1A2B3C4D */
static char g_cfgName[64];    /* computer name */
static char g_cfgMac[32];     /* AA:BB:CC:DD:EE:FF or AABBCCDDEEFF */
static char g_cfgGuid[64];    /* MachineGuid */
static char g_cfgBiosVendor[64];
static char g_cfgBiosVer[32];
static char g_cfgBoardMfr[64];
static char g_cfgBoardProd[64];
static char g_cfgSysMfr[64];
static char g_cfgSysProd[64];
static char g_cfgSysVer[32];
static char g_cfgMonId[64];
static char g_cfgDiskSerial[64];
static char g_cfgCpu[96];
static int g_cfgBuild;
static int g_serialOverride, g_nameOverride, g_macOverride, g_guidOverride;

/* extra HWID values */
static char g_cfgBiosSerial[64];
static char g_cfgUuid[40];    /* SMBIOS system UUID */
static char g_cfgBoardSerial[64];
static char g_cfgRamMb[16];   /* total RAM in MB */
static WCHAR g_biosSerialW[64], g_uuidW[40], g_boardSerialW[64];
static ULONGLONG g_ramBytes;

static void logline(const char *fmt, ...);
static void logfirst(const char *fn)
{
  logline("spoof: FIRST read %s at +%lums after injection", fn, (unsigned long)(GetTickCount() - g_t0));
}

static void logline(const char *fmt, ...)
{
  FILE *f;
  if (!g_logPath[0]) return;
  f = fopen(g_logPath, "a");
  if (!f) return;
  va_list ap; va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap);
  fputc('\n', f); fclose(f);
}

static void append_cfg_suffix(char *path, size_t cap, const char *suffix)
{
  size_t n = strlen(path);
  if (n + strlen(suffix) + 1 < cap) strcat(path, suffix);
}

/* directory part of a path, with a trailing backslash; empty if there is none */
static void dir_of(const char *path, char *out, size_t cap)
{
  char *s;
  out[0] = 0;
  if (!path || !path[0]) return;
  strncpy(out, path, cap - 1); out[cap - 1] = 0;
  s = strrchr(out, '\\');
  if (s) s[1] = 0; else out[0] = 0;
}

/* cfg path next to a DLL: foo.dll -> foo.cfg (the old LoadLibrary contract) */
static void cfg_from_dll(const char *dll, char *out, size_t cap)
{
  size_t n;
  out[0] = 0;
  if (!dll || !dll[0]) return;
  strncpy(out, dll, cap - 1); out[cap - 1] = 0;
  n = strlen(out);
  if (n > 4 && !_stricmp(out + n - 4, ".dll")) { out[n - 3] = 0; strcat(out, "cfg"); }
}

static int load_cfg_file(const char *cfg)
{
  char line[256];
  FILE *f;
  if (!cfg || !cfg[0]) return 0;
  f = fopen(cfg, "r");
  if (!f) return 0;
  strncpy(g_cfgPath, cfg, MAX_PATH - 1); g_cfgPath[MAX_PATH - 1] = 0;
  while (fgets(line, sizeof(line), f)) {
    char *p = line; while (*p == ' ' || *p == '\t') p++;
    char *e = p + strlen(p); while (e > p && (e[-1] == '\n' || e[-1] == '\r')) *--e = 0;
    if (!strncmp(p, "id=", 3))     { strncpy(g_cfgId, p + 3, sizeof(g_cfgId) - 1); g_cfgId[sizeof(g_cfgId) - 1] = 0; }
    else if (!strncmp(p, "proxy=", 6)) { strncpy(g_cfgProxy, p + 6, sizeof(g_cfgProxy) - 1); g_cfgProxy[sizeof(g_cfgProxy) - 1] = 0; }
    else if (!strncmp(p, "log=", 4))  { strncpy(g_logPath, p + 4, MAX_PATH - 1); g_logPath[MAX_PATH - 1] = 0; }
    else if (!strncmp(p, "min=", 4))  { g_min = atoi(p + 4); }
    else if (!strncmp(p, "net=", 4))  { g_net = atoi(p + 4); }
    else if (!strncmp(p, "nohooks=", 8)) { g_nohooks = atoi(p + 8); }
    else if (!strncmp(p, "reg=", 4))  { g_reg = atoi(p + 4); }
    else if (!strncmp(p, "rega=", 5)) { g_rega = atoi(p + 5); }
    else if (!strncmp(p, "vol=", 4))  { g_vol = atoi(p + 4); }
    else if (!strncmp(p, "name=", 5)) { g_cname = atoi(p + 5); }
    else if (!strncmp(p, "reghw=", 6)) { g_reghw = atoi(p + 6); }
    else if (!strncmp(p, "regsub=", 7)){ g_regsub = atoi(p + 7); }
    else if (!strncmp(p, "smbios=", 7)){ g_smbios = atoi(p + 7); }
    else if (!strncmp(p, "nocex=", 6)) { g_nocex = atoi(p + 6); }
    else if (!strncmp(p, "noinline=", 9)) { g_noinline = atoi(p + 9); }
    else if (!strncmp(p, "nogpa=", 6)) { g_nogpa = atoi(p + 6); }
    else if (!strncmp(p, "noiat=", 6)) { g_noiat = atoi(p + 6); }
    else if (!strncmp(p, "proxymain=", 10)) { g_proxyMain = atoi(p + 10); }
    else if (!strncmp(p, "disk=", 5)) { g_disk = atoi(p + 5); }
    else if (!strncmp(p, "mon=", 4))  { g_mon = atoi(p + 4); }
    else if (!strncmp(p, "host=", 5)) { g_host = atoi(p + 5); }
    else if (!strncmp(p, "ram=", 4))  { g_ram = atoi(p + 4); }
    else if (!strncmp(p, "extra=", 6)) { g_extra = atoi(p + 6); }
    else if (!strncmp(p, "mac=", 4))  { g_macOn = atoi(p + 4); }
    else if (!strncmp(p, "ver=", 4))  { g_ver = atoi(p + 4); }
    else if (!strncmp(p, "prod=", 5)) { g_prod = atoi(p + 5); }
    else if (!strncmp(p, "geo=", 4))  { g_geo = atoi(p + 4); }
    else if (!strncmp(p, "delay=", 6)) { g_delay = atoi(p + 6); }
    else if (!strncmp(p, "serial=", 7)){ strncpy(g_cfgSerial, p + 7, sizeof(g_cfgSerial) - 1); g_serialOverride = 1; }
    else if (!strncmp(p, "cname=", 6)) { strncpy(g_cfgName, p + 6, sizeof(g_cfgName) - 1); g_nameOverride = 1; }
    else if (!strncmp(p, "macaddr=", 8)){ strncpy(g_cfgMac, p + 8, sizeof(g_cfgMac) - 1); g_macOverride = 1; }
    else if (!strncmp(p, "guid=", 5)) { strncpy(g_cfgGuid, p + 5, sizeof(g_cfgGuid) - 1); g_guidOverride = 1; }
    else if (!strncmp(p, "biosvendor=", 11)) { strncpy(g_cfgBiosVendor, p + 11, sizeof(g_cfgBiosVendor) - 1); }
    else if (!strncmp(p, "biosver=", 8))   { strncpy(g_cfgBiosVer, p + 8, sizeof(g_cfgBiosVer) - 1); }
    else if (!strncmp(p, "boardmfr=", 9))  { strncpy(g_cfgBoardMfr, p + 9, sizeof(g_cfgBoardMfr) - 1); }
    else if (!strncmp(p, "boardprod=", 10)) { strncpy(g_cfgBoardProd, p + 10, sizeof(g_cfgBoardProd) - 1); }
    else if (!strncmp(p, "sysmfr=", 7))   { strncpy(g_cfgSysMfr, p + 7, sizeof(g_cfgSysMfr) - 1); }
    else if (!strncmp(p, "sysprod=", 8))   { strncpy(g_cfgSysProd, p + 8, sizeof(g_cfgSysProd) - 1); }
    else if (!strncmp(p, "sysver=", 7))   { strncpy(g_cfgSysVer, p + 7, sizeof(g_cfgSysVer) - 1); }
    else if (!strncmp(p, "monid=", 6))    { strncpy(g_cfgMonId, p + 6, sizeof(g_cfgMonId) - 1); }
    else if (!strncmp(p, "diskserial=", 11)) { strncpy(g_cfgDiskSerial, p + 11, sizeof(g_cfgDiskSerial) - 1); }
    else if (!strncmp(p, "biosserial=", 11)) { strncpy(g_cfgBiosSerial, p + 11, sizeof(g_cfgBiosSerial) - 1); }
    else if (!strncmp(p, "boardserial=", 12)){ strncpy(g_cfgBoardSerial, p + 12, sizeof(g_cfgBoardSerial) - 1); }
    else if (!strncmp(p, "uuid=", 5))    { strncpy(g_cfgUuid, p + 5, sizeof(g_cfgUuid) - 1); }
    else if (!strncmp(p, "rammb=", 6))   { strncpy(g_cfgRamMb, p + 6, sizeof(g_cfgRamMb) - 1); }
    else if (!strncmp(p, "meta=", 5))    { MultiByteToWideChar(CP_UTF8, 0, p + 5, -1, g_metaPath, MAX_PATH - 1); g_metaPath[MAX_PATH - 1] = 0; }
    else if (!strncmp(p, "metadir=", 8))   { MultiByteToWideChar(CP_UTF8, 0, p + 8, -1, g_metaDir, MAX_PATH - 1); g_metaDir[MAX_PATH - 1] = 0; }
    else if (!strncmp(p, "cpu=", 4))     { strncpy(g_cfgCpu, p + 4, sizeof(g_cfgCpu) - 1); }
    else if (!strncmp(p, "build=", 6))    { g_cfgBuild = atoi(p + 6); }
  }
  fclose(f);
  return 1;
}

/* config from env / reserved / <modulename>.cfg / a profile sidecar. Manual map has no PEB entry,
   so `reserved` and the env are the only reliable sources; never depend on GetModuleFileNameA alone. */
static void LoadCfg(void)
{
  char cand[MAX_PATH], self[MAX_PATH];
  int got = 0;

  if (GetEnvironmentVariableA("SPOOF_ID", g_cfgId, sizeof(g_cfgId))) { }
  if (GetEnvironmentVariableA("SPOOF_PROXY", g_cfgProxy, sizeof(g_cfgProxy))) { }
  GetEnvironmentVariableA("SPOOF_LOG", g_logPath, sizeof(g_logPath));

  /* 1) per-process cfg passed by the mapper (reserved second string) */
  if (g_reservedCfg[0]) got |= load_cfg_file(g_reservedCfg);
#ifdef NETONLY
  /* 2) the launcher/CEF net-only cfg */
  if (!got && GetEnvironmentVariableA("SPOOF_NET_CFG", cand, MAX_PATH)) got |= load_cfg_file(cand);
#endif
  /* 3) the per-instance cfg from the environment */
  if (!got && GetEnvironmentVariableA("SPOOF_CFG", cand, MAX_PATH)) got |= load_cfg_file(cand);
  /* 4) cfg next to the DLL path the mapper passed */
  if (!got && g_reservedPath[0]) {
    cfg_from_dll(g_reservedPath, cand, MAX_PATH); got |= load_cfg_file(cand);
  }
  /* 5) cfg next to the real module (LoadLibrary / a loader that kept the PEB entry) */
  if (!got && g_hself && GetModuleFileNameA(g_hself, self, MAX_PATH)) {
    cfg_from_dll(self, cand, MAX_PATH); got |= load_cfg_file(cand);
  }
  /* 6) a profile sidecar: <dir>\rfspoof.cfg, then the historical C:\SHARE\hwid\spoof_<id>.cfg */
  if (!got && g_reservedPath[0]) {
    strncpy(cand, g_reservedPath, MAX_PATH - 1); cand[MAX_PATH - 1] = 0;
    { char *s = strrchr(cand, '\\'); if (s) { s[1] = 0; append_cfg_suffix(cand, MAX_PATH, "rfspoof.cfg"); got |= load_cfg_file(cand); } }
  }
  if (!got && g_reservedPath[0]) {
    char dir[MAX_PATH];
    dir_of(g_reservedPath, dir, MAX_PATH);
    if (dir[0]) {
      wsprintfA(cand, "%sspoof_%s.cfg", dir, g_cfgId);
      got |= load_cfg_file(cand);
    }
  }
  if (!got && g_reservedPath[0]) {
    char dir[MAX_PATH];
    dir_of(g_reservedPath, dir, MAX_PATH);
    if (dir[0]) {
      wsprintfA(cand, "%srfspoof.cfg", dir);
      got |= load_cfg_file(cand);
    }
  }
  if (!got) {
    wsprintfA(cand, "C:\\SHARE\\hwid\\spoof_%s.cfg", g_cfgId);
    got |= load_cfg_file(cand);
  }
  if (!got) {
    strncpy(cand, "C:\\SHARE\\hwid\\rfspoof.cfg", MAX_PATH - 1); cand[MAX_PATH - 1] = 0;
    got |= load_cfg_file(cand);
  }
  /* a log path is mandatory for diagnostics; derive one if the cfg did not set it */
  if (!g_logPath[0]) {
    if (g_cfgPath[0]) {
      dir_of(g_cfgPath, g_logPath, MAX_PATH);
      append_cfg_suffix(g_logPath, MAX_PATH, "spoof.log");
    } else if (g_reservedPath[0]) {
      dir_of(g_reservedPath, g_logPath, MAX_PATH);
      append_cfg_suffix(g_logPath, MAX_PATH, "spoof.log");
    } else {
      wsprintfA(g_logPath, "C:\\SHARE\\hwid\\logs\\spoof_%s.log", g_cfgId);
    }
  }
}

static void state_open(void)
{
  char name[80];
  DWORD err;
  wsprintfA(name, "Local\\RFSpoofMutex_%lu", (unsigned long)GetCurrentProcessId());
  g_stateMutex = CreateMutexA(NULL, FALSE, name);
  err = GetLastError();
  g_alreadyPresent = (g_stateMutex && err == ERROR_ALREADY_EXISTS);
  wsprintfA(name, "Local\\RFSpoofState_%lu", (unsigned long)GetCurrentProcessId());
  g_stateMap = CreateFileMappingA(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0, sizeof(RFS_STATE), name);
  if (g_stateMap) {
    g_stateView = (RFS_STATE *)MapViewOfFile(g_stateMap, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(RFS_STATE));
    if (g_stateView) {
      if (!g_alreadyPresent) {
        memset(g_stateView, 0, sizeof(*g_stateView));
        g_stateView->magic = RFS_STATE_MAGIC;
        g_stateView->version = RFS_STATE_VERSION;
        g_stateView->pid = GetCurrentProcessId();
        g_stateView->tick = GetTickCount();
      }
    }
  }
}

static void state_cfg(void)
{
  if (!g_stateView) return;
  if (g_stateView->magic != RFS_STATE_MAGIC) {
    g_stateView->magic = RFS_STATE_MAGIC;
    g_stateView->version = RFS_STATE_VERSION;
    g_stateView->pid = GetCurrentProcessId();
  }
  g_stateView->cfgLen = (DWORD)strlen(g_cfgPath);
  strncpy(g_stateView->cfg, g_cfgPath, MAX_PATH - 1);
  g_stateView->cfg[MAX_PATH - 1] = 0;
  g_stateView->tick = GetTickCount();
}

static void state_ready(int hooks)
{
  if (!g_stateView) return;
  g_stateView->hooks = (DWORD)hooks;
  g_stateView->tick = GetTickCount();
  g_stateView->ready = 1;
}

static DWORD WINAPI heartbeat(LPVOID p)
{
  (void)p;
  for (;;) {
    Sleep(1000);
    if (g_stateView) g_stateView->tick = GetTickCount();
  }
  return 0;
}

static DWORD fnv(const char *s)
{
  DWORD h = 2166136261u;
  while (*s) { h ^= (unsigned char)*s++; h *= 16777619u; }
  return h;
}

static volatile int g_verbose;
static LONG g_vol_in;
static LONG g_name_in;

static BOOL WINAPI h_GetVolumeInformationW(LPCWSTR drv, LPWSTR vn, DWORD vnsz, LPDWORD serial,
                      LPDWORD maxc, LPDWORD flags, LPWSTR fs, DWORD fssz)
{
  static int fc;
  if (!fc) { fc = 1; logfirst("GetVolumeInformationW"); }
  /* Answer fully ourselves: calling the original re-enters this hook from many CEF threads and
    can wedge on the volume; a static reply is safe. */
  if (vn && vnsz) { vn[0] = 0; }
  if (serial) *serial = g_serial;
  if (maxc) *maxc = 255;
  if (flags) *flags = 0x00000003;   /* FS_CASE_IS_PRESERVED | FS_CASE_SENSITIVE */
  if (fs && fssz) { wcscpy(fs, L"NTFS"); }
  return TRUE;
}

static BOOL WINAPI h_GetComputerNameW(LPWSTR buf, LPDWORD size)
{
  DWORD need;
  static int fc;
  if (!fc) { fc = 1; logfirst("GetComputerNameW"); }
  if (!buf || !size) return FALSE;
  need = (DWORD)wcslen(g_name);
  if (*size <= need) { *size = need + 1; return FALSE; }
  wcscpy(buf, g_name);
  *size = need;
  return TRUE;
}

/* (see git history for the original comment)
   otherwise. Return the spoofed name for every format (NetBIOS/DnsHostname/...) */
typedef BOOL (WINAPI *PCGCNEW)(int, LPWSTR, LPDWORD);
static PCGCNEW o_GetComputerNameExW;
static BOOL WINAPI h_GetComputerNameExW(int fmt, LPWSTR buf, LPDWORD size)
{
  DWORD need;
  static int fc;
  if (!fc) { fc = 1; logfirst("GetComputerNameExW"); }
  if (!buf || !size) return FALSE;
  need = (DWORD)wcslen(g_name);
  (void)fmt;
  if (*size <= need) { *size = need + 1; return FALSE; }
  wcscpy(buf, g_name);
  *size = need;
  return TRUE;
}

static LONG g_ver_in;
static BOOL WINAPI h_GetVersionExW(LPOSVERSIONINFOW vi)
{
  BOOL r;
  LONG d = InterlockedIncrement(&g_ver_in);
  if (d > 1) { if (vi) vi->dwBuildNumber = g_build; InterlockedDecrement(&g_ver_in); return TRUE; }
  r = o_GetVersionExW ? o_GetVersionExW(vi) : TRUE;
  if (vi) vi->dwBuildNumber = g_build;
  InterlockedDecrement(&g_ver_in);
  return r;
}

static BOOL WINAPI h_GetProductInfo(DWORD a, DWORD b, DWORD c, DWORD d, PDWORD type)
{
  BOOL r = o_GetProductInfo ? o_GetProductInfo(a, b, c, d, type) : TRUE;
  if (type) *type = PRODUCT_PROFESSIONAL;
  return r;
}

static INT WINAPI h_GetGeoInfoW(UINT loc, GEOTYPE t, LPWSTR buf, int cch, LANGID lang)
{
  if (t == GeoISOString && buf && cch > 2) { wcscpy(buf, L"RU"); return 2; }
  return o_GetGeoInfoW ? o_GetGeoInfoW(loc, t, buf, cch, lang) : 0;
}

/* ---- MAC (GetAdaptersInfo) ---- */
typedef DWORD (WINAPI *PGAI)(void *buf, ULONG *size);

static PGAI o_GetAdaptersInfo;
static PGAI g_real_GetAdaptersInfo;  /* the true iphlpapi export, resolved once (never our hook) */
static LONG g_mac_in;
static BYTE g_mac[6];
static int g_mac_logged;

/* (see git history for the original comment) */
typedef ULONG (WINAPI *PGAA)(ULONG family, ULONG flags, void *reserved, void *addrs, PULONG size);
static PGAA o_GetAdaptersAddresses;

static ULONG WINAPI h_GetAdaptersAddresses(ULONG family, ULONG flags, void *reserved, void *addrs, PULONG size)
{
  PIP_ADAPTER_ADDRESSES a;
  ULONG r;
  static int fc;
  if (!fc) { fc = 1; logfirst("GetAdaptersAddresses"); }
  r = o_GetAdaptersAddresses ? o_GetAdaptersAddresses(family, flags, reserved, addrs, size) : ERROR_CALL_NOT_IMPLEMENTED;
  if (r == NO_ERROR && addrs) {
    int guard = 0;
    for (a = (PIP_ADAPTER_ADDRESSES)addrs; a && guard++ < 64; a = a->Next) {
      if (a->PhysicalAddressLength >= 6) {
        memcpy(a->PhysicalAddress, g_mac, 6);
        a->PhysicalAddressLength = 6;
      }
    }
  }
  return r;
}

static DWORD WINAPI h_GetAdaptersInfo(void *buf, ULONG *size)
{
  DWORD r;
  PIP_ADAPTER_INFO a;
  PGAI real = g_real_GetAdaptersInfo ? g_real_GetAdaptersInfo : o_GetAdaptersInfo;
  if (InterlockedIncrement(&g_mac_in) > 1) {    /* reentrant: do not re-enter real (it may loop back) */
    InterlockedDecrement(&g_mac_in);
    if (buf && size && *size) return 0;      /* report success, buffer already valid */
    return 1;
  }
  r = real ? real(buf, size) : 1;
  if (r == 0 && buf) {
    if (!g_mac_logged) { g_mac_logged = 1; logline("spoof: GetAdaptersInfo called -> MAC faked"); }
    for (a = (PIP_ADAPTER_INFO)buf; a; a = a->Next) {
      a->AddressLength = 6;
      a->Address[0] = g_mac[0]; a->Address[1] = g_mac[1]; a->Address[2] = g_mac[2];
      a->Address[3] = g_mac[3]; a->Address[4] = g_mac[4]; a->Address[5] = g_mac[5];
    }
  }
  InterlockedDecrement(&g_mac_in);
  return r;
}

/* ================================================================================
 * SMBIOS spoofing via GetSystemFirmwareTable / EnumSystemFirmwareTables and
 * NtQuerySystemInformation(SystemFirmwareTableInformation). Overwrites Type 0
 * (BIOS), Type 1 (System/UUID), Type 2 (Baseboard) string fields and the UUID.
 * ================================================================================ */
#define SMBIOS_RSMB 0x52534D42u   /* 'RSMB' */
#define SMBIOS_FIRMWARE_TABLE 0x00000046u
#define SystemFirmwareTableInformation 0x4F

/* Rebuild a raw SMBIOS table, substituting the configured Type 0/1/2 strings and the
 * Type 1 UUID. Strings are re-packed, so a fake value may be longer than the real one.
 * Returns the new table length, or 0 when it does not fit into dst[0..cap). */
static void smbios_map_field(const char *map[65], BYTE flen, const BYTE *f, int off, const char *v)
{
  if (off < flen && f[off] && f[off] < 65 && v && v[0]) map[f[off]] = v;
}

static DWORD smbios_rebuild(BYTE *tbl, DWORD len, BYTE *dst, DWORD cap)
{
  BYTE *p = tbl, *end = tbl + len, *out = dst;
  while (p + 4 <= end) {
    BYTE type = p[0];
    BYTE flen = p[1];
    BYTE *sp, *src_next, *op, *ostr[64];
    const char *fmap[65];
    DWORD need;
    int i, n = 0;
    if (flen < 4) break;

    for (i = 0; i < 65; i++) fmap[i] = NULL;
    if (type == 0) {
      smbios_map_field(fmap, flen, p, 4, g_cfgBiosVendor);
      smbios_map_field(fmap, flen, p, 5, g_cfgBiosVer);
    } else if (type == 1) {
      smbios_map_field(fmap, flen, p, 4, g_cfgSysMfr);
      smbios_map_field(fmap, flen, p, 5, g_cfgSysProd);
      smbios_map_field(fmap, flen, p, 6, g_cfgSysVer);
      smbios_map_field(fmap, flen, p, 7, g_cfgBiosSerial);
    } else if (type == 2) {
      smbios_map_field(fmap, flen, p, 4, g_cfgBoardMfr);
      smbios_map_field(fmap, flen, p, 5, g_cfgBoardProd);
      smbios_map_field(fmap, flen, p, 7, g_cfgBoardSerial);
    }

    sp = p + flen;
    while (sp < end && *sp && n < 64) {
      ostr[n++] = sp;
      while (sp < end && *sp) sp++;
      if (sp < end) sp++;
    }
    src_next = sp;
    if (src_next + 1 < end && src_next[0] == 0 && src_next[1] == 0) src_next += 2;
    else if (src_next < end) src_next += 1;

    need = (DWORD)flen + 1 + (n == 0 ? 1 : 0);
    for (i = 1; i <= n; i++) {
      const char *v = fmap[i];
      need += (DWORD)strlen(v ? v : (const char *)ostr[i - 1]) + 1;
    }
    if ((DWORD)(out - dst) + need > cap) return 0;

    memcpy(out, p, flen);
    op = out + flen;
    for (i = 1; i <= n; i++) {
      const char *v = fmap[i];
      if (!v) v = (const char *)ostr[i - 1];
      lstrcpyA((char *)op, v);
      op += strlen(v) + 1;
    }
    if (n == 0) *op++ = 0;
    *op++ = 0;
    if (type == 1 && g_uuidW[0] && flen >= 24) {
      unsigned a, b, c, d, e, f, g, h, i, j, k;
      if (sscanf(g_cfgUuid, "%8x-%4x-%4x-%2x%2x-%2x%2x%2x%2x%2x%2x",
                 &a, &b, &c, &d, &e, &f, &g, &h, &i, &j, &k) == 11) {
        out[8]  = (BYTE)a; out[9]  = (BYTE)(a >> 8); out[10] = (BYTE)(a >> 16); out[11] = (BYTE)(a >> 24);
        out[12] = (BYTE)b; out[13] = (BYTE)(b >> 8);
        out[14] = (BYTE)c; out[15] = (BYTE)(c >> 8);
        out[16] = (BYTE)d; out[17] = (BYTE)e; out[18] = (BYTE)f;
        out[19] = (BYTE)g; out[20] = (BYTE)h; out[21] = (BYTE)i;
        out[22] = (BYTE)j; out[23] = (BYTE)k;
      } else {
        DWORD hv = fnv(g_cfgUuid[0] ? g_cfgUuid : "uuid");
        int q;
        for (q = 0; q < 16; q++) out[8 + q] = (BYTE)(hv >> ((q % 4) * 8)) ^ (BYTE)(q * 31);
      }
    }
    out = op;
    if (type == 127) break;
    p = src_next;
  }
  return (DWORD)(out - dst);
}
static DWORD WINAPI h_GetSystemFirmwareTable(DWORD sig, DWORD table, PVOID buf, DWORD size)
{
  DWORD r;
  static int fc;
  if (!fc) { fc = 1; logfirst("GetSystemFirmwareTable"); }
  if (sig != SMBIOS_RSMB || !o_GetSystemFirmwareTable)
    return o_GetSystemFirmwareTable(sig, table, buf, size);

  if (!buf) {            /* size query: report room for the rebuilt table */
    DWORD need = o_GetSystemFirmwareTable(sig, table, NULL, 0);
    if (need >= 8) {
      BYTE *tmp = (BYTE *)malloc(need);
      if (tmp && o_GetSystemFirmwareTable(sig, table, tmp, need) == need) {
        DWORD tl = *(DWORD *)(tmp + 4);
        BYTE *reb = (BYTE *)malloc(tl + 16384);
        if (reb) {
          DWORD nl = smbios_rebuild(tmp + 8, tl, reb, tl + 16384);
          free(reb);
          if (nl) { free(tmp); return 8 + nl; }
        }
      }
      if (tmp) free(tmp);
    }
    return need;
  }

  r = o_GetSystemFirmwareTable(sig, table, buf, size);
  if (r >= 8 && size >= 8) {
    DWORD tl = *(DWORD *)((BYTE *)buf + 4);
    if (tl && 8 + tl <= r) {
      BYTE *reb = (BYTE *)malloc(tl + 16384);
      if (reb) {
        DWORD nl = smbios_rebuild((BYTE *)buf + 8, tl, reb, tl + 16384);
        if (nl && 8 + nl <= size) {
          memcpy((BYTE *)buf + 8, reb, nl);
          *(DWORD *)((BYTE *)buf + 4) = nl;
          r = 8 + nl;
        }
        free(reb);
      }
    }
  }
  return r;
}

static LONG WINAPI h_NtQSI(ULONG cls, PVOID buf, ULONG len, PULONG ret)
{
  LONG r = o_NtQSI(cls, buf, len, ret);
  static int fc;
  if (!fc && cls == SystemFirmwareTableInformation) { fc = 1; logfirst("NtQSI(Firmware)"); }
  { static DWORD seen_classes;
   if (!(seen_classes & (1u << (cls & 31)))) { seen_classes |= (1u << (cls & 31)); logline("spoof: NtQSI class=%lu len=%lu r=%d", cls, len, r); } }
  if (r >= 0 && cls == 1 && buf && len >= 12) {    /* SYSTEM_PROCESSOR_INFORMATION: spoof revision */
    USHORT *rev = (USHORT *)((BYTE *)buf + 4);
    *rev = (USHORT)((g_serial >> 8) & 0xFFFF);
  }
  if (r >= 0 && cls == SystemFirmwareTableInformation && buf && len >= 12) {
    /* SYSTEM_FIRMWARE_TABLE_INFORMATION: ProviderSignature, TableID, TableBufferLength, Buffer */
    DWORD sig = *(DWORD *)buf;
    DWORD tblLen = *(DWORD *)((BYTE *)buf + 8);
    DWORD cap = len - 12;
    if (sig == SMBIOS_RSMB && tblLen && 12 + tblLen <= len) {
      BYTE *reb = (BYTE *)malloc(cap);
      if (reb) {
        DWORD nl = smbios_rebuild((BYTE *)buf + 12, tblLen, reb, cap);
        if (nl) { memcpy((BYTE *)buf + 12, reb, nl); *(DWORD *)((BYTE *)buf + 8) = nl; }
        free(reb);
      }
    }
  }
  return r;
}

/* disk serial via DeviceIoControl(IOCTL_STORAGE_QUERY_PROPERTY / SMART) */
#define IOCTL_STORAGE_QUERY_PROPERTY_ 0x2D1400u
static BOOL WINAPI h_DeviceIoControl(HANDLE h, DWORD code, PVOID in, DWORD insz, PVOID out, DWORD outsz,
                   LPDWORD ret, LPOVERLAPPED ol)
{
  BOOL r = o_DeviceIoControl(h, code, in, insz, out, outsz, ret, ol);
  static int fc;
  if (!fc && code == IOCTL_STORAGE_QUERY_PROPERTY_) { fc = 1; logfirst("DeviceIoControl(Storage)"); }
  { static DWORD seen; if (!(seen & (1u << (code & 31))) || code == 0x2D1400) { if (!(seen & (1u << (code & 31)))) { seen |= (1u << (code & 31)); logline("spoof: DeviceIoControl code=0x%X r=%d", code, r); } } }
  if (r && code == 0x70050 && out && outsz >= 24 && g_smbios) {
    BYTE *b = (BYTE *)out;
    logline("spoof: MSSMBios hdr24=%02X%02X%02X%02X %02X%02X%02X%02X %02X%02X%02X%02X %02X%02X%02X%02X %02X%02X%02X%02X %02X%02X%02X%02X",
        b[0],b[1],b[2],b[3],b[4],b[5],b[6],b[7],b[8],b[9],b[10],b[11],b[12],b[13],b[14],b[15],b[16],b[17],b[18],b[19],b[20],b[21],b[22],b[23]);
  }
  if (r && code == IOCTL_STORAGE_QUERY_PROPERTY_ && out && outsz >= 12 && g_cfgDiskSerial[0]) {
    /* STORAGE_DEVICE_DESCRIPTOR: Version,Size,DeviceType,DeviceTypeModifier,RemovableMedia,
      CommandQueueing, VendorIdOffset(+12),ProductIdOffset,ProductRevisionOffset,SerialNumberOffset(+24) */
    DWORD vers = *(DWORD *)out;
    DWORD serialOff = *(DWORD *)((BYTE *)out + 24);
    DWORD size = *(DWORD *)((BYTE *)out + 4);
    if (vers && serialOff && serialOff < outsz && (!size || serialOff < size)) {
      char *s = (char *)out + serialOff;
      size_t sl = strlen(s), vl = strlen(g_cfgDiskSerial);
      size_t room = outsz - serialOff;
      if (vl && vl < room) {
        memcpy(s, g_cfgDiskSerial, vl);
        if (vl <= sl) memset(s + vl, 0, sl - vl + 1);  /* wipe the real remainder */
        else s[vl] = 0;
      }
    }
  }
  return r;
}

/* ---- monitors: EnumDisplayDevicesW ---- */
static BOOL WINAPI h_EnumDisplayDevicesW(LPCWSTR dev, DWORD num, PVOID info, DWORD flags)
{
  BOOL r = o_EnumDisplayDevicesW(dev, num, info, flags);
  static int fc;
  if (!fc) { fc = 1; logfirst("EnumDisplayDevicesW"); }
  if (r && info && g_cfgMonId[0]) {
    DISPLAY_DEVICEW *d = (DISPLAY_DEVICEW *)info;
    WCHAR *p = wcsstr(d->DeviceID, L"MONITOR\\");
    if (p && d->cb >= sizeof(DISPLAY_DEVICEW)) {
      WCHAR cfgW[64], out[MAX_PATH];
      const WCHAR *rest = wcschr(p + 8, L'\\');
      int n = MultiByteToWideChar(CP_UTF8, 0, g_cfgMonId, -1, cfgW, 63);
      if (n > 0 && rest) {
        cfgW[63] = 0;
        lstrcpynW(out, d->DeviceID, (int)(p - d->DeviceID) + 1);
        lstrcatW(out, cfgW);
        lstrcatW(out, rest);
        lstrcpynW(d->DeviceID, out, 128);
      }
    }
  }
  return r;
}

/* SystemProcessorRevision in SYSTEM_INFO (also exposed by GetSystemInfo) */
typedef void (WINAPI *PGetSystemInfo)(PVOID);
static PGetSystemInfo o_GetSystemInfo;
static void WINAPI h_GetSystemInfo(PVOID si)
{
  static int fc;
  if (!fc) { fc = 1; logfirst("GetSystemInfo"); }
  if (o_GetSystemInfo) o_GetSystemInfo(si);
  if (si) *(USHORT *)((BYTE *)si + 0x22) = (USHORT)((g_serial >> 8) & 0xFFFF);
}

/* ---- SetupAPI device properties (serial/HWID of devices) ---- */
static BOOL WINAPI h_SetupDiGetDeviceRegistryPropertyW(void *dev, void *reg, DWORD prop, PDWORD ptype,
                           PBYTE buf, DWORD size, PDWORD reqsize)
{
  BOOL r = o_SetupDiGetDeviceRegistryPropertyW ? o_SetupDiGetDeviceRegistryPropertyW(dev, reg, prop, ptype, buf, size, reqsize) : FALSE;
  return r;
}

/* (see git history for the original comment) */
static BOOL WINAPI h_GetFileInformationByHandle(HANDLE hf, PVOID info)
{
  BOOL r = o_GetFileInformationByHandle ? o_GetFileInformationByHandle(hf, info) : FALSE;
  static int fc;
  if (!fc) { fc = 1; logfirst("GetFileInformationByHandle"); }
  if (r && info) *(DWORD *)((BYTE *)info + 0x1C) = g_serial;  /* dwVolumeSerialNumber */
  return r;
}

static BOOL WINAPI h_GetUserNameW(LPWSTR buf, LPDWORD size)
{
  static int fc;
  if (!fc) { fc = 1; logfirst("GetUserNameW"); }
  if (buf && size && g_username[0]) {
    DWORD need = (DWORD)wcslen(g_username);
    if (*size <= need) { *size = need + 1; return FALSE; }
    wcscpy(buf, g_username); *size = need; return TRUE;
  }
  return o_GetUserNameW ? o_GetUserNameW(buf, size) : FALSE;
}

/* redirect anything under ...\DeviceSync\ to our per-profile directory */
#define META_DIR_MARK L"\\DeviceSync\\"
static int is_meta_path(LPCWSTR path)
{
  return path && g_metaPath[0] && wcsstr(path, META_DIR_MARK) != NULL;
}

/* build the redirected path: replace everything up to and incl. "\DeviceSync\" with g_metaDir */
static const WCHAR *redirect_meta(LPCWSTR path, WCHAR *out)
{
  const WCHAR *m = wcsstr(path, META_DIR_MARK);
  if (!m) return path;
  wcscpy(out, g_metaDir);
  /* ensure single backslash between dir and remainder */
  if (out[wcslen(out) - 1] != L'\\') wcscat(out, L"\\");
  wcscat(out, m + wcslen(META_DIR_MARK));
  return out;
}

static HANDLE WINAPI h_CreateFileW(LPCWSTR path, DWORD acc, DWORD share, PVOID sa, DWORD disp, DWORD flags, HANDLE tmpl)
{
  static int fc;
  WCHAR red[MAX_PATH];
  if (!fc) { fc = 1; logfirst("CreateFileW"); }
  if (is_meta_path(path))
    return o_CreateFileW(redirect_meta(path, red), acc, share, sa, disp, flags, tmpl);
  return o_CreateFileW(path, acc, share, sa, disp, flags, tmpl);
}

typedef DWORD (WINAPI *PGetFileAttributesW)(LPCWSTR);
static PGetFileAttributesW o_GetFileAttributesW;
static DWORD WINAPI h_GetFileAttributesW(LPCWSTR path)
{
  static int fc;
  WCHAR red[MAX_PATH];
  if (!fc) { fc = 1; logfirst("GetFileAttributesW"); }
  if (is_meta_path(path)) return o_GetFileAttributesW(redirect_meta(path, red));
  return o_GetFileAttributesW(path);
}

typedef BOOL (WINAPI *PGetFileAttributesExW)(LPCWSTR, GET_FILEEX_INFO_LEVELS, PVOID);
static PGetFileAttributesExW o_GetFileAttributesExW;
static BOOL WINAPI h_GetFileAttributesExW(LPCWSTR path, GET_FILEEX_INFO_LEVELS level, PVOID info)
{
  WCHAR red[MAX_PATH];
  if (is_meta_path(path)) path = redirect_meta(path, red);
  return o_GetFileAttributesExW ? o_GetFileAttributesExW(path, level, info) : FALSE;
}

typedef HANDLE (WINAPI *PFindFirstFileW)(LPCWSTR, LPWIN32_FIND_DATAW);
static PFindFirstFileW o_FindFirstFileW;
static HANDLE WINAPI h_FindFirstFileW(LPCWSTR path, LPWIN32_FIND_DATAW data)
{
  WCHAR red[MAX_PATH];
  if (is_meta_path(path)) path = redirect_meta(path, red);
  return o_FindFirstFileW ? o_FindFirstFileW(path, data) : INVALID_HANDLE_VALUE;
}

typedef BOOL (WINAPI *PDeleteFileW)(LPCWSTR);
static PDeleteFileW o_DeleteFileW;
static BOOL WINAPI h_DeleteFileW(LPCWSTR path)
{
  WCHAR red[MAX_PATH];
  if (is_meta_path(path)) path = redirect_meta(path, red);
  return o_DeleteFileW ? o_DeleteFileW(path) : FALSE;
}

typedef BOOL (WINAPI *PCreateDirectoryW)(LPCWSTR, PVOID);
static PCreateDirectoryW o_CreateDirectoryW;
static BOOL WINAPI h_CreateDirectoryW(LPCWSTR path, PVOID sa)
{
  static int fc;
  WCHAR red[MAX_PATH];
  if (!fc) { fc = 1; logfirst("CreateDirectoryW"); }
  if (is_meta_path(path)) return o_CreateDirectoryW(redirect_meta(path, red), sa);
  return o_CreateDirectoryW(path, sa);
}



/* ---- host name (system) ---- */
static int WINAPI h_GetHostNameW(PWCHAR buf, int len)
{
  int r = o_GetHostNameW ? o_GetHostNameW(buf, len) : 0;
  static int fc;
  if (!fc) { fc = 1; logfirst("GetHostNameW"); }
  if (buf && g_name[0]) {
    int need = (int)wcslen(g_name);
    if (need < len) { wcscpy(buf, g_name); r = 0; }
  }
  return r;
}

/* (see git history for the original comment) */
typedef int (WINAPI *Pgethostname)(char *, int);
static Pgethostname o_gethostname;
static int WINAPI h_gethostname(char *buf, int len)
{
  static int fc;
  if (!fc) { fc = 1; logfirst("gethostname"); }
  if (buf && g_name[0]) {
    char a[128]; int i;
    for (i = 0; i < 127 && g_name[i]; i++) a[i] = (char)g_name[i];
    a[i] = 0;
    if ((int)strlen(a) < len) { strcpy(buf, a); return 0; }
  }
  return o_gethostname ? o_gethostname(buf, len) : 0;
}

/* ---- total physical memory ---- */
#pragma pack(push, 1)
typedef struct { DWORD dwLength; DWORD dwMemoryLoad; ULONGLONG ullTotalPhys, ullAvailPhys, ullTotalPageFile, ullAvailPageFile, ullTotalVirtual, ullAvailVirtual, ullAvailExtendedVirtual; } MEMORYSTATUSEX_;
#pragma pack(pop)

static BOOL WINAPI h_GlobalMemoryStatusEx(PVOID mse)
{
  BOOL r = o_GlobalMemoryStatusEx ? o_GlobalMemoryStatusEx(mse) : FALSE;
  static int fc;
  if (!fc) { fc = 1; logfirst("GlobalMemoryStatusEx"); }
  if (r && mse && g_ramBytes) {
    MEMORYSTATUSEX_ *m = (MEMORYSTATUSEX_ *)mse;
    if (m->dwLength >= sizeof(MEMORYSTATUSEX_)) {
      m->ullTotalPhys = g_ramBytes;
      if (m->ullAvailPhys > g_ramBytes) m->ullAvailPhys = g_ramBytes - (64ull << 20);
    }
  }
  return r;
}

/* ---- MachineGuid (RegQueryValueExW / A) ---- */
typedef LONG (WINAPI *PRegQueryValueExW)(void *hKey, LPCWSTR name, DWORD *reserved, DWORD *type, BYTE *data, DWORD *cbData);
typedef LONG (WINAPI *PRegQueryValueExA)(void *hKey, LPCSTR name, DWORD *reserved, DWORD *type, BYTE *data, DWORD *cbData);

static PRegQueryValueExW o_RegQueryValueExW;
static PRegQueryValueExA o_RegQueryValueExA;
static WCHAR g_guid[64];
static char g_guidA[64];
static int  g_guid_logged;

/* fake values for a few HKLM HWID value names (per-instance, deterministic from the seed) */
static WCHAR g_biosVendor[48], g_biosVer[24], g_boardMfr[48], g_boardProd[40], g_sysProd[40], g_sysVer[24], g_macStr[16], g_monId[40];

static void put_w(WCHAR *name, DWORD *type, BYTE *data, DWORD *cbData, DWORD cap, DWORD regtype, const WCHAR *val, int once)
{
  DWORD need = (DWORD)(wcslen(val) * 2 + 2);
  if (*cbData >= need || cap >= need) {
    wcscpy((WCHAR *)data, val);
    *cbData = need;
    if (type) *type = regtype;
  }
}

static void fake_reg_if(WCHAR *name, DWORD *type, BYTE *data, DWORD *cbData, DWORD cap)
{
  if (!name || !cbData) return;
  if (_wcsicmp(name, L"MachineGuid") == 0) {
    if (!g_guid_logged) { g_guid_logged = 1; logfirst("RegQueryValue(MachineGuid)"); }
    put_w(name, type, data, cbData, cap, REG_SZ, g_guid, 0);
  }
  if (!g_regsub) return;
  if (!g_reghw) return;
  if (0) { }
  else if (_wcsicmp(name, L"BIOSVendor") == 0)     put_w(name, type, data, cbData, cap, REG_SZ, g_biosVendor, 0);
  else if (_wcsicmp(name, L"BIOSVersion") == 0)     put_w(name, type, data, cbData, cap, REG_SZ, g_biosVer, 0);
  else if (_wcsicmp(name, L"SystemBiosVersion") == 0) put_w(name, type, data, cbData, cap, REG_MULTI_SZ, g_biosVer, 0);
  else if (_wcsicmp(name, L"SystemBiosDate") == 0)   put_w(name, type, data, cbData, cap, REG_SZ, L"01/01/2019", 0);
  else if (_wcsicmp(name, L"ProcessorNameString") == 0) { if (g_cfgCpu[0]) { WCHAR w[96]; MultiByteToWideChar(CP_UTF8, 0, g_cfgCpu, -1, w, 95); w[95] = 0; put_w(name, type, data, cbData, cap, REG_SZ, w, 0); } }
  else if (_wcsicmp(name, L"Identifier") == 0)     put_w(name, type, data, cbData, cap, REG_SZ, L"x86 Family 6 Model 158 Stepping 10", 0);
  else if (_wcsicmp(name, L"BIOSVersion") == 0)     put_w(name, type, data, cbData, cap, REG_SZ, g_biosVer, 0);
  else if (_wcsicmp(name, L"BaseBoardManufacturer") == 0)put_w(name, type, data, cbData, cap, REG_SZ, g_boardMfr, 0);
  else if (_wcsicmp(name, L"BaseBoardProduct") == 0)   put_w(name, type, data, cbData, cap, REG_SZ, g_boardProd, 0);
  else if (_wcsicmp(name, L"SystemManufacturer") == 0)  put_w(name, type, data, cbData, cap, REG_SZ, g_boardMfr, 0);
  else if (_wcsicmp(name, L"SystemProductName") == 0)  put_w(name, type, data, cbData, cap, REG_SZ, g_sysProd, 0);
  else if (_wcsicmp(name, L"SystemVersion") == 0)    put_w(name, type, data, cbData, cap, REG_SZ, g_sysVer, 0);
  else if (_wcsicmp(name, L"NetworkAddress") == 0)    put_w(name, type, data, cbData, cap, REG_SZ, g_macStr, 0);
  else if (_wcsicmp(name, L"Hostname") == 0 || _wcsicmp(name, L"NV Hostname") == 0 ||
           _wcsicmp(name, L"DhcpHostname") == 0) {
    DWORD need = (DWORD)(wcslen(g_name) * 2 + 2);
    logline("spoof: HOSTNAME cap=%lu cb=%lu data=%p need=%lu", cap, cbData ? *cbData : 0, data, need);
    if (type) *type = REG_SZ;
    if (cbData) {
      if (!data) *cbData = need;
      else if (cap >= need || *cbData >= need) { memcpy(data, g_name, need); *cbData = need; }
      else *cbData = need;
    }
  }
  else if (_wcsicmp(name, L"HardwareID") == 0) {     /* REG_MULTI_SZ "MONITOR\\xxx\0\0" */
    DWORD need = (DWORD)(wcslen(g_monId) * 2 + 4);
    if (*cbData >= need || cap >= need) {
      wcscpy((WCHAR *)data, g_monId);
      ((WCHAR *)data)[wcslen(g_monId) + 1] = 0;
      *cbData = need; if (type) *type = REG_MULTI_SZ;
    }
  }
}

static LONG g_regw_in;
static LONG g_rega_in;
static int g_reglog = 1;
static int fake_reg_known(const WCHAR *n);

static LONG WINAPI h_RegQueryValueExW(void *hKey, LPCWSTR name, DWORD *reserved, DWORD *type, BYTE *data, DWORD *cbData)
{
  LONG r;
  DWORD cap = cbData ? *cbData : 0;  /* caller's buffer capacity, before the real call shrinks it */
  static int fc;
  if (!fc) { fc = 1; logfirst("RegQueryValueExW"); }
  /* MachineGuid (and the other HWID values below) is answered by us, not by the real registry:
    a 32-bit caller under WOW64 may not even see the native Cryptography key, and a non-admin
    profile must not need write access. */
  if (name && g_guid[0] && _wcsicmp(name, L"MachineGuid") == 0) {
    DWORD need = (DWORD)(wcslen(g_guid) * 2 + 2);
    if (!g_guid_logged) { g_guid_logged = 1; logfirst("RegQueryValue(MachineGuid)"); }
    if (type) *type = REG_SZ;
    if (!cbData) return ERROR_SUCCESS;
    if (!data) { *cbData = need; return ERROR_SUCCESS; }
    if (*cbData < need) { *cbData = need; return ERROR_MORE_DATA; }
    wcscpy((WCHAR *)data, g_guid);
    *cbData = need;
    return ERROR_SUCCESS;
  }
  if (o_RegQueryValueExW == (void *)h_RegQueryValueExW) {  /* self-recursion guard */
    static LONG depth;
    if (InterlockedIncrement(&depth) > 1) { InterlockedDecrement(&depth); return 0; }
    r = 0;                  /* no real original available */
    if (r == 0) fake_reg_if((WCHAR *)name, type, data, cbData, cap);
    InterlockedDecrement(&depth);
    return r;
  }
  r = o_RegQueryValueExW ? o_RegQueryValueExW(hKey, name, reserved, type, data, cbData) : 2;
  if (r == 0) fake_reg_if((WCHAR *)name, type, data, cbData, cap);
  if (r == 0 && name && g_reglog && fake_reg_known(name) == 0) {
    static WCHAR seen[64][32]; static int ns;
    int i, dup = 0; WCHAR *nm = (WCHAR *)name;
    for (i = 0; i < ns; i++) if (!_wcsicmp(seen[i], nm)) { dup = 1; break; }
    if (!dup && ns < 64) { wcsncpy(seen[ns], nm, 31); seen[ns][31] = 0; ns++;
      logline("spoof: REG name=%S", nm); }
  }
  return r;
}

/* 1 if fake_reg_if would substitute this name */
static int fake_reg_known(const WCHAR *n)
{
  return !_wcsicmp(n, L"MachineGuid") || !_wcsicmp(n, L"BIOSVendor") || !_wcsicmp(n, L"BIOSVersion") ||
    !_wcsicmp(n, L"BaseBoardManufacturer") || !_wcsicmp(n, L"BaseBoardProduct") ||
    !_wcsicmp(n, L"SystemManufacturer") || !_wcsicmp(n, L"SystemProductName") ||
    !_wcsicmp(n, L"SystemVersion") || !_wcsicmp(n, L"NetworkAddress") || !_wcsicmp(n, L"HardwareID") ||
    !_wcsicmp(n, L"Hostname") || !_wcsicmp(n, L"NV Hostname") || !_wcsicmp(n, L"DhcpHostname") ||
    !_wcsicmp(n, L"ProcessorNameString") || !_wcsicmp(n, L"SystemBiosVersion") ||
    !_wcsicmp(n, L"SystemBiosDate") || !_wcsicmp(n, L"Identifier");
}

static LONG WINAPI h_RegQueryValueExA(void *hKey, LPCSTR name, DWORD *reserved, DWORD *type, BYTE *data, DWORD *cbData)
{
  LONG r;
  if (name && g_guidA[0] && _stricmp(name, "MachineGuid") == 0) {
    DWORD need = (DWORD)strlen(g_guidA) + 1;
    if (!g_guid_logged) { g_guid_logged = 1; logline("spoof: RegQueryValueExA(MachineGuid) called -> faked"); }
    if (type) *type = REG_SZ;
    if (!cbData) return ERROR_SUCCESS;
    if (!data) { *cbData = need; return ERROR_SUCCESS; }
    if (*cbData < need) { *cbData = need; return ERROR_MORE_DATA; }
    memcpy(data, g_guidA, need);
    *cbData = need;
    return ERROR_SUCCESS;
  }
  if (InterlockedIncrement(&g_rega_in) > 1) { InterlockedDecrement(&g_rega_in); return o_RegQueryValueExA ? o_RegQueryValueExA(hKey, name, reserved, type, data, cbData) : 2; }
  r = o_RegQueryValueExA ? o_RegQueryValueExA(hKey, name, reserved, type, data, cbData) : 2;
  InterlockedDecrement(&g_rega_in);
  if (name) {
    WCHAR wname[128];
    if (MultiByteToWideChar(CP_ACP, 0, name, -1, wname, 127) > 0) {
      wname[127] = 0;
      if (fake_reg_known(wname)) {
        WCHAR wbuf[512]; DWORD wcb = sizeof(wbuf); DWORD wtype = REG_SZ; char abuf[1024]; int n;
        memset(wbuf, 0, sizeof(wbuf));
        fake_reg_if(wname, &wtype, (BYTE *)wbuf, &wcb, sizeof(wbuf));
        if (wcb > 2) {
          if (wtype == REG_MULTI_SZ) n = WideCharToMultiByte(CP_ACP, 0, wbuf, (int)wcslen(wbuf) + 2, abuf, sizeof(abuf), 0, 0);
          else n = WideCharToMultiByte(CP_ACP, 0, wbuf, -1, abuf, sizeof(abuf), 0, 0);
          if (n > 0) {
            DWORD need = (DWORD)n;
            r = ERROR_SUCCESS;
            if (type) *type = wtype;
            if (cbData) {
              if (!data) *cbData = need;
              else if (*cbData >= need) { memcpy(data, abuf, need); *cbData = need; }
              else { *cbData = need; r = ERROR_MORE_DATA; }
            }
          }
        }
      }
    }
  }
  return r;
}

/* ---- per-instance SOCKS5 proxying (tunnel through the proxy from SPOOF_PROXY) ---- */
typedef int (WINAPI *Pconnect)(SOCKET, const struct sockaddr *, int);
typedef int (WINAPI *PWSAConnect)(SOCKET, const struct sockaddr *, int, LPWSABUF, LPWSABUF, LPQOS, LPQOS);
static Pconnect   o_connect;
static PWSAConnect o_WSAConnect;
static int   g_proxyOn;
static int   g_proxyAuth;
static char  g_proxyUser[64];
static char  g_proxyPass[64];
static DWORD  g_proxyIp;   /* network order */
static USHORT g_proxyPort;  /* network order */

static int wait_io(SOCKET s, int wr, int ms)
{
  fd_set f; struct timeval tv;
  FD_ZERO(&f); FD_SET(s, &f);
  tv.tv_sec = ms / 1000; tv.tv_usec = (ms % 1000) * 1000;
  return select(0, wr ? NULL : &f, wr ? &f : NULL, NULL, &tv);
}
/* read with an explicit timeout (returns 0 ok, -1 on error/timeout) */
static int r_all_to(SOCKET s, char *b, int len, int ms)
{
  int o = 0;
  while (o < len) {
    int n = recv(s, b + o, len - o, 0);
    if (n > 0) { o += n; continue; }
    if (n == 0) return -1;
    if (WSAGetLastError() == WSAEWOULDBLOCK) { if (wait_io(s, 0, ms) <= 0) return -1; continue; }
    return -1;
  }
  return 0;
}
static int s_all(SOCKET s, const char *b, int len)
{
  int o = 0;
  while (o < len) {
    int n = send(s, b + o, len - o, 0);
    if (n > 0) { o += n; continue; }
    if (n == SOCKET_ERROR && WSAGetLastError() == WSAEWOULDBLOCK) { if (wait_io(s, 1, 5000) <= 0) return -1; continue; }
    return -1;
  }
  return 0;
}
static int r_all(SOCKET s, char *b, int len)
{
  int o = 0;
  while (o < len) {
    int n = recv(s, b + o, len - o, 0);
    if (n > 0) { o += n; continue; }
    if (n == 0) return -1;
    if (WSAGetLastError() == WSAEWOULDBLOCK) { if (wait_io(s, 0, 5000) <= 0) return -1; continue; }
    return -1;
  }
  return 0;
}

static int socks5_connect(SOCKET s, DWORD ip, USHORT port)
{
  unsigned char gr[4], rep[2], req[10], rp[4], ar[2];
  int glen;
  if (g_proxyAuth) { gr[0] = 5; gr[1] = 2; gr[2] = 0; gr[3] = 2; glen = 4; }
  else       { gr[0] = 5; gr[1] = 1; gr[2] = 0;        glen = 3; }
  if (s_all(s, (char *)gr, glen)) return 1;
  if (r_all(s, (char *)rep, 2)) return 2;
  if (rep[0] != 5) return 3;
  if (rep[1] == 0x02) {             /* username/password (RFC 1929) */
    unsigned char ab[2 + 255 + 1 + 255];
    int n = 0, ul = (int)strlen(g_proxyUser), pl = (int)strlen(g_proxyPass);
    if (ul > 255) ul = 255;
    if (pl > 255) pl = 255;
    ab[n++] = 1; ab[n++] = (unsigned char)ul; memcpy(ab + n, g_proxyUser, ul); n += ul;
    ab[n++] = (unsigned char)pl; memcpy(ab + n, g_proxyPass, pl); n += pl;
    if (s_all(s, (char *)ab, n)) return 4;
    if (r_all(s, (char *)ar, 2)) return 5;
    if (ar[1] != 0) return 6;
  } else if (rep[1] != 0x00) return 7;
  req[0] = 5; req[1] = 1; req[2] = 0; req[3] = 1;
  memcpy(req + 4, &ip, 4); memcpy(req + 8, &port, 2);
  if (s_all(s, (char *)req, 10)) return 8;
  if (r_all_to(s, (char *)rp, 4, 3000)) return 9;
  logline("spoof: socks5 CONNECT rep=%d atyp=%d", rp[1], rp[3]);
  if (rp[1] != 0) return 10;
  if (rp[3] == 1) { char t[6]; if (r_all(s, t, 6)) return 11; }
  else if (rp[3] == 4) { char t[18]; if (r_all(s, t, 18)) return 11; }
  else if (rp[3] == 3) { char l; if (r_all(s, &l, 1)) return 11; { char t[256]; if (r_all(s, t, (unsigned char)l + 2)) return 11; } }
  return 0;
}

/* same SOCKS5 handshake but for an IPv6 destination (ATYP=4) */
static int socks5_connect6(SOCKET s, const BYTE *ip6, USHORT port)
{
  unsigned char gr[4], rep[2], req[22], rp[4], ar[2];
  int glen;
  if (g_proxyAuth) { gr[0] = 5; gr[1] = 2; gr[2] = 0; gr[3] = 2; glen = 4; }
  else       { gr[0] = 5; gr[1] = 1; gr[2] = 0;        glen = 3; }
  if (s_all(s, (char *)gr, glen)) return 1;
  if (r_all(s, (char *)rep, 2)) return 2;
  if (rep[0] != 5) return 3;
  if (rep[1] == 0x02) {
    unsigned char ab[2 + 255 + 1 + 255];
    int n = 0, ul = (int)strlen(g_proxyUser), pl = (int)strlen(g_proxyPass);
    if (ul > 255) ul = 255; if (pl > 255) pl = 255;
    ab[n++] = 1; ab[n++] = (unsigned char)ul; memcpy(ab + n, g_proxyUser, ul); n += ul;
    ab[n++] = (unsigned char)pl; memcpy(ab + n, g_proxyPass, pl); n += pl;
    if (s_all(s, (char *)ab, n)) return 4;
    if (r_all(s, (char *)ar, 2)) return 5;
    if (ar[1] != 0) return 6;
  } else if (rep[1] != 0x00) return 7;
  req[0] = 5; req[1] = 1; req[2] = 0; req[3] = 4;
  memcpy(req + 4, ip6, 16); memcpy(req + 20, &port, 2);
  if (s_all(s, (char *)req, 22)) return 8;
  if (r_all_to(s, (char *)rp, 4, 3000)) return 9;
  logline("spoof: socks5 CONNECT rep=%d atyp=%d", rp[1], rp[3]);
  if (rp[1] != 0) return 10;
  if (rp[3] == 1) { char t[6]; if (r_all(s, t, 6)) return 11; }
  else if (rp[3] == 4) { char t[18]; if (r_all(s, t, 18)) return 11; }
  else if (rp[3] == 3) { char l; if (r_all(s, &l, 1)) return 11; { char t[256]; if (r_all(s, t, (unsigned char)l + 2)) return 11; } }
  return 0;
}

static int ip_is_bad(DWORD ip);
static void ip_mark_bad(DWORD ip);
static int g_tries = 8;     /* proxy CONNECT attempts */

static SOCKET reopen_same(SOCKET s)
{
  /* close s and reopen until we get the SAME descriptor back (CEF holds the old number) */
  int i;
  closesocket(s);
  for (i = 0; i < 8; i++) {
    SOCKET n = socket(AF_INET, SOCK_STREAM, 0);
    if (n == s) return n;
    if (n == INVALID_SOCKET) return s;
    closesocket(n);
  }
  return socket(AF_INET, SOCK_STREAM, 0);
}

static SOCKET reopen_same6(SOCKET s)
{
  int i;
  closesocket(s);
  for (i = 0; i < 8; i++) {
    SOCKET n = socket(AF_INET6, SOCK_STREAM, 0);
    if (n == s) return n;
    if (n == INVALID_SOCKET) return s;
    closesocket(n);
  }
  return socket(AF_INET6, SOCK_STREAM, 0);
}

static int proxy_tcp_connect(SOCKET s, const struct sockaddr_in *addr)
{
  int rc = o_connect(s, (const struct sockaddr *)addr, sizeof(*addr));
  if (rc == 0) return 0;
  if (WSAGetLastError() != WSAEWOULDBLOCK) return -1;
  if (wait_io(s, 1, 5000) <= 0) return -1;
  {
    int err = 0, el = sizeof(err);
    if (getsockopt(s, SOL_SOCKET, SO_ERROR, (char *)&err, &el) != 0 || err != 0) {
      WSASetLastError(err ? err : WSAETIMEDOUT);
      return -1;
    }
  }
  return 0;
}

static int do_connect(SOCKET s, DWORD ip, USHORT port)
{
  struct sockaddr_in pr;
  int udp = 0, attempt;
  { int t = 0, tl = sizeof(t); if (getsockopt(s, SOL_SOCKET, SO_TYPE, (char *)&t, &tl) == 0 && t == SOCK_DGRAM) udp = 1; }
  if (g_proxyOn && !udp && (ntohl(ip) >> 24) != 127 && !(ip == g_proxyIp && port == g_proxyPort)) {
    u_long nb = 0; int wasnb = 0;
    struct sockaddr_in p_addr;
    p_addr.sin_family = AF_INET; p_addr.sin_port = g_proxyPort; p_addr.sin_addr.s_addr = g_proxyIp;
    memset(p_addr.sin_zero, 0, sizeof(p_addr.sin_zero));
    for (attempt = 0; attempt < g_tries; attempt++) {
      int rc;
      if (attempt) { s = reopen_same(s); Sleep(150 + attempt * 100); }
      if (ioctlsocket(s, FIONBIO, &nb) == 0) wasnb = 1;
      if (proxy_tcp_connect(s, &p_addr) != 0) {
        logline("spoof: proxy tcp connect fail attempt=%d err=%d", attempt, WSAGetLastError());
        nb = 1; if (wasnb) ioctlsocket(s, FIONBIO, &nb);
        continue;
      }
      rc = socks5_connect(s, ip, port);
      nb = 1; if (wasnb) ioctlsocket(s, FIONBIO, &nb);
      if (rc == 0) { if (attempt) logline("spoof: proxy retry ok attempt=%d", attempt); return 0; }
      logline("spoof: socks5 fail step=%d attempt=%d dst=%d.%d.%d.%d:%d", rc, attempt, ip & 0xff, (ip >> 8) & 0xff, (ip >> 16) & 0xff, (ip >> 24) & 0xff, ntohs(port));
    }
    WSASetLastError(WSAECONNREFUSED);
    return SOCKET_ERROR;
  }
  pr.sin_family = AF_INET; pr.sin_port = port; pr.sin_addr.s_addr = ip;
  memset(pr.sin_zero, 0, sizeof(pr.sin_zero));
  return o_connect(s, (struct sockaddr *)&pr, sizeof(pr));
}

/* connect() through the proxy for an IPv6 destination */
static int do_connect6(SOCKET s, const BYTE *ip6, USHORT port)
{
  struct sockaddr_in pr;
  struct sockaddr_in6 p6;
  if (!g_proxyOn) {
    p6.sin6_family = AF_INET6; p6.sin6_port = port; memcpy(p6.sin6_addr.s6_addr, ip6, 16);
    return o_connect(s, (struct sockaddr *)&p6, sizeof(p6));
  }
  {
    u_long nb = 0; int wasnb = 0, rc, attempt;
    for (attempt = 0; attempt < g_tries; attempt++) {
      if (attempt) { s = reopen_same6(s); Sleep(150 + attempt * 100); }
      if (ioctlsocket(s, FIONBIO, &nb) == 0) wasnb = 1;
      pr.sin_family = AF_INET; pr.sin_port = g_proxyPort; pr.sin_addr.s_addr = g_proxyIp;
      memset(pr.sin_zero, 0, sizeof(pr.sin_zero));
      if (proxy_tcp_connect(s, &pr) != 0) {
        logline("spoof: proxy6 tcp connect fail attempt=%d err=%d", attempt, WSAGetLastError());
        nb = 1; if (wasnb) ioctlsocket(s, FIONBIO, &nb);
        continue;
      }
      rc = socks5_connect6(s, ip6, port);
      nb = 1; if (wasnb) ioctlsocket(s, FIONBIO, &nb);
      if (rc == 0) { if (attempt) logline("spoof: proxy6 retry ok attempt=%d", attempt); return 0; }
      logline("spoof: socks5-6 fail step=%d attempt=%d", rc, attempt);
    }
    WSASetLastError(WSAECONNREFUSED);
    return SOCKET_ERROR;
  }
}

static int g_connect_calls;
/* remember hosts the proxy refused (rep!=0) so later connects go direct immediately */
static DWORD g_badip[64];
static int g_badip_n;
static int ip_is_bad(DWORD ip) { int i; for (i = 0; i < g_badip_n; i++) if (g_badip[i] == ip) return 1; return 0; }
static void ip_mark_bad(DWORD ip) { if (g_badip_n < 64 && !ip_is_bad(ip)) g_badip[g_badip_n++] = ip; }

static int WINAPI h_connect(SOCKET s, const struct sockaddr *name, int namelen)
{
  static int fc;
  g_connect_calls++;
  if (!fc) { fc = 1; logfirst("connect"); }
  if (!o_connect || !name) return o_connect(s, name, namelen);
  if (name->sa_family == AF_INET) {
    struct sockaddr_in *in = (struct sockaddr_in *)name;
    return do_connect(s, in->sin_addr.s_addr, in->sin_port);
  }
  if (name->sa_family == AF_INET6 && namelen >= (int)sizeof(struct sockaddr_in6)) {
    struct sockaddr_in6 *in6 = (struct sockaddr_in6 *)name;
    const unsigned char *b = in6->sin6_addr.s6_addr;
    /* v4-mapped (::ffff:a.b.c.d) or v4-compatible (::a.b.c.d) */
    int zero = 1, k;
    for (k = 0; k < 10; k++) if (b[k]) { zero = 0; break; }
    if (zero && (b[10] == 0xFF && b[11] == 0xFF)) {
      DWORD ip; memcpy(&ip, b + 12, 4);
      return do_connect(s, ip, in6->sin6_port);
    }
    if (g_proxyOn) return do_connect6(s, b, in6->sin6_port);
  }
  return o_connect(s, name, namelen);
}

static int WINAPI h_WSAConnect(SOCKET s, const struct sockaddr *name, int namelen, LPWSABUF a, LPWSABUF b, LPQOS c, LPQOS d)
{
  static int fc;
  if (!fc) { fc = 1; logfirst("WSAConnect"); }
  if (!o_WSAConnect || !name) return o_WSAConnect(s, name, namelen, a, b, c, d);
  if (name->sa_family == AF_INET) {
    struct sockaddr_in *in = (struct sockaddr_in *)name;
    return do_connect(s, in->sin_addr.s_addr, in->sin_port);
  }
  if (name->sa_family == AF_INET6 && namelen >= (int)sizeof(struct sockaddr_in6)) {
    struct sockaddr_in6 *in6 = (struct sockaddr_in6 *)name;
    const unsigned char *b = in6->sin6_addr.s6_addr;
    int zero = 1, k;
    for (k = 0; k < 10; k++) if (b[k]) { zero = 0; break; }
    if (zero && (b[10] == 0xFF && b[11] == 0xFF)) {
      DWORD ip; memcpy(&ip, b + 12, 4);
      return do_connect(s, ip, in6->sin6_port);
    }
    if (g_proxyOn) return do_connect6(s, b, in6->sin6_port);
  }
  return o_WSAConnect(s, name, namelen, a, b, c, d);
}

/* GetProcAddress: Chromium resolves connect etc. dynamically */
typedef FARPROC (WINAPI *PGPA)(HMODULE, LPCSTR);
static PGPA o_GetProcAddress;

typedef BOOL (WINAPI *PCONNECTEX)(SOCKET, const struct sockaddr *, int, PVOID, DWORD, LPDWORD, LPOVERLAPPED);
static PCONNECTEX o_ConnectEx;
static BOOL WINAPI h_ConnectEx(SOCKET, const struct sockaddr *, int, PVOID, DWORD, LPDWORD, LPOVERLAPPED);

static FARPROC WINAPI h_GetProcAddress(HMODULE m, LPCSTR name)
{
  FARPROC r = o_GetProcAddress ? o_GetProcAddress(m, name) : NULL;
  if (name) {
    if (!strcmp(name, "connect"))        { if (!o_connect) o_connect = (Pconnect)r;        return (FARPROC)h_connect; }
    if (!strcmp(name, "WSAConnect"))      { if (!o_WSAConnect) o_WSAConnect = (PWSAConnect)r;   return (FARPROC)h_WSAConnect; }
    if (name[0] == 'C' && !strcmp(name, "ConnectEx")) { if (!o_ConnectEx) o_ConnectEx = (PCONNECTEX)r;   return (FARPROC)h_ConnectEx; }
    if (!strcmp(name, "GetVolumeInformationW")) { if (!o_GetVolumeInformationW) o_GetVolumeInformationW = (PCGVIW)r; return (FARPROC)h_GetVolumeInformationW; }
    if (!strcmp(name, "GetComputerNameW"))   { if (!o_GetComputerNameW) o_GetComputerNameW = (PCGCNW)r; return (FARPROC)h_GetComputerNameW; }
    if (!strcmp(name, "GetComputerNameExW"))  { if (!o_GetComputerNameExW) o_GetComputerNameExW = (PCGCNEW)r; return (FARPROC)h_GetComputerNameExW; }
    if (!strcmp(name, "gethostname"))      { if (!o_gethostname) o_gethostname = (Pgethostname)r; return (FARPROC)h_gethostname; }
    if (!strcmp(name, "GetAdaptersAddresses")) { if (!o_GetAdaptersAddresses) o_GetAdaptersAddresses = (PGAA)r; return (FARPROC)h_GetAdaptersAddresses; }
    if (!strcmp(name, "SetupDiGetDeviceRegistryPropertyW")) { if (!o_SetupDiGetDeviceRegistryPropertyW) o_SetupDiGetDeviceRegistryPropertyW = (PSetupDiGetDeviceRegistryPropertyW)r; return (FARPROC)h_SetupDiGetDeviceRegistryPropertyW; }
    if (!strcmp(name, "GetFileInformationByHandle")) { if (!o_GetFileInformationByHandle) o_GetFileInformationByHandle = (PGetFileInformationByHandle)r; return (FARPROC)h_GetFileInformationByHandle; }
    if (!strcmp(name, "CreateFileW")) { if (!o_CreateFileW) o_CreateFileW = (PCreateFileW)r; return (FARPROC)h_CreateFileW; }
    if (!strcmp(name, "GetFileAttributesW")) { if (!o_GetFileAttributesW) o_GetFileAttributesW = (PGetFileAttributesW)r; return (FARPROC)h_GetFileAttributesW; }
    if (!strcmp(name, "GetFileAttributesExW")) { if (!o_GetFileAttributesExW) o_GetFileAttributesExW = (PGetFileAttributesExW)r; return (FARPROC)h_GetFileAttributesExW; }
    if (!strcmp(name, "FindFirstFileW")) { if (!o_FindFirstFileW) o_FindFirstFileW = (PFindFirstFileW)r; return (FARPROC)h_FindFirstFileW; }
    if (!strcmp(name, "DeleteFileW")) { if (!o_DeleteFileW) o_DeleteFileW = (PDeleteFileW)r; return (FARPROC)h_DeleteFileW; }
    if (!strcmp(name, "CreateDirectoryW")) { if (!o_CreateDirectoryW) o_CreateDirectoryW = (PCreateDirectoryW)r; return (FARPROC)h_CreateDirectoryW; }
    if (!strcmp(name, "GetUserNameW")) { if (!o_GetUserNameW) o_GetUserNameW = (PGetUserNameW)r; return (FARPROC)h_GetUserNameW; }
    if (!strcmp(name, "GetSystemInfo")) { if (!o_GetSystemInfo) o_GetSystemInfo = (PGetSystemInfo)r; return (FARPROC)h_GetSystemInfo; }
    if (g_ver && !strcmp(name, "GetVersionExW"))   { if (!o_GetVersionExW) o_GetVersionExW = (PGetVersionExW)r; return (FARPROC)h_GetVersionExW; }
    if (g_reg && !strcmp(name, "RegQueryValueExW")) { if (!o_RegQueryValueExW) o_RegQueryValueExW = (PRegQueryValueExW)r; return (FARPROC)h_RegQueryValueExW; }
    if (g_smbios && !strcmp(name, "NtQuerySystemInformation")) { if (!o_NtQSI) o_NtQSI = (PNtQSI)r; return (FARPROC)h_NtQSI; }
    if (g_smbios && !strcmp(name, "GetSystemFirmwareTable")) { if (!o_GetSystemFirmwareTable) o_GetSystemFirmwareTable = (PGetSystemFirmwareTable)r; return (FARPROC)h_GetSystemFirmwareTable; }
  }
  return r;
}

/* ConnectEx: Chromium uses overlapped connect for its network service; route it through the proxy
  by doing a plain blocking connect (which our h_connect proxies) then completing the OVERLAPPED.
  Uses a per-call blocking handshake on the same socket via a temporary switch to blocking mode. */
static int sockaddr_ip4(const struct sockaddr *name, int namelen, DWORD *ip, USHORT *port)
{
  if (name->sa_family == AF_INET && namelen >= (int)sizeof(struct sockaddr_in)) {
    struct sockaddr_in *in = (struct sockaddr_in *)name;
    *ip = in->sin_addr.s_addr; *port = in->sin_port; return 1;
  }
  if (name->sa_family == AF_INET6 && namelen >= (int)sizeof(struct sockaddr_in6)) {
    struct sockaddr_in6 *in6 = (struct sockaddr_in6 *)name;
    const unsigned char *b = in6->sin6_addr.s6_addr;
    int z = 1, k;
    for (k = 0; k < 10; k++) if (b[k]) { z = 0; break; }
    if (z && b[10] == 0xFF && b[11] == 0xFF) { memcpy(ip, b + 12, 4); *port = in6->sin6_port; return 1; }
  }
  return 0;
}

static BOOL WINAPI h_ConnectEx(SOCKET s, const struct sockaddr *name, int namelen, PVOID sb, DWORD sl,
                LPDWORD sc, LPOVERLAPPED ol)
{
  DWORD ip; USHORT port;
  int is6 = 0;
  static int fc;
  if (!fc) { fc = 1; logfirst("ConnectEx"); }
  if (!o_ConnectEx || !name || !g_proxyOn)
    return o_ConnectEx(s, name, namelen, sb, sl, sc, ol);
  if (sockaddr_ip4(name, namelen, &ip, &port)) {
    if (do_connect(s, ip, port) != 0) { logline("spoof: ConnectEx do_connect failed fam=%d", name->sa_family); if (sc) *sc = 0; WSASetLastError(WSAECONNREFUSED); return FALSE; }
  } else if (name->sa_family == AF_INET6 && namelen >= (int)sizeof(struct sockaddr_in6)) {
    struct sockaddr_in6 *in6 = (struct sockaddr_in6 *)name;
    is6 = 1; port = in6->sin6_port;
    if (do_connect6(s, in6->sin6_addr.s6_addr, port) != 0) { logline("spoof: ConnectEx do6 failed"); if (sc) *sc = 0; WSASetLastError(WSAECONNREFUSED); return FALSE; }
  } else {
    return o_ConnectEx(s, name, namelen, sb, sl, sc, ol);
  }
  logline("spoof: ConnectEx PROXIED fam=%d%s", name->sa_family, is6 ? " v6" : "");
  if (sc) *sc = (sl ? sl : 0);     /* pretend the send buffer was consumed */
  if (ol) {
    ol->Internal = 0;        /* STATUS_SUCCESS */
    ol->InternalHigh = 0;
    if (ol->hEvent) SetEvent(ol->hEvent);
  }
  return TRUE;
}

#ifdef NETONLY
typedef int (WSAAPI *Pgetaddrinfo)(PCSTR, PCSTR, const ADDRINFOA *, PADDRINFOA *);
typedef int (WSAAPI *PGetAddrInfoW)(PCWSTR, PCWSTR, const ADDRINFOW *, PADDRINFOW *);
typedef struct hostent *(WSAAPI *Pgethostbyname)(const char *);
typedef void (WSAAPI *Pfreeaddrinfo)(PADDRINFOA);
typedef void (WSAAPI *PFreeAddrInfoW)(PADDRINFOW);
static Pgetaddrinfo o_getaddrinfo;
static PGetAddrInfoW o_GetAddrInfoW;
static Pgethostbyname o_gethostbyname;
static Pfreeaddrinfo o_freeaddrinfo;
static PFreeAddrInfoW o_FreeAddrInfoW;
static WCHAR g_realName[64];
static char g_realNameA[64];
static CRITICAL_SECTION g_ai_lock;
static void *g_ai_blocks[128];
static int g_ai_n;

typedef struct { ADDRINFOA ai; SOCKADDR_IN sa; SOCKADDR_IN6 sa6; } MYAIA;
typedef struct { ADDRINFOW ai; SOCKADDR_IN sa; SOCKADDR_IN6 sa6; } MYAIW;

static int own_name_a(const char *n)
{
    if (!n || !*n) return 0;
    if (g_cfgName[0] && _stricmp(n, g_cfgName) == 0) return 1;
    if (g_realNameA[0] && _stricmp(n, g_realNameA) == 0) return 1;
    return 0;
}
static int own_name_w(const WCHAR *n)
{
    if (!n || !*n) return 0;
    if (g_name[0] && _wcsicmp(n, g_name) == 0) return 1;
    if (g_realName[0] && _wcsicmp(n, g_realName) == 0) return 1;
    return 0;
}
static void ai_track(void *p)
{
    EnterCriticalSection(&g_ai_lock);
    if (g_ai_n < 128) g_ai_blocks[g_ai_n++] = p;
    LeaveCriticalSection(&g_ai_lock);
}
static int ai_untrack(void *p)
{
    int i, found = 0;
    EnterCriticalSection(&g_ai_lock);
    for (i = 0; i < g_ai_n; i++) if (g_ai_blocks[i] == p) { g_ai_blocks[i] = g_ai_blocks[--g_ai_n]; found = 1; break; }
    LeaveCriticalSection(&g_ai_lock);
    return found;
}
static int make_ai_a(PCSTR service, const ADDRINFOA *hints, PADDRINFOA *res)
{
    MYAIA *m;
    int fam = (hints && hints->ai_family == AF_INET6) ? AF_INET6 : AF_INET;
    int port = (service && *service) ? atoi(service) : 0;
    if (!res) return EAI_FAIL;
    m = (MYAIA *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(*m));
    if (!m) return EAI_MEMORY;
    m->ai.ai_family = fam;
    m->ai.ai_socktype = hints ? hints->ai_socktype : 0;
    m->ai.ai_protocol = hints ? hints->ai_protocol : 0;
    if (fam == AF_INET6) {
        m->sa6.sin6_family = AF_INET6; m->sa6.sin6_addr = in6addr_loopback; m->sa6.sin6_port = htons((u_short)port);
        m->ai.ai_addr = (SOCKADDR *)&m->sa6; m->ai.ai_addrlen = sizeof(m->sa6);
    } else {
        m->sa.sin_family = AF_INET; m->sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK); m->sa.sin_port = htons((u_short)port);
        m->ai.ai_addr = (SOCKADDR *)&m->sa; m->ai.ai_addrlen = sizeof(m->sa);
    }
    if (hints && (hints->ai_flags & AI_CANONNAME)) m->ai.ai_canonname = g_cfgName;
    m->ai.ai_next = NULL;
    ai_track(m);
    *res = &m->ai;
    return 0;
}
static int make_ai_w(PCWSTR service, const ADDRINFOW *hints, PADDRINFOW *res)
{
    MYAIW *m;
    int fam = (hints && hints->ai_family == AF_INET6) ? AF_INET6 : AF_INET;
    int port = (service && *service) ? _wtoi(service) : 0;
    if (!res) return EAI_FAIL;
    m = (MYAIW *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(*m));
    if (!m) return EAI_MEMORY;
    m->ai.ai_family = fam;
    m->ai.ai_socktype = hints ? hints->ai_socktype : 0;
    m->ai.ai_protocol = hints ? hints->ai_protocol : 0;
    if (fam == AF_INET6) {
        m->sa6.sin6_family = AF_INET6; m->sa6.sin6_addr = in6addr_loopback; m->sa6.sin6_port = htons((u_short)port);
        m->ai.ai_addr = (SOCKADDR *)&m->sa6; m->ai.ai_addrlen = sizeof(m->sa6);
    } else {
        m->sa.sin_family = AF_INET; m->sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK); m->sa.sin_port = htons((u_short)port);
        m->ai.ai_addr = (SOCKADDR *)&m->sa; m->ai.ai_addrlen = sizeof(m->sa);
    }
    if (hints && (hints->ai_flags & AI_CANONNAME)) m->ai.ai_canonname = g_name;
    m->ai.ai_next = NULL;
    ai_track(m);
    *res = &m->ai;
    return 0;
}
static int WSAAPI h_getaddrinfo(PCSTR node, PCSTR service, const ADDRINFOA *hints, PADDRINFOA *res)
{
    if (own_name_a(node)) { logline("spoof: DNS own-name %s", node); return make_ai_a(service, hints, res); }
    return o_getaddrinfo ? o_getaddrinfo(node, service, hints, res) : EAI_FAIL;
}
static int WSAAPI h_GetAddrInfoW(PCWSTR node, PCWSTR service, const ADDRINFOW *hints, PADDRINFOW *res)
{
    if (own_name_w(node)) { logline("spoof: DNS own-name-w %S", node); return make_ai_w(service, hints, res); }
    return o_GetAddrInfoW ? o_GetAddrInfoW(node, service, hints, res) : EAI_FAIL;
}
static struct hostent *WSAAPI h_gethostbyname(const char *node)
{
    static struct hostent he;
    static char *al[1] = { NULL };
    static struct in_addr ia;
    static char *addr[2] = { NULL, NULL };
    if (own_name_a(node)) {
        ia.s_addr = htonl(INADDR_LOOPBACK);
        he.h_name = g_cfgName; he.h_aliases = al; he.h_addrtype = AF_INET; he.h_length = 4;
        addr[0] = (char *)&ia; addr[1] = NULL; he.h_addr_list = addr;
        logline("spoof: DNS own-name (gethostbyname) %s", node);
        return &he;
    }
    return o_gethostbyname ? o_gethostbyname(node) : NULL;
}
static void WSAAPI h_freeaddrinfo(PADDRINFOA p)
{
    if (!p) return;
    if (ai_untrack(p)) HeapFree(GetProcessHeap(), 0, p);
    else if (o_freeaddrinfo) o_freeaddrinfo(p);
}
static void WSAAPI h_FreeAddrInfoW(PADDRINFOW p)
{
    if (!p) return;
    if (ai_untrack(p)) HeapFree(GetProcessHeap(), 0, p);
    else if (o_FreeAddrInfoW) o_FreeAddrInfoW(p);
}
#endif

/* minimal x86 length decoder: return length of the instruction at p (enough for prologues) */
static int insn_len(const BYTE *p)
{
  const BYTE *s = p;
  int i;
  for (i = 0; i < 4; i++) {          /* legacy prefixes */
    if (p[0] == 0x66 || p[0] == 0x67 || p[0] == 0xF0 || p[0] == 0xF2 || p[0] == 0xF3 ||
      p[0] == 0x2E || p[0] == 0x3E || p[0] == 0x26 || p[0] == 0x36 || p[0] == 0x64 || p[0] == 0x65)
      p++;
    else break;
  }
  /* REX (not on x86), opcode */
  switch (*p) {
  case 0xE9: case 0xE8: return (int)(p - s) + 5;      /* jmp/call rel32 */
  case 0xEB: return (int)(p - s) + 2;           /* jmp rel8 */
  case 0x9A: return (int)(p - s) + 7;           /* call far */
  case 0x8B: case 0x89: case 0x8D: case 0x03: case 0x2B:  /* ModRM + reg */
  case 0x33: case 0x0B: case 0x23: case 0x3B: case 0x85: case 0x87:
    { int mod = (p[1] >> 6) & 3; int rm = p[1] & 7; int len = 2;
     if (mod != 3) { if (rm == 4) len++; /* SIB */ len += 4; /* disp32 */ }
     else if (rm == 4) len++;                /* SIB */
     return (int)(p - s) + len; }
  case 0xB8: case 0xB9: case 0xBA: case 0xBB: case 0xBC: case 0xBD: case 0xBE: case 0xBF:
    return (int)(p - s) + 5;
  default:
    if (*p >= 0x50 && *p <= 0x5F) return (int)(p - s) + 1;  /* push/pop reg */
    if (*p == 0x68) return (int)(p - s) + 5;         /* push imm32 */
    if (*p == 0x6A) return (int)(p - s) + 2;         /* push imm8 */
    return (int)(p - s) + 2;                 /* assume 2 */
  }
}

/* inline hook (E9 jmp) with a trampoline; returns the callable original */
static void *InlineHook(void *target, void *hook)
{
  BYTE *t = (BYTE *)target;
  BYTE *tr;
  DWORD old, copy = 0;
  if (!t || !hook) return target;
  if (t[0] == 0xE9) return target;         /* already hooked */
  /* copy whole instructions covering at least 5 bytes */
  while (copy < 5) {
    int l = insn_len(t + copy);
    if (l <= 0) { l = 1; }
    copy += l;
    if (copy > 16) break;
  }
  tr = (BYTE *)VirtualAlloc(NULL, 48, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
  if (!tr) return target;
  memcpy(tr, t, copy);
  tr[copy] = 0xE9;
  *(DWORD *)(tr + copy + 1) = (DWORD)(t + copy) - (DWORD)(tr + copy + 5);
  if (!VirtualProtect(t, copy, PAGE_EXECUTE_READWRITE, &old)) { VirtualFree(tr, 0, MEM_RELEASE); return target; }
  memset(t, 0x90, copy);              /* pad */
  t[0] = 0xE9;
  *(DWORD *)(t + 1) = (DWORD)hook - (DWORD)(t + 5);
  VirtualProtect(t, copy, old, &old);
  return tr;
}

/* install an IAT hook once per slot */
static void set_slot(void **slot, void *hook, void **orig_out)
{
  DWORD old;
  if (*slot == (void *)hook) return;     /* already hooked band -> keep orig */
  if (orig_out && *orig_out == NULL) *orig_out = *slot;
  if (VirtualProtect(slot, 4, PAGE_READWRITE, &old)) {
    *slot = hook;
    VirtualProtect(slot, 4, old, &old);
  }
}

static int readable(void *p, SIZE_T sz)
{
  BYTE *a = (BYTE *)p, *end = a + sz;
  MEMORY_BASIC_INFORMATION mbi;
  int guard = 0;
  while (a < end) {
    BYTE *prev = a;
    if (!VirtualQuery(a, &mbi, sizeof(mbi))) return 0;
    if (mbi.State != MEM_COMMIT) return 0;
    if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return 0;
    a = (BYTE *)mbi.BaseAddress + mbi.RegionSize;
    if (a <= prev || guard++ > 4096) break;
  }
  return 1;
}

static int patch_name(const char *fn, void **slot)
{
  if (g_vol && !strcmp(fn, "GetVolumeInformationW")) { set_slot(slot, (void *)h_GetVolumeInformationW, (void **)&o_GetVolumeInformationW); return 1; }
  else if (g_cname && !strcmp(fn, "GetComputerNameW"))   { set_slot(slot, (void *)h_GetComputerNameW,   (void **)&o_GetComputerNameW);   return 1; }
  else if (g_cname && !strcmp(fn, "GetComputerNameExW"))  { set_slot(slot, (void *)h_GetComputerNameExW,  (void **)&o_GetComputerNameExW);  return 1; }
  else if (g_ver && !strcmp(fn, "GetVersionExW"))  { set_slot(slot, (void *)h_GetVersionExW,  (void **)&o_GetVersionExW);  return 1; }
  else if (g_prod && !strcmp(fn, "GetProductInfo")) { set_slot(slot, (void *)h_GetProductInfo,  (void **)&o_GetProductInfo);  return 1; }
  else if (g_geo && !strcmp(fn, "GetGeoInfoW"))   { set_slot(slot, (void *)h_GetGeoInfoW,   (void **)&o_GetGeoInfoW);   return 1; }
  else if (g_macOn && !strcmp(fn, "GetAdaptersInfo")){ set_slot(slot, (void *)h_GetAdaptersInfo,  (void **)&o_GetAdaptersInfo); return 1; }
  else if (g_macOn && !strcmp(fn, "GetAdaptersAddresses")){ set_slot(slot, (void *)h_GetAdaptersAddresses, (void **)&o_GetAdaptersAddresses); return 1; }
  else if (g_smbios && !strcmp(fn, "GetSystemFirmwareTable")) { set_slot(slot, (void *)h_GetSystemFirmwareTable, (void **)&o_GetSystemFirmwareTable); return 1; }
  else if (g_smbios && !strcmp(fn, "NtQuerySystemInformation")) { set_slot(slot, (void *)h_NtQSI, (void **)&o_NtQSI); return 1; }
  else if (g_disk && !strcmp(fn, "DeviceIoControl")) { set_slot(slot, (void *)h_DeviceIoControl,  (void **)&o_DeviceIoControl);  return 1; }
  else if (g_mon && !strcmp(fn, "EnumDisplayDevicesW")){ set_slot(slot, (void *)h_EnumDisplayDevicesW,(void **)&o_EnumDisplayDevicesW); return 1; }
  else if (g_host && !strcmp(fn, "GetHostNameW"))   { set_slot(slot, (void *)h_GetHostNameW,   (void **)&o_GetHostNameW);   return 1; }
  else if (g_host && !strcmp(fn, "gethostname"))    { set_slot(slot, (void *)h_gethostname,    (void **)&o_gethostname);    return 1; }
  else if (!strcmp(fn, "SetupDiGetDeviceRegistryPropertyW")) { set_slot(slot, (void *)h_SetupDiGetDeviceRegistryPropertyW, (void **)&o_SetupDiGetDeviceRegistryPropertyW); return 1; }
  else if (!strcmp(fn, "GetFileInformationByHandle")) { set_slot(slot, (void *)h_GetFileInformationByHandle, (void **)&o_GetFileInformationByHandle); return 1; }
  else if (!strcmp(fn, "CreateFileW")) { set_slot(slot, (void *)h_CreateFileW, (void **)&o_CreateFileW); return 1; }
  else if (!strcmp(fn, "GetFileAttributesW")) { set_slot(slot, (void *)h_GetFileAttributesW, (void **)&o_GetFileAttributesW); return 1; }
  else if (!strcmp(fn, "GetFileAttributesExW")) { set_slot(slot, (void *)h_GetFileAttributesExW, (void **)&o_GetFileAttributesExW); return 1; }
  else if (!strcmp(fn, "FindFirstFileW")) { set_slot(slot, (void *)h_FindFirstFileW, (void **)&o_FindFirstFileW); return 1; }
  else if (!strcmp(fn, "DeleteFileW")) { set_slot(slot, (void *)h_DeleteFileW, (void **)&o_DeleteFileW); return 1; }
  else if (!strcmp(fn, "CreateDirectoryW")) { set_slot(slot, (void *)h_CreateDirectoryW, (void **)&o_CreateDirectoryW); return 1; }
  else if (g_host && !strcmp(fn, "GetUserNameW"))   { set_slot(slot, (void *)h_GetUserNameW,   (void **)&o_GetUserNameW);   return 1; }
  else if (!strcmp(fn, "GetSystemInfo"))        { set_slot(slot, (void *)h_GetSystemInfo,   (void **)&o_GetSystemInfo);   return 1; }
  else if (g_ram && !strcmp(fn, "GlobalMemoryStatusEx")){ set_slot(slot, (void *)h_GlobalMemoryStatusEx, (void **)&o_GlobalMemoryStatusEx); return 1; }
  else if (g_reg && !strcmp(fn, "RegQueryValueExW")) { set_slot(slot, (void *)h_RegQueryValueExW, (void **)&o_RegQueryValueExW); return 1; }
  else if (g_rega && !strcmp(fn, "RegQueryValueExA")) { set_slot(slot, (void *)h_RegQueryValueExA, (void **)&o_RegQueryValueExA); return 1; }
  else if (g_net && !g_noiat && !strcmp(fn, "connect"))     { set_slot(slot, (void *)h_connect,      (void **)&o_connect);     return 1; }
  else if (g_net && !g_noiat && !strcmp(fn, "WSAConnect"))    { set_slot(slot, (void *)h_WSAConnect,    (void **)&o_WSAConnect);    return 1; }
  else if (g_net && !g_noiat && !strcmp(fn, "ConnectEx"))    { set_slot(slot, (void *)h_ConnectEx,     (void **)&o_ConnectEx);    return 1; }
  else if (g_net && !g_nogpa && !strcmp(fn, "GetProcAddress"))  { set_slot(slot, (void *)h_GetProcAddress,  (void **)&o_GetProcAddress);  return 1; }
  return 0;
}

static int patch_module(HMODULE mod)
{
  BYTE *base = (BYTE *)mod;
  IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
  IMAGE_NT_HEADERS *nt;
  IMAGE_IMPORT_DESCRIPTOR *imp;
  DWORD impRva;
  int n = 0;

  if (!readable(base, sizeof(*dos)) || dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;
  if (!readable(base + dos->e_lfanew, sizeof(*nt))) return 0;
  nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
  if (nt->Signature != IMAGE_NT_SIGNATURE) return 0;
  impRva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
  if (!impRva) return 0;
  if (!readable(base + impRva, sizeof(*imp))) return 0;

  imp = (IMAGE_IMPORT_DESCRIPTOR *)(base + impRva);
  for (; readable(imp, sizeof(*imp)) && imp->Name; imp++) {
    DWORD guard = 0;
    DWORD oftRva = imp->OriginalFirstThunk ? imp->OriginalFirstThunk : imp->FirstThunk;
    IMAGE_THUNK_DATA *oft = (IMAGE_THUNK_DATA *)(base + oftRva);
    IMAGE_THUNK_DATA *ft = (IMAGE_THUNK_DATA *)(base + imp->FirstThunk);
    for (; readable(oft, sizeof(*oft)) && readable(ft, sizeof(*ft)) && oft->u1.AddressOfData && guard < 8192; oft++, ft++, guard++) {
      IMAGE_IMPORT_BY_NAME *nm;
      const char *fn;
      void **slot = (void **)&ft->u1.Function;
      if (oft->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;
      if (!readable(base + oft->u1.AddressOfData, sizeof(IMAGE_IMPORT_BY_NAME))) continue;
      nm = (IMAGE_IMPORT_BY_NAME *)(base + oft->u1.AddressOfData);
      fn = (const char *)nm->Name;
      n += patch_name(fn, slot);
    }
  }

  /* delay-load imports (Chromium resolves connect & co this way) */
  if (g_delay) {
    DWORD dRva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT].VirtualAddress;
    if (dRva && readable(base + dRva, sizeof(IMAGE_DELAYLOAD_DESCRIPTOR))) {
      IMAGE_DELAYLOAD_DESCRIPTOR *dl = (IMAGE_DELAYLOAD_DESCRIPTOR *)(base + dRva);
      int kd = 0;
      for (; kd < 32 && readable(dl, sizeof(*dl)) && dl->DllNameRVA; dl++, kd++) {
        IMAGE_THUNK_DATA *intp = (IMAGE_THUNK_DATA *)(base + dl->ImportNameTableRVA);
        IMAGE_THUNK_DATA *iat = (IMAGE_THUNK_DATA *)(base + dl->ImportAddressTableRVA);
        DWORD g2 = 0;
        for (; g2 < 1024 && readable(intp, sizeof(*intp)) && readable(iat, sizeof(*iat)) && intp->u1.AddressOfData; intp++, iat++, g2++) {
          IMAGE_IMPORT_BY_NAME *nm;
          if (intp->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;
          if (!readable(base + intp->u1.AddressOfData, sizeof(IMAGE_IMPORT_BY_NAME))) continue;
          nm = (IMAGE_IMPORT_BY_NAME *)(base + intp->u1.AddressOfData);
          n += patch_name((const char *)nm->Name, (void **)&iat->u1.Function);
        }
      }
    }
  }
  return n;
}

/* track fully-processed modules so later passes can skip them */
#ifdef NETONLY
static int patch_dns_fn(const char *fn, void **slot)
{
  if (!strcmp(fn, "getaddrinfo"))    { set_slot(slot, (void *)h_getaddrinfo,    (void **)&o_getaddrinfo);    return 1; }
  if (!strcmp(fn, "gethostbyname"))  { set_slot(slot, (void *)h_gethostbyname,  (void **)&o_gethostbyname);  return 1; }
  if (!strcmp(fn, "freeaddrinfo"))   { set_slot(slot, (void *)h_freeaddrinfo,   (void **)&o_freeaddrinfo);   return 1; }
  if (!strcmp(fn, "GetAddrInfoW"))   { set_slot(slot, (void *)h_GetAddrInfoW,   (void **)&o_GetAddrInfoW);   return 1; }
  if (!strcmp(fn, "FreeAddrInfoW"))  { set_slot(slot, (void *)h_FreeAddrInfoW,  (void **)&o_FreeAddrInfoW);  return 1; }
  return 0;
}
static void patch_dns_module(HMODULE mod)
{
  BYTE *base = (BYTE *)mod;
  logline("spoof: dns module %p", mod);
  IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
  IMAGE_NT_HEADERS *nt;
  IMAGE_IMPORT_DESCRIPTOR *imp;
  DWORD impRva;
  if (!mod || !readable(base, sizeof(*dos)) || dos->e_magic != IMAGE_DOS_SIGNATURE) return;

  if (!readable(base + dos->e_lfanew, sizeof(*nt))) return;
  nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
  if (nt->Signature != IMAGE_NT_SIGNATURE) return;
  impRva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
  if (!impRva || !readable(base + impRva, sizeof(*imp))) return;
  imp = (IMAGE_IMPORT_DESCRIPTOR *)(base + impRva);
  for (; readable(imp, sizeof(*imp)) && imp->Name; imp++) {
    DWORD guard = 0;
    DWORD oftRva = imp->OriginalFirstThunk ? imp->OriginalFirstThunk : imp->FirstThunk;
    IMAGE_THUNK_DATA *oft = (IMAGE_THUNK_DATA *)(base + oftRva);
    IMAGE_THUNK_DATA *ft = (IMAGE_THUNK_DATA *)(base + imp->FirstThunk);
    for (; readable(oft, sizeof(*oft)) && readable(ft, sizeof(*ft)) && oft->u1.AddressOfData && guard < 8192; oft++, ft++, guard++) {
      IMAGE_IMPORT_BY_NAME *nm;
      if (oft->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;
      if (!readable(base + oft->u1.AddressOfData, sizeof(IMAGE_IMPORT_BY_NAME))) continue;
      nm = (IMAGE_IMPORT_BY_NAME *)(base + oft->u1.AddressOfData);
      patch_dns_fn((const char *)nm->Name, (void **)&ft->u1.Function);
    }
  }
}
static void patch_dns_all(void)
{
  HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, GetCurrentProcessId());
  MODULEENTRY32 me;
  if (snap == INVALID_HANDLE_VALUE) return;
  me.dwSize = sizeof(me);
  if (Module32First(snap, &me)) do { patch_dns_module(me.hModule); } while (Module32Next(snap, &me));
  CloseHandle(snap);
}
#endif
#define MAX_SEEN 4096
static HMODULE g_seen[MAX_SEEN];
static int g_seen_n;
static int mod_seen(HMODULE m)
{
  int i;
  for (i = 0; i < g_seen_n; i++) if (g_seen[i] == m) return 1;
  return 0;
}
static void mark_mod(HMODULE m)
{
  if (g_seen_n < MAX_SEEN) g_seen[g_seen_n++] = m;
}

static int patch_all(void)
{
  HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, GetCurrentProcessId());
  MODULEENTRY32 me;
  int total = 0;
  if (snap == INVALID_HANDLE_VALUE) return 0;
  me.dwSize = sizeof(me);
  if (Module32First(snap, &me)) do { total += patch_module(me.hModule); } while (Module32Next(snap, &me));
  CloseHandle(snap);
  return total;
}

static void verify(int tag, int patched)
{
  WCHAR nm[64]; DWORD n = 64; WCHAR vn[16]; DWORD ser = 0;
  logline("spoof: verify(%d) a o_vol=%p o_name=%p", tag, (void *)o_GetVolumeInformationW, (void *)o_GetComputerNameW);
  GetComputerNameW(nm, &n);
  logline("spoof: verify(%d) b name=%S", tag, nm);
  logline("spoof: verify(%d) c o_vol==hook:%d", tag, o_GetVolumeInformationW == (PCGVIW)h_GetVolumeInformationW);
  g_verbose = 1;
  GetVolumeInformationW(L"C:\\", vn, 16, &ser, 0, 0, 0, 0);
  g_verbose = 0;
  logline("spoof: pass %d patched=%d verify name=%S serial=%08lX", tag, patched, nm, ser);
}

static DWORD WINAPI worker(LPVOID p)
{
  DWORD seed;
  int i;
  HMODULE mainmod;
  (void)p;
  LoadCfg();
  state_cfg();
  if (g_nohooks) {
    logline("spoof: nohooks=1 (module mapped, no hooks)");
    state_ready(0);
    return 0;
  }
#ifdef NETONLY
  {
    DWORD rn = 64;
    g_realName[0] = 0; g_realNameA[0] = 0;
    if (GetComputerNameW(g_realName, &rn))
      WideCharToMultiByte(CP_ACP, 0, g_realName, -1, g_realNameA, sizeof(g_realNameA), 0, 0);
  }
#endif
  seed = fnv(g_cfgId);
  wcscpy(g_metaTail, L"DeviceSync\\vcredist_x86.exe");
  if (!g_metaDir[0] && g_metaPath[0]) {     /* derive dir from meta file path */
    wcscpy(g_metaDir, g_metaPath);
    WCHAR *s = wcsrchr(g_metaDir, L'\\');
    if (s) *s = 0;
  }

  g_serial = 0x10000000u | (seed & 0x0FFFFFFF);
  wsprintfW(g_name, L"DESKTOP-%04X%03X", (seed >> 8) & 0xFFFF, seed & 0xFFF);
  g_build = 19045 + (seed % 4);
  {
    DWORD h2 = seed ^ 0x9E3779B9u;
    g_mac[0] = 0x02; g_mac[1] = (BYTE)(seed >> 8); g_mac[2] = (BYTE)(seed >> 16);
    g_mac[3] = (BYTE)(seed >> 24); g_mac[4] = (BYTE)h2; g_mac[5] = (BYTE)(h2 >> 8);
    wsprintfW(g_guid, L"%08lX-%04X-%04X-%04X-%04X%08lX",
         (unsigned long)seed, (seed >> 16) & 0xFFFF, h2 & 0xFFFF,
         (h2 >> 16) & 0xFFFF, (seed >> 8) & 0xFFFF, (unsigned long)h2);
    wsprintfA(g_guidA, "%08lX-%04X-%04X-%04X-%04X%08lX",
         (unsigned long)seed, (seed >> 16) & 0xFFFF, h2 & 0xFFFF,
         (h2 >> 16) & 0xFFFF, (seed >> 8) & 0xFFFF, (unsigned long)h2);
    wcscpy(g_biosVendor, L"American Megatrends Inc.");
    wsprintfW(g_biosVer, L"%X.%02X", (seed % 9) + 1, seed & 0xFF);
    wcscpy(g_boardMfr, L"ASUSTeK COMPUTER INC.");
    wsprintfW(g_boardProd, L"PRIME-%04X-PRO", seed & 0xFFFF);
    wsprintfW(g_sysProd, L"System Product Name %04X", seed & 0xFFFF);
    wsprintfW(g_sysVer, L"Rev %X.%02X", (seed % 7) + 1, (seed >> 8) & 0xFF);
    wsprintfW(g_macStr, L"%02X%02X%02X%02X%02X%02X", g_mac[0], g_mac[1], g_mac[2], g_mac[3], g_mac[4], g_mac[5]);
    wsprintfW(g_monId, L"MONITOR\\PRM%04X", seed & 0xFFFF);
  }

  /* ---- apply cfg overrides over the id-derived defaults ---- */
  if (g_serialOverride && g_cfgSerial[0])
    g_serial = (DWORD)strtoul(g_cfgSerial, NULL, 16);
  if (g_nameOverride && g_cfgName[0]) {
    MultiByteToWideChar(CP_UTF8, 0, g_cfgName, -1, g_name, 63); g_name[63] = 0;
  }
  if (g_macOverride && g_cfgMac[0]) {
    unsigned b[6]; int k; char *q = g_cfgMac; int n = 0;
    for (k = 0; k < 6 && *q; k++) { unsigned v = 0; int d = 0;
      while (*q == ':' || *q == '-' || *q == '.') q++;
      while (d < 2 && *q) { char ch = *q++; int h; if (ch >= '0' && ch <= '9') h = ch - '0';
        else if (ch >= 'a' && ch <= 'f') h = ch - 'a' + 10; else if (ch >= 'A' && ch <= 'F') h = ch - 'A' + 10; else break;
        v = (v << 4) | (unsigned)h; d++; }
      b[n++] = v; }
    if (n == 6) { int j; for (j = 0; j < 6; j++) g_mac[j] = (BYTE)b[j]; }
    wsprintfW(g_macStr, L"%02X%02X%02X%02X%02X%02X", g_mac[0], g_mac[1], g_mac[2], g_mac[3], g_mac[4], g_mac[5]);
  }
  if (g_guidOverride && g_cfgGuid[0]) {
    MultiByteToWideChar(CP_UTF8, 0, g_cfgGuid, -1, g_guid, 63); g_guid[63] = 0;
    strncpy(g_guidA, g_cfgGuid, 63); g_guidA[63] = 0;
  }
  if (g_cfgBiosVendor[0]) { MultiByteToWideChar(CP_UTF8, 0, g_cfgBiosVendor, -1, g_biosVendor, 47); g_biosVendor[47] = 0; }
  if (g_cfgBiosVer[0])  { MultiByteToWideChar(CP_UTF8, 0, g_cfgBiosVer, -1, g_biosVer, 23); g_biosVer[23] = 0; }
  if (g_cfgBoardMfr[0])  { MultiByteToWideChar(CP_UTF8, 0, g_cfgBoardMfr, -1, g_boardMfr, 47); g_boardMfr[47] = 0; }
  if (g_cfgBoardProd[0]) { MultiByteToWideChar(CP_UTF8, 0, g_cfgBoardProd, -1, g_boardProd, 39); g_boardProd[39] = 0; }
  if (g_cfgSysProd[0])  { MultiByteToWideChar(CP_UTF8, 0, g_cfgSysProd, -1, g_sysProd, 39); g_sysProd[39] = 0; }
  if (g_cfgSysVer[0])   { MultiByteToWideChar(CP_UTF8, 0, g_cfgSysVer, -1, g_sysVer, 23); g_sysVer[23] = 0; }
  if (g_cfgMonId[0])   { MultiByteToWideChar(CP_UTF8, 0, g_cfgMonId, -1, g_monId, 39); g_monId[39] = 0; }
  if (g_cfgBuild)     g_build = (DWORD)g_cfgBuild;
  if (g_cfgUuid[0])    { MultiByteToWideChar(CP_UTF8, 0, g_cfgUuid, -1, g_uuidW, 39); g_uuidW[39] = 0; }
  if (g_cfgBiosSerial[0]) { MultiByteToWideChar(CP_UTF8, 0, g_cfgBiosSerial, -1, g_biosSerialW, 63); g_biosSerialW[63] = 0; }
  if (g_cfgBoardSerial[0]){ MultiByteToWideChar(CP_UTF8, 0, g_cfgBoardSerial, -1, g_boardSerialW, 63); g_boardSerialW[63] = 0; }
  if (g_cfgRamMb[0])   g_ramBytes = (ULONGLONG)atoi(g_cfgRamMb) * 1024ull * 1024ull;
  if (o_GetUserNameW) { DWORD un = 64; if (!o_GetUserNameW(g_username, &un)) g_username[0] = 0; }

  {
    char *p = g_cfgProxy;
    if (p[0]) {
      char *at = strchr(p, '@');
      char *hostport = p, *c, *u;
      if (at) {
        *at = 0;
        u = strchr(p, ':');
        if (u) {
          *u = 0;
          strncpy(g_proxyUser, p, 63); g_proxyUser[63] = 0;
          strncpy(g_proxyPass, u + 1, 63); g_proxyPass[63] = 0;
          g_proxyAuth = 1;
        }
        hostport = at + 1;
      }
      c = strchr(hostport, ':');
      if (c) {
        *c = 0;
        g_proxyIp = inet_addr(hostport);
        g_proxyPort = htons((USHORT)atoi(c + 1));
        g_proxyOn = 1;
        /* The browser (main) process runs the UI thread; a synchronous SOCKS handshake
          there can freeze the window. Only proxy CEF child processes (--type=...). */
        if (g_proxyMain == 0) {
          char *cl = GetCommandLineA();
          if (cl && !strstr(cl, "--type=")) g_proxyOn = 0;
        }
      }
    }
  }

  logline("spoof: id=%s serial=%08lX name=%S mac=%02X:%02X:%02X:%02X:%02X:%02X guid=%S proxy=%s",
      g_cfgId, g_serial, g_name, g_mac[0], g_mac[1], g_mac[2], g_mac[3], g_mac[4], g_mac[5], g_guid,
      g_proxyOn ? "on" : "off");

  /* 0) resolve the true GetAdaptersInfo export so our hook never recurses into itself,
     then inline-hook connect/WSAConnect in ws2_32 (catches IAT, delay-load, dynamic calls) */
  {
    HMODULE k = GetModuleHandleA("kernel32.dll");
    HMODULE kb = GetModuleHandleA("kernelbase.dll");
    HMODULE ip = GetModuleHandleA("iphlpapi.dll");
    if (!ip) ip = LoadLibraryA("iphlpapi.dll");
    if (ip && !g_real_GetAdaptersInfo) g_real_GetAdaptersInfo = (PGAI)GetProcAddress(ip, "GetAdaptersInfo");
    /* anchor every origin to the real export so no hook can recurse into itself.
      Reg* live in kernelbase (in kernel32 they are delay-load stubs -> crash on call). */
    if (k) {
      if (!o_GetVolumeInformationW) o_GetVolumeInformationW = (PCGVIW)GetProcAddress(k, "GetVolumeInformationW");
      if (!o_GetComputerNameW)   o_GetComputerNameW   = (PCGCNW)GetProcAddress(k, "GetComputerNameW");
      if (!o_GetComputerNameExW)  o_GetComputerNameExW  = (PCGCNEW)GetProcAddress(k, "GetComputerNameExW");
      if (!o_GetVersionExW)     o_GetVersionExW     = (PGetVersionExW)GetProcAddress(k, "GetVersionExW");
      if (!o_GetProductInfo)    o_GetProductInfo    = (PGetProductInfo)GetProcAddress(k, "GetProductInfo");
      if (!o_GetGeoInfoW)      o_GetGeoInfoW      = (PGetGeoInfoW)GetProcAddress(k, "GetGeoInfoW");
    }
    if (kb) {
      if (!o_RegQueryValueExW) o_RegQueryValueExW = (PRegQueryValueExW)GetProcAddress(kb, "RegQueryValueExW");
      if (!o_RegQueryValueExA) o_RegQueryValueExA = (PRegQueryValueExA)GetProcAddress(kb, "RegQueryValueExA");
      if (!o_GetFileInformationByHandle) o_GetFileInformationByHandle = (PGetFileInformationByHandle)GetProcAddress(kb, "GetFileInformationByHandle");
      if (!o_CreateFileW) o_CreateFileW = (PCreateFileW)GetProcAddress(kb, "CreateFileW");
      if (!o_GetFileAttributesW) o_GetFileAttributesW = (PGetFileAttributesW)GetProcAddress(kb, "GetFileAttributesW");
      if (!o_GetFileAttributesExW) o_GetFileAttributesExW = (PGetFileAttributesExW)GetProcAddress(kb, "GetFileAttributesExW");
      if (!o_FindFirstFileW) o_FindFirstFileW = (PFindFirstFileW)GetProcAddress(kb, "FindFirstFileW");
      if (!o_DeleteFileW) o_DeleteFileW = (PDeleteFileW)GetProcAddress(kb, "DeleteFileW");
      if (!o_CreateDirectoryW) o_CreateDirectoryW = (PCreateDirectoryW)GetProcAddress(kb, "CreateDirectoryW");
      if (!o_GetUserNameW) o_GetUserNameW = (PGetUserNameW)GetProcAddress(kb, "GetUserNameW");
      if (!o_GetSystemInfo) o_GetSystemInfo = (PGetSystemInfo)GetProcAddress(kb, "GetSystemInfo");
      if (!o_DeviceIoControl) o_DeviceIoControl = (PDeviceIoControl)GetProcAddress(kb, "DeviceIoControl");
      if (!o_GetHostNameW)   o_GetHostNameW   = (PGetHostNameW)GetProcAddress(kb, "GetHostNameW");
      if (!o_GlobalMemoryStatusEx) o_GlobalMemoryStatusEx = (PGlobalMemoryStatusEx)GetProcAddress(kb, "GlobalMemoryStatusEx");
    }
    if (!o_gethostname) { HMODULE w = GetModuleHandleA("ws2_32.dll"); if (w) o_gethostname = (Pgethostname)GetProcAddress(w, "gethostname"); }
    if (ip && !o_GetAdaptersAddresses) o_GetAdaptersAddresses = (PGAA)GetProcAddress(ip, "GetAdaptersAddresses");
    { HMODULE su = GetModuleHandleA("setupapi.dll"); if (!su) su = LoadLibraryA("setupapi.dll");
     if (su && !o_SetupDiGetDeviceRegistryPropertyW) o_SetupDiGetDeviceRegistryPropertyW = (PSetupDiGetDeviceRegistryPropertyW)GetProcAddress(su, "SetupDiGetDeviceRegistryPropertyW"); }
    {
      HMODULE nt = GetModuleHandleA("ntdll.dll");
      HMODULE u = GetModuleHandleA("user32.dll");
      HMODULE g = GetModuleHandleA("gdi32.dll");
      if (nt && !o_NtQSI) o_NtQSI = (PNtQSI)GetProcAddress(nt, "NtQuerySystemInformation");
      if (u && !o_EnumDisplayDevicesW) o_EnumDisplayDevicesW = (PEnumDisplayDevicesW)GetProcAddress(u, "EnumDisplayDevicesW");
      (void)g;
    }
  }
  if (g_net) {
    HMODULE w = GetModuleHandleA("ws2_32.dll");
    HMODULE ms = GetModuleHandleA("mswsock.dll");
    void *c, *wa, *ce = NULL;
    if (!ms) ms = LoadLibraryA("mswsock.dll");
    if (w && !g_noinline && (c = (void *)GetProcAddress(w, "connect")) != NULL) { o_connect = (Pconnect)InlineHook(c, (void *)h_connect); logline("spoof: hook connect at %p byte0=%02X now=%02X", c, ((BYTE*)c)[0], ((BYTE*)c)[0]); }
    if (w && !g_noinline && (wa = (void *)GetProcAddress(w, "WSAConnect")) != NULL) o_WSAConnect = (PWSAConnect)InlineHook(wa, (void *)h_WSAConnect);
    if (ms) ce = (void *)GetProcAddress(ms, "ConnectEx");
    if (!ce) {  /* ConnectEx is often only reachable via WSAIoctl extension pointer */
      SOCKET t = socket(AF_INET, SOCK_STREAM, 0);
      if (t != INVALID_SOCKET) {
        GUID g = WSAID_CONNECTEX; DWORD nb = 0;
        WSAIoctl(t, SIO_GET_EXTENSION_FUNCTION_POINTER, &g, sizeof(g), &ce, sizeof(ce), &nb, NULL, NULL);
        closesocket(t);
      }
    }
    if (ce && !g_nocex) o_ConnectEx = (PCONNECTEX)InlineHook(ce, (void *)h_ConnectEx);
    logline("spoof: inline connect=%p wsaconnect=%p connectex=%p", (void *)o_connect, (void *)o_WSAConnect, (void *)o_ConnectEx);
#ifdef NETONLY
    patch_dns_all();
    logline("spoof: dns iat patched");
#endif
  }
#ifdef NETONLY
  logline("spoof: net-only hooks installed");
  state_ready(1);
  return 0;
#endif
  /* inline-hook the SMBIOS source so WMI providers (cimwin32) are caught regardless of IAT */
  if (g_smbios) {
    HMODULE kb2 = GetModuleHandleA("kernelbase.dll");
    HMODULE nt2 = GetModuleHandleA("ntdll.dll");
    void *gf, *nq;
    if (kb2 && (gf = (void *)GetProcAddress(kb2, "GetSystemFirmwareTable")) != NULL)
      o_GetSystemFirmwareTable = (PGetSystemFirmwareTable)InlineHook(gf, (void *)h_GetSystemFirmwareTable);
    if (nt2 && (nq = (void *)GetProcAddress(nt2, "NtQuerySystemInformation")) != NULL)
      o_NtQSI = (PNtQSI)InlineHook(nq, (void *)h_NtQSI);
    logline("spoof: inline firmware=%p ntqsi=%p", (void *)o_GetSystemFirmwareTable, (void *)o_NtQSI);
  }
  /* IAT-hook CreateFileW (inline can be fragile here) so the marker file is redirected */
  logline("spoof: CreateFileW block meta=%S", g_metaPath);
  if (!o_CreateFileW) {
    HMODULE k3 = GetModuleHandleA("kernel32.dll");
    if (k3) o_CreateFileW = (PCreateFileW)GetProcAddress(k3, "CreateFileW");
  }
  logline("spoof: CreateFileW orig=%p", (void *)o_CreateFileW);

  /* 1) hook the main module first (this is where the launcher's own HWID code sits) */
  mainmod = GetModuleHandleA(NULL);
  logline("spoof: mainmodule=0x%08lX", (DWORD)mainmod);
  {
    int first = patch_module(mainmod);
    verify(-1, first);
    /* the main module + inline net hooks are live: the loader must not wait for the slow 40-pass
       module sweep before treating the process as covered. */
    state_ready(first);
  }

  /* 2) then all modules; on the first pass log each module name so a crash is visible */
  for (i = 0; i < 40; i++) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, GetCurrentProcessId());
    int c = 0;
    if (snap != INVALID_HANDLE_VALUE) {
      MODULEENTRY32 me; me.dwSize = sizeof(me);
      if (Module32First(snap, &me)) {
        do {
          if (i == 0) logline("spoof: mod %s", me.szModule);
          /* after the first few passes, only patch modules we have not seen */
          if (i <= 2 || !mod_seen(me.hModule)) {
            c += patch_module(me.hModule);
            mark_mod(me.hModule);
          }
        } while (Module32Next(snap, &me));
      }
      CloseHandle(snap);
    }
    if (i <= 2) logline("spoof: modloop i=%d modules_patched=%d", i, c);
    if (i == 0 || i == 2) verify(i, c);
    if (i <= 3) Sleep(400); else Sleep(900);  /* slow down once settled */
  }
  return 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
  if (reason == DLL_PROCESS_ATTACH) {
    g_hself = inst;
    g_t0 = GetTickCount();
    g_reservedPath[0] = 0;
    g_reservedCfg[0] = 0;
    if (reserved) {
      /* manual-map contract: "<dll path>\0<cfg path>\0"; LoadLibrary passes NULL. */
      const char *r = (const char *)reserved;
      strncpy(g_reservedPath, r, MAX_PATH - 1);
      g_reservedPath[MAX_PATH - 1] = 0;
      if (g_reservedPath[0]) {
        const char *r2 = r + strlen(g_reservedPath) + 1;
        if (*r2) { strncpy(g_reservedCfg, r2, MAX_PATH - 1); g_reservedCfg[MAX_PATH - 1] = 0; }
      }
    }
    DisableThreadLibraryCalls(inst);
#ifdef NETONLY
    InitializeCriticalSection(&g_ai_lock);
#endif
    if (!g_logPath[0]) {
      char dir[MAX_PATH];
      dir_of(g_reservedPath, dir, MAX_PATH);
      if (dir[0])
        wsprintfA(g_logPath, "%srfspoof_%lu.log", dir, (unsigned long)GetCurrentProcessId());
      else
        wsprintfA(g_logPath, "C:\\SHARE\\hwid\\logs\\rfspoof_%lu.log", (unsigned long)GetCurrentProcessId());
    }
    state_open();
    if (g_alreadyPresent) {
      /* a second copy in the same process must not hook twice (the first copy owns the status). */
      logline("spoof: already mapped in pid=%lu, second copy idle",
              (unsigned long)GetCurrentProcessId());
    } else {
      HANDLE t = CreateThread(NULL, 0, worker, NULL, 0, NULL);
      if (t) CloseHandle(t);
      t = CreateThread(NULL, 0, heartbeat, NULL, 0, NULL);
      if (t) CloseHandle(t);
    }
  }
  return TRUE;
}
