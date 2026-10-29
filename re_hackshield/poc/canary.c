/* canary.c - tiny SEC_IMAGE canary for the RFOCliMod vtable test.
 * The mapped module is not in the PEB; canary() is a naked thunk that increments a counter
 * and jumps to the original vtable function. Build with 32-bit gcc:
 *   gcc -shared -O2 -s -o canary.dll canary.c
 */
#include <windows.h>

__declspec(dllexport) volatile DWORD g_count = 0;
__declspec(dllexport) void *g_orig = (void *)0xDEADBEEF;

__declspec(dllexport) __declspec(naked) void canary(void) {
    __asm__ __volatile__(
        "incl _g_count\n\t"
        "jmp *_g_orig\n\t"
    );
}

__declspec(dllexport) DWORD canary_count(void) { return g_count; }

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID r) {
    (void)h; (void)reason; (void)r;
    return TRUE;
}
