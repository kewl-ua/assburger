/* canary_remote.c - LoadLibrary a tiny SEC_IMAGE canary and install a canary vtable thunk.
 * Run as the game's user (Johnny). Usage: canary_remote.exe <pid>
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

#define SLOT 0x00A41ED4u
#define ORIG 0x004038A0u
#define RVA_CANARY 0x14A0u
#define RVA_GORIG  0x3008u
#define RVA_GCOUNT 0x602Cu

int main(int argc, char **argv) {
    DWORD pid; HANDLE h, th; void *mem, *base; SIZE_T n; DWORD code = 0, old;
    char *dll = "C:\\SHARE\\hwid\\re_hackshield\\poc\\canary.dll";
    FILE *log;
    if (argc < 2) { printf("usage: canary_remote.exe <pid>\n"); return 2; }
    pid = (DWORD)strtoul(argv[1], NULL, 0);
    h = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION |
                    PROCESS_VM_WRITE | PROCESS_VM_READ, FALSE, pid);
    if (!h) { printf("OpenProcess err=%lu\n", GetLastError()); return 3; }
    n = strlen(dll) + 1;
    mem = VirtualAllocEx(h, NULL, n, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!mem || !WriteProcessMemory(h, mem, dll, n, NULL)) { printf("path write err=%lu\n", GetLastError()); return 4; }
    th = CreateRemoteThread(h, NULL, 0,
        (LPTHREAD_START_ROUTINE)GetProcAddress(GetModuleHandleA("kernel32.dll"), "LoadLibraryA"),
        mem, 0, NULL);
    if (!th) { printf("CreateRemoteThread err=%lu\n", GetLastError()); return 5; }
    WaitForSingleObject(th, 10000);
    GetExitCodeThread(th, &code);
    CloseHandle(th);
    base = (void *)(DWORD_PTR)code;
    log = fopen("C:\\SHARE\\hwid\\re_hackshield\\logs\\canary.txt", "a");
    if (log) { fprintf(log, "canary base=%p pid=%lu\n", base, pid); fflush(log); }
    if (!base) { printf("LoadLibrary returned 0\n"); return 6; }
    {
        DWORD orig = ORIG;
        if (!WriteProcessMemory(h, (BYTE *)base + RVA_GORIG, &orig, 4, NULL))
            printf("g_orig write err=%lu\n", GetLastError());
        VirtualProtectEx(h, (void *)SLOT, 4, PAGE_READWRITE, &old);
        {
            DWORD canary = (DWORD)(DWORD_PTR)base + RVA_CANARY;
            if (!WriteProcessMemory(h, (void *)SLOT, &canary, 4, NULL))
                printf("slot write err=%lu\n", GetLastError());
            if (log) { fprintf(log, "slot=%08lX canary=%08lX\n", (unsigned long)SLOT, (unsigned long)canary); }
        }
        VirtualProtectEx(h, (void *)SLOT, 4, old, &old);
        if (log) {
            DWORD v = 0, c = 0;
            ReadProcessMemory(h, (void *)SLOT, &v, 4, NULL);
            ReadProcessMemory(h, (BYTE *)base + RVA_GCOUNT, &c, 4, NULL);
            fprintf(log, "readback slot=%08lX count=%lu\n", (unsigned long)v, (unsigned long)c);
            fclose(log);
        }
    }
    CloseHandle(h);
    printf("ok pid=%lu base=%p\n", pid, base);
    return 0;
}
