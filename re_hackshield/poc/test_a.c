#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

static void rd(HKEY root, const char *sub, const char *val) {
    HKEY h; char buf[512]; DWORD cb = sizeof(buf), type = 0; LONG r;
    r = RegOpenKeyExA(root, sub, 0, KEY_READ, &h);
    if (r) { printf("open %s r=%ld\n", sub, r); return; }
    cb = sizeof(buf);
    r = RegQueryValueExA(h, val, NULL, &type, (BYTE*)buf, &cb);
    printf("%-28s r=%ld type=%lu cb=%lu val='%s'\n", val, r, type, cb, (r==0 && (type==REG_SZ||type==REG_EXPAND_SZ)) ? buf : "");
    RegCloseKey(h);
}

int main(void) {
    SetEnvironmentVariableA("SPOOF_CFG", "C:\\SHARE\\hwid\\spoof_2.cfg");
    if (!LoadLibraryA("C:\\SHARE\\hwid\\rfspoof.new.dll")) { printf("load err=%lu\n", GetLastError()); return 1; }
    Sleep(1500);
    rd(HKEY_LOCAL_MACHINE, "SYSTEM\\HardwareConfig", "BIOSVendor");
    rd(HKEY_LOCAL_MACHINE, "SYSTEM\\HardwareConfig", "BIOSVersion");
    rd(HKEY_LOCAL_MACHINE, "SYSTEM\\HardwareConfig", "BaseBoardProduct");
    rd(HKEY_LOCAL_MACHINE, "SYSTEM\\HardwareConfig", "SystemProductName");
    rd(HKEY_LOCAL_MACHINE, "SYSTEM\\HardwareConfig", "ProcessorNameString");
    rd(HKEY_LOCAL_MACHINE, "SYSTEM\\HardwareConfig", "HardwareID");
    rd(HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Cryptography", "MachineGuid");
    return 0;
}
