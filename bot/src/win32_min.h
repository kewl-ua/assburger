/*
 * Minimal Win32 / Direct3D9 declarations for a CRT-free 32-bit DLL.
 * Only what HPBars actually uses is declared here.
 */
#ifndef WIN32_MIN_H
#define WIN32_MIN_H

typedef unsigned char  BYTE;
typedef unsigned short WORD;
typedef unsigned long  DWORD;
typedef int            BOOL;
typedef long           LONG;
typedef long           HRESULT;
typedef unsigned int   UINT;
typedef unsigned long  ULONG_PTR;
typedef unsigned long  SIZE_T;
typedef void          *HANDLE;
typedef void          *HMODULE;
typedef void          *HINSTANCE;
typedef void          *HWND;
typedef void          *LPVOID;
typedef const void    *LPCVOID;
typedef char          *LPSTR;
typedef const char    *LPCSTR;
typedef DWORD (__stdcall *LPTHREAD_START_ROUTINE)(LPVOID);
typedef int (__stdcall *FARPROC)(void);

#define WINAPI __stdcall
#define TRUE  1
#define FALSE 0
#define NULL  ((void *)0)
#define MAX_PATH 260

#define DLL_PROCESS_ATTACH 1
#define DLL_PROCESS_DETACH 0

#define PAGE_READWRITE         0x04
#define PAGE_EXECUTE_READWRITE 0x40

#define GENERIC_WRITE          0x40000000
#define FILE_SHARE_READ        0x00000001
#define FILE_SHARE_WRITE       0x00000002
#define CREATE_ALWAYS          2
#define OPEN_ALWAYS            4
#define FILE_ATTRIBUTE_NORMAL  0x80
#define FILE_END               2
#define INVALID_HANDLE_VALUE   ((HANDLE)(long)-1)
#define INVALID_FILE_ATTRIBUTES ((DWORD)-1)

#define MEM_COMMIT  0x1000
#define PAGE_NOACCESS 0x01
#define PAGE_GUARD    0x100

typedef struct _MEMORY_BASIC_INFORMATION {
    void  *BaseAddress;
    void  *AllocationBase;
    DWORD  AllocationProtect;
    SIZE_T RegionSize;
    DWORD  State;
    DWORD  Protect;
    DWORD  Type;
} MEMORY_BASIC_INFORMATION;

typedef struct _SYSTEMTIME {
    WORD wYear, wMonth, wDayOfWeek, wDay, wHour, wMinute, wSecond, wMilliseconds;
} SYSTEMTIME;

/* SEH (__try/__except needs _except_handler3, imported from msvcrt.dll, see build.sh) */
typedef struct _EXCEPTION_RECORD {
    DWORD ExceptionCode;
    DWORD ExceptionFlags;
    struct _EXCEPTION_RECORD *ExceptionRecord;
    void *ExceptionAddress;
    DWORD NumberParameters;
    ULONG_PTR ExceptionInformation[15];
} EXCEPTION_RECORD;

typedef struct _EXCEPTION_POINTERS {
    EXCEPTION_RECORD *ExceptionRecord;
    void *ContextRecord;
} EXCEPTION_POINTERS;

#define EXCEPTION_EXECUTE_HANDLER 1
#define EXCEPTION_CONTINUE_SEARCH 0
#define EXCEPTION_BREAKPOINT      0x80000003u
#define EXCEPTION_SINGLE_STEP     0x80000004u

/* kernel32 */
__declspec(dllimport) HMODULE WINAPI LoadLibraryA(LPCSTR);
__declspec(dllimport) HMODULE WINAPI GetModuleHandleA(LPCSTR);
__declspec(dllimport) FARPROC WINAPI GetProcAddress(HMODULE, LPCSTR);
__declspec(dllimport) DWORD   WINAPI GetModuleFileNameA(HMODULE, LPSTR, DWORD);
__declspec(dllimport) UINT    WINAPI GetSystemDirectoryA(LPSTR, UINT);
__declspec(dllimport) BOOL    WINAPI DisableThreadLibraryCalls(HMODULE);
__declspec(dllimport) HANDLE  WINAPI CreateThread(void *, SIZE_T, LPTHREAD_START_ROUTINE, LPVOID, DWORD, DWORD *);
__declspec(dllimport) BOOL    WINAPI CloseHandle(HANDLE);
__declspec(dllimport) void    WINAPI Sleep(DWORD);
__declspec(dllimport) DWORD   WINAPI GetTickCount(void);
__declspec(dllimport) BOOL    WINAPI VirtualProtect(LPVOID, SIZE_T, DWORD, DWORD *);
__declspec(dllimport) SIZE_T  WINAPI VirtualQuery(LPCVOID, MEMORY_BASIC_INFORMATION *, SIZE_T);
__declspec(dllimport) DWORD   WINAPI GetCurrentProcessId(void);
__declspec(dllimport) HANDLE  WINAPI CreateFileA(LPCSTR, DWORD, DWORD, void *, DWORD, DWORD, HANDLE);
__declspec(dllimport) BOOL    WINAPI WriteFile(HANDLE, LPCVOID, DWORD, DWORD *, void *);
__declspec(dllimport) DWORD   WINAPI SetFilePointer(HANDLE, LONG, LONG *, DWORD);
__declspec(dllimport) DWORD   WINAPI GetFileAttributesA(LPCSTR);
__declspec(dllimport) void    WINAPI GetLocalTime(SYSTEMTIME *);
__declspec(dllimport) UINT    WINAPI GetPrivateProfileIntA(LPCSTR, LPCSTR, int, LPCSTR);
__declspec(dllimport) DWORD   WINAPI GetPrivateProfileStringA(LPCSTR, LPCSTR, LPCSTR, LPSTR, DWORD, LPCSTR);
__declspec(dllimport) BOOL    WINAPI WritePrivateProfileStringA(LPCSTR, LPCSTR, LPCSTR, LPCSTR);
__declspec(dllimport) int     WINAPI lstrlenA(LPCSTR);
__declspec(dllimport) LPSTR   WINAPI lstrcpynA(LPSTR, LPCSTR, int);
__declspec(dllimport) LPSTR   WINAPI lstrcatA(LPSTR, LPCSTR);
__declspec(dllimport) int     WINAPI MultiByteToWideChar(UINT, DWORD, LPCSTR, int, WORD *, int);
__declspec(dllimport) int     WINAPI WideCharToMultiByte(UINT, DWORD, const WORD *, int, LPSTR, int, LPCSTR, BOOL *);
__declspec(dllimport) BOOL    WINAPI MoveFileExA(LPCSTR, LPCSTR, DWORD);
__declspec(dllimport) BOOL    WINAPI DeleteFileA(LPCSTR);
__declspec(dllimport) HANDLE  WINAPI CreateFileMappingA(HANDLE, void *, DWORD, DWORD, DWORD, LPCSTR);
__declspec(dllimport) LPVOID  WINAPI MapViewOfFile(HANDLE, DWORD, DWORD, DWORD, SIZE_T);

