/* dbgattach.c - attach a real debugger to the game for a few seconds, pump debug events,
 * then detach. Run as the game's user. Usage: dbgattach.exe <pid> [seconds]
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    DWORD pid, end; DEBUG_EVENT de; FILE *log;
    int secs = 5;
    if (argc < 2) { printf("usage: dbgattach.exe <pid> [seconds]\n"); return 2; }
    pid = (DWORD)strtoul(argv[1], NULL, 0);
    if (argc > 2) secs = atoi(argv[2]);
    log = fopen("C:\\SHARE\\hwid\\re_hackshield\\logs\\dbgattach.txt", "a");
    if (log) { fprintf(log, "attach pid=%lu secs=%d\n", pid, secs); fflush(log); }
    if (!DebugActiveProcess(pid)) {
        DWORD e = GetLastError();
        if (log) { fprintf(log, "DebugActiveProcess err=%lu\n", e); fclose(log); }
        printf("attach err=%lu\n", e); return 3;
    }
    DebugSetProcessKillOnExit(FALSE);
    end = GetTickCount() + (DWORD)secs * 1000;
    while ((LONG)(end - GetTickCount()) > 0) {
        if (WaitForDebugEvent(&de, 200)) {
            ContinueDebugEvent(de.dwProcessId, de.dwThreadId, DBG_CONTINUE);
        }
    }
    DebugActiveProcessStop(pid);
    if (log) { fprintf(log, "detached pid=%lu\n", pid); fclose(log); }
    printf("ok pid=%lu\n", pid);
    return 0;
}
