#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <stdio.h>

int main(void) {
    WSADATA w;
    WSAStartup(MAKEWORD(2, 2), &w);
    printf("pid=%lu\n", (unsigned long)GetCurrentProcessId());
    fflush(stdout);
    Sleep(60000);
    return 0;
}