#define CP_UTF8                   65001
#define MB_ERR_INVALID_CHARS      0x00000008
#define MOVEFILE_REPLACE_EXISTING 0x00000001
#define FILE_MAP_WRITE            0x0002
#define FILE_MAP_READ             0x0004

/* user32 */
__declspec(dllimport) short   WINAPI GetAsyncKeyState(int);
__declspec(dllimport) HWND    WINAPI GetForegroundWindow(void);
__declspec(dllimport) DWORD   WINAPI GetWindowThreadProcessId(HWND, DWORD *);
__declspec(dllimport) BOOL    WINAPI IsWindow(HWND);
__declspec(dllimport) BOOL    WINAPI PostMessageA(HWND, UINT, DWORD, LONG);
__declspec(dllimport) UINT    WINAPI MapVirtualKeyA(UINT, UINT);
__declspec(dllimport) int     __cdecl wsprintfA(LPSTR, LPCSTR, ...);
__declspec(dllimport) int     WINAPI wvsprintfA(LPSTR, LPCSTR, __builtin_va_list);

#define VK_SHIFT   0x10
#define VK_CONTROL 0x11
#define VK_MENU    0x12

#define WM_KEYDOWN 0x0100
#define WM_KEYUP   0x0101

/* ---------------- Direct3D9 (vtable indices, constants) ---------------- */

/* IDirect3DDevice9 vtable indices */
#define D3DDEV_BeginStateBlock      60
#define D3DDEV_EndStateBlock        61
#define D3DDEV_SetTexture           65
#define D3DDEV_SetTextureStageState 67
#define D3DDEV_SetRenderState       57
#define D3DDEV_DrawPrimitiveUP      83
#define D3DDEV_SetVertexDeclaration 87
#define D3DDEV_SetFVF               89
#define D3DDEV_SetVertexShader      92
#define D3DDEV_SetStreamSource      100
#define D3DDEV_SetPixelShader       107

/* IDirect3DStateBlock9 vtable indices */
#define D3DSB_Release 2
#define D3DSB_Capture 4
#define D3DSB_Apply   5

/* D3DRENDERSTATETYPE */
#define D3DRS_ZENABLE                  7
#define D3DRS_FILLMODE                 8
#define D3DRS_SHADEMODE                9
#define D3DRS_ZWRITEENABLE             14
#define D3DRS_ALPHATESTENABLE          15
#define D3DRS_SRCBLEND                 19
#define D3DRS_DESTBLEND                20
#define D3DRS_CULLMODE                 22
#define D3DRS_ALPHABLENDENABLE         27
#define D3DRS_FOGENABLE                28
#define D3DRS_STENCILENABLE            52
#define D3DRS_CLIPPING                 136
#define D3DRS_LIGHTING                 137
#define D3DRS_COLORWRITEENABLE         168
#define D3DRS_BLENDOP                  171
#define D3DRS_SCISSORTESTENABLE        174
#define D3DRS_SRGBWRITEENABLE          194
#define D3DRS_SEPARATEALPHABLENDENABLE 206

/* D3DTEXTURESTAGESTATETYPE */
#define D3DTSS_COLOROP   1
#define D3DTSS_COLORARG1 2
#define D3DTSS_ALPHAOP   4
#define D3DTSS_ALPHAARG1 5

#define D3DTOP_DISABLE    1
#define D3DTOP_SELECTARG1 2
#define D3DTA_DIFFUSE     0

#define D3DFILL_SOLID        3
#define D3DSHADE_GOURAUD     2
#define D3DCULL_NONE         1
#define D3DBLEND_SRCALPHA    5
#define D3DBLEND_INVSRCALPHA 6
#define D3DBLENDOP_ADD       1

#define D3DPT_TRIANGLELIST 4
#define D3DFVF_XYZRHW  0x004
#define D3DFVF_DIFFUSE 0x040

#endif
