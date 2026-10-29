#!/bin/sh
# Build BotCore (Bagnon.dll) with clang + lld-link, no Windows SDK.
# Output is a RELOCATABLE x86 DLL (needs /dynamicbase so the manual mapper can rebase it).
set -e
cd "$(dirname "$0")"
mkdir -p build && cd build

cat > kernel32.def <<'DEF'
LIBRARY kernel32.dll
EXPORTS
LoadLibraryA@4
GetModuleHandleA@4
GetProcAddress@8
GetModuleFileNameA@12
GetSystemDirectoryA@8
DisableThreadLibraryCalls@4
CreateThread@24
CloseHandle@4
Sleep@4
GetTickCount@0
VirtualProtect@16
VirtualQuery@12
GetCurrentProcessId@0
CreateFileA@28
WriteFile@20
SetFilePointer@16
GetFileAttributesA@4
GetLocalTime@4
GetPrivateProfileIntA@16
GetPrivateProfileStringA@24
WritePrivateProfileStringA@16
lstrlenA@4
lstrcpynA@12
lstrcatA@8
MultiByteToWideChar@24
WideCharToMultiByte@32
MoveFileExA@12
DeleteFileA@4
CreateFileMappingA@24
MapViewOfFile@20
DEF

cat > user32.def <<'DEF'
LIBRARY user32.dll
EXPORTS
GetAsyncKeyState@4
GetForegroundWindow@0
GetWindowThreadProcessId@8
IsWindow@4
PostMessageA@16
MapVirtualKeyA@8
wsprintfA
wvsprintfA@12
DEF

cat > msvcrt.def <<'DEF'
LIBRARY msvcrt.dll
EXPORTS
_except_handler3
DEF

LLVM_BIN="${LLVM_BIN:-/c/Program Files/LLVM/bin}"
"$LLVM_BIN/llvm-dlltool" -m i386 -k -d kernel32.def -l kernel32.lib
"$LLVM_BIN/llvm-dlltool" -m i386 -k -d user32.def -l user32.lib
"$LLVM_BIN/llvm-dlltool" -m i386 -k -d msvcrt.def -l msvcrt.lib

"$LLVM_BIN/clang" -target i686-pc-windows-msvc -O2 -msse2 -mfpmath=sse -fno-stack-protector \
      -fno-builtin -ffreestanding -Wall -Wextra -Wno-unused-parameter \
      -c ../src/botcore.c -o botcore.obj

"$LLVM_BIN/lld-link" /dll /nologo /machine:x86 /entry:DllMain /nodefaultlib /subsystem:windows \
         /safeseh:no /dynamicbase /out:Bagnon.dll botcore.obj kernel32.lib user32.lib msvcrt.lib
echo "built build/Bagnon.dll"
