#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    DWORD pid;
    char *dll;
    HANDLE h, th;
    void *mem;
    SIZE_T n;
    if (argc < 3) { printf("usage: inject.exe <pid> <dll>\n"); return 2; }
    pid = (DWORD)strtoul(argv[1], NULL, 0);
    dll = argv[2];
    h = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ, FALSE, pid);
    if (!h) { printf("OpenProcess failed err=%lu\n", GetLastError()); return 3; }
    n = strlen(dll) + 1;
    mem = VirtualAllocEx(h, NULL, n, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!mem) { printf("VirtualAllocEx failed err=%lu\n", GetLastError()); return 4; }
    if (!WriteProcessMemory(h, mem, dll, n, NULL)) { printf("WriteProcessMemory failed err=%lu\n", GetLastError()); return 5; }
    th = CreateRemoteThread(h, NULL, 0, (LPTHREAD_START_ROUTINE)GetProcAddress(GetModuleHandleA("kernel32.dll"), "LoadLibraryA"), mem, 0, NULL);
    if (!th) { printf("CreateRemoteThread failed err=%lu\n", GetLastError()); return 6; }
    WaitForSingleObject(th, 15000);
    printf("ok pid=%lu dll=%s\n", pid, dll);
    CloseHandle(th); CloseHandle(h);
    return 0;
}
