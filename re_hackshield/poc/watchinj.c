#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdarg.h>

static FILE *g_log;
static void logf(const char *fmt, ...) {
    va_list ap;
    SYSTEMTIME st;
    if (!g_log) return;
    GetLocalTime(&st);
    fprintf(g_log, "%02d:%02d:%02d ", st.wHour, st.wMinute, st.wSecond);
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fprintf(g_log, "\n");
    fflush(g_log);
}

static int seen(DWORD *arr, int n, DWORD pid) {
    int i;
    for (i = 0; i < n; i++) if (arr[i] == pid) return 1;
    return 0;
}

int main(int argc, char **argv) {
    const char *dll = argc > 1 ? argv[1] : "C:\\SHARE\\hwid\\re_hackshield\\poc\\hsmon5.dll";
    const char *logpath = "C:\\SHARE\\hwid\\re_hackshield\\logs\\watch_inject.txt";
    const char *stop = "C:\\SHARE\\hwid\\re_hackshield\\logs\\watch_inject.stop";
    DWORD seenpids[64]; int nseen = 0;
    DWORD t0 = GetTickCount();
    g_log = fopen(logpath, "a");
    if (!g_log) return 1;
    logf("watcher start pid=%lu dll=%s", GetCurrentProcessId(), dll);
    while (GetTickCount() - t0 < 900000) {
        HANDLE snap;
        PROCESSENTRY32 pe;
        if (GetFileAttributesA(stop) != INVALID_FILE_ATTRIBUTES) break;
        snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        pe.dwSize = sizeof(pe);
        if (snap != INVALID_HANDLE_VALUE && Process32First(snap, &pe)) {
            do {
                if (_stricmp(pe.szExeFile, "RF_Online_4gb.bin") == 0 && !seen(seenpids, nseen, pe.th32ProcessID)) {
                    DWORD pid = pe.th32ProcessID;
                    HANDLE h;
                    void *mem;
                    SIZE_T n = strlen(dll) + 1;
                    HANDLE th;
                    if (nseen < 64) seenpids[nseen++] = pid;
                    logf("game pid=%lu", pid);
                    h = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ, FALSE, pid);
                    if (!h) { logf("OpenProcess err=%lu", GetLastError()); continue; }
                    mem = VirtualAllocEx(h, NULL, n, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
                    if (!mem) { logf("VirtualAllocEx err=%lu", GetLastError()); CloseHandle(h); continue; }
                    if (!WriteProcessMemory(h, mem, dll, n, NULL)) { logf("WriteProcessMemory err=%lu", GetLastError()); CloseHandle(h); continue; }
                    th = CreateRemoteThread(h, NULL, 0, (LPTHREAD_START_ROUTINE)GetProcAddress(GetModuleHandleA("kernel32.dll"), "LoadLibraryA"), mem, 0, NULL);
                    if (!th) { logf("CreateRemoteThread err=%lu", GetLastError()); CloseHandle(h); continue; }
                    WaitForSingleObject(th, 15000);
                    logf("inject ok pid=%lu", pid);
                    CloseHandle(th); CloseHandle(h);
                }
            } while (Process32Next(snap, &pe));
        }
        if (snap != INVALID_HANDLE_VALUE) CloseHandle(snap);
        Sleep(30);
    }
    logf("watcher exit");
    fclose(g_log);
    return 0;
}
