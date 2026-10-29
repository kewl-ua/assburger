#include <winsock2.h>
#include <windows.h>
#include <iphlpapi.h>
#include <stdio.h>

static void show_a(const char *label, const char *got, const char *want) {
    printf("%-28s = %-40s (cfg: %s)%s\n", label, got && got[0] ? got : "<empty>",
           want && want[0] ? want : "<none>",
           (want && want[0] && got && !lstrcmpA(got, want)) ? "  OK" : "");
}

int main(int argc, char **argv) {
    const char *cfg = argc > 1 ? argv[1] : "C:\\SHARE\\hwid\\spoof_1.cfg";
    const char *dll = argc > 2 ? argv[2] : "C:\\SHARE\\hwid\\rfspoof.dll";
    HMODULE h;
    WCHAR w[256];
    DWORD n;
    char a[256];
    DWORD serial = 0;

    SetEnvironmentVariableA("SPOOF_CFG", cfg);
    h = LoadLibraryA(dll);
    printf("LoadLibrary %s -> %p err=%lu\n", dll, (void *)h, GetLastError());
    if (!h) return 1;
    Sleep(600);

    n = 256; w[0] = 0;
    if (GetComputerNameW(w, &n)) { WideCharToMultiByte(CP_ACP, 0, w, -1, a, sizeof(a), 0, 0); show_a("GetComputerNameW", a, ""); }
    n = 256; w[0] = 0;
    if (GetComputerNameExW(ComputerNameNetBIOS, w, &n)) { WideCharToMultiByte(CP_ACP, 0, w, -1, a, sizeof(a), 0, 0); show_a("GetComputerNameExW(NetBIOS)", a, ""); }
    n = 256; w[0] = 0;
    if (GetComputerNameExW(ComputerNameDnsHostname, w, &n)) { WideCharToMultiByte(CP_ACP, 0, w, -1, a, sizeof(a), 0, 0); show_a("GetComputerNameExW(DnsHost)", a, ""); }

    if (GetVolumeInformationW(L"C:\\", NULL, 0, &serial, NULL, NULL, NULL, 0))
        printf("%-28s = %08lX\n", "GetVolumeInformationW serial", (unsigned long)serial);

    {
        ULONG sz = 0;
        GetAdaptersInfo(NULL, &sz);
        if (sz) {
            PIP_ADAPTER_INFO p = (PIP_ADAPTER_INFO)HeapAlloc(GetProcessHeap(), 0, sz);
            if (p && GetAdaptersInfo(p, &sz) == 0) {
                wsprintfA(a, "%02X:%02X:%02X:%02X:%02X:%02X", p->Address[0], p->Address[1], p->Address[2], p->Address[3], p->Address[4], p->Address[5]);
                show_a("GetAdaptersInfo MAC", a, "");
            }
            if (p) HeapFree(GetProcessHeap(), 0, p);
        }
    }

    {
        ULONG sz = 0;
        GetAdaptersAddresses(AF_INET, 0, NULL, NULL, &sz);
        if (sz) {
            PIP_ADAPTER_ADDRESSES p = (PIP_ADAPTER_ADDRESSES)HeapAlloc(GetProcessHeap(), 0, sz);
            if (p && GetAdaptersAddresses(AF_INET, 0, NULL, p, &sz) == 0) {
                if (p->PhysicalAddressLength >= 6) {
                    wsprintfA(a, "%02X:%02X:%02X:%02X:%02X:%02X", p->PhysicalAddress[0], p->PhysicalAddress[1], p->PhysicalAddress[2], p->PhysicalAddress[3], p->PhysicalAddress[4], p->PhysicalAddress[5]);
                    show_a("GetAdaptersAddresses MAC", a, "");
                }
            }
            if (p) HeapFree(GetProcessHeap(), 0, p);
        }
    }

    {
        HKEY k;
        if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Microsoft\\Cryptography", 0, KEY_READ, &k) == ERROR_SUCCESS) {
            DWORD cb = sizeof(w), t = 0;
            if (RegQueryValueExW(k, L"MachineGuid", NULL, &t, (LPBYTE)w, &cb) == ERROR_SUCCESS) {
                WideCharToMultiByte(CP_ACP, 0, w, -1, a, sizeof(a), 0, 0);
                show_a("RegQueryValueExW MachineGuid", a, "");
            } else printf("RegQueryValueExW MachineGuid FAILED %lu\n", GetLastError());
            RegCloseKey(k);
        }
        if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"HARDWARE\\DESCRIPTION\\System\\BIOS", 0, KEY_READ, &k) == ERROR_SUCCESS) {
            DWORD cb = sizeof(w), t = 0;
            if (RegQueryValueExW(k, L"BaseBoardProduct", NULL, &t, (LPBYTE)w, &cb) == ERROR_SUCCESS) {
                WideCharToMultiByte(CP_ACP, 0, w, -1, a, sizeof(a), 0, 0);
                show_a("BaseBoardProduct", a, "");
            }
            RegCloseKey(k);
        }
    }

    {
        MEMORYSTATUSEX m; m.dwLength = sizeof(m);
        if (GlobalMemoryStatusEx(&m))
            printf("%-28s = %llu MB\n", "GlobalMemoryStatusEx total", (unsigned long long)(m.ullTotalPhys / (1024 * 1024)));
    }

    {
        HANDLE hd = CreateFileW(L"\\\\.\\PhysicalDrive0", 0, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                NULL, OPEN_EXISTING, 0, NULL);
        if (hd != INVALID_HANDLE_VALUE) {
            BYTE q[12] = {0}, out[1024];
            DWORD ret = 0;
            if (DeviceIoControl(hd, 0x2D1400, q, sizeof(q), out, sizeof(out), &ret, NULL) && ret >= 28) {
                DWORD off = *(DWORD *)(out + 24);
                if (off && off < ret) show_a("Storage descriptor serial", (char *)out + off, "");
            }
            CloseHandle(hd);
        }
    }

    {
        DISPLAY_DEVICEW dd;
        dd.cb = sizeof(dd);
        if (EnumDisplayDevicesW(NULL, 0, &dd, 0)) {
            WideCharToMultiByte(CP_ACP, 0, dd.DeviceID, -1, a, sizeof(a), 0, 0);
            show_a("EnumDisplayDevicesW DeviceID", a, "");
        }
    }

    {
        HKEY k;
        if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0",
                          0, KEY_READ, &k) == ERROR_SUCCESS) {
            DWORD cb = sizeof(w), t = 0;
            if (RegQueryValueExW(k, L"ProcessorNameString", NULL, &t, (LPBYTE)w, &cb) == ERROR_SUCCESS) {
                WideCharToMultiByte(CP_ACP, 0, w, -1, a, sizeof(a), 0, 0);
                show_a("ProcessorNameString", a, "");
            }
            RegCloseKey(k);
        }
    }

    {
        HKEY k;
        if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters",
                          0, KEY_READ, &k) == ERROR_SUCCESS) {
            DWORD cb = sizeof(w), t = 0;
            if (RegQueryValueExW(k, L"Hostname", NULL, &t, (LPBYTE)w, &cb) == ERROR_SUCCESS) {
                WideCharToMultiByte(CP_ACP, 0, w, -1, a, sizeof(a), 0, 0);
                show_a("Tcpip Hostname", a, "");
            }
            RegCloseKey(k);
        }
    }

    {
        DWORD sz = GetSystemFirmwareTable(0x52534D42, 0, NULL, 0);
        if (sz > 8) {
            BYTE *tbl = (BYTE *)HeapAlloc(GetProcessHeap(), 0, sz);
            if (tbl && GetSystemFirmwareTable(0x52534D42, 0, tbl, sz) == sz) {
                DWORD len = *(DWORD *)(tbl + 4);
                BYTE *p = tbl + 8, *end = tbl + 8 + len;
                while (p + 4 <= end) {
                    BYTE t = p[0], sl = p[1];
                    BYTE *s = p + sl;
                    const char *v[8] = {0};
                    int i;
                    if (sl < 4) break;
                    for (i = 0; i < 8; i++) {
                        v[i] = (const char *)s;
                        if (!*s) break;
                        while (*s) s++;
                        s++;
                    }
                    if (t == 0) printf("%-28s = %s / %s\n", "SMBIOS Type0 BIOS", (p[4] && p[4] < 8) ? v[p[4]-1] : "?", (p[5] && p[5] < 8) ? v[p[5]-1] : "?");
                    if (t == 1) {
                        printf("%-28s = %s / %s\n", "SMBIOS Type1 System", (p[4] && p[4] < 8) ? v[p[4]-1] : "?", (p[5] && p[5] < 8) ? v[p[5]-1] : "?");
                        printf("%-28s = %02X%02X%02X%02X-%02X%02X-%02X%02X-%02X%02X-%02X%02X%02X%02X%02X%02X\n", "SMBIOS Type1 UUID",
                          p[11],p[10],p[9],p[8], p[13],p[12], p[15],p[14], p[16],p[17], p[18],p[19],p[20],p[21],p[22],p[23]);
                    }
                    if (t == 2) printf("%-28s = %s / %s\n", "SMBIOS Type2 Board", (p[4] && p[4] < 8) ? v[p[4]-1] : "?", (p[5] && p[5] < 8) ? v[p[5]-1] : "?");
                    if (t == 127) break;
                    p += sl;
                    while (p + 1 < end && !(p[0] == 0 && p[1] == 0)) p++;
                    p += 2;
                }
            }
            if (tbl) HeapFree(GetProcessHeap(), 0, tbl);
        } else printf("GetSystemFirmwareTable returned %lu\n", sz);
    }

    FreeLibrary(h);
    return 0;
}


