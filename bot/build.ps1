# Build BotCore (Bagnon.dll) with clang + lld-link (LLVM). Relocatable x86 DLL for manual mapping.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$src  = Join-Path $root "src"
$bld  = Join-Path $root "build"
New-Item -ItemType Directory -Force -Path $bld | Out-Null

$llvm = "C:\Program Files\LLVM\bin"
$clang    = Join-Path $llvm "clang.exe"
$lldlink  = Join-Path $llvm "lld-link.exe"
$dlltool  = Join-Path $llvm "llvm-dlltool.exe"

$kernel32 = @"
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
"@

$user32 = @"
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
"@

$msvcrt = @"
LIBRARY msvcrt.dll
EXPORTS
_except_handler3
"@

[IO.File]::WriteAllText((Join-Path $bld "kernel32.def"), $kernel32)
[IO.File]::WriteAllText((Join-Path $bld "user32.def"), $user32)
[IO.File]::WriteAllText((Join-Path $bld "msvcrt.def"), $msvcrt)

& $dlltool -m i386 -k -d (Join-Path $bld "kernel32.def") -l (Join-Path $bld "kernel32.lib")
& $dlltool -m i386 -k -d (Join-Path $bld "user32.def")   -l (Join-Path $bld "user32.lib")
& $dlltool -m i386 -k -d (Join-Path $bld "msvcrt.def")   -l (Join-Path $bld "msvcrt.lib")

& $clang -target i686-pc-windows-msvc -O2 -msse2 -mfpmath=sse -fno-stack-protector `
    -fno-builtin -ffreestanding -Wall -Wextra -Wno-unused-parameter `
    -c (Join-Path $src "botcore.c") -o (Join-Path $bld "botcore.obj")

& $lldlink /dll /nologo /machine:x86 /entry:DllMain /nodefaultlib /subsystem:windows `
    /safeseh:no /dynamicbase "/out:$bld\Bagnon.new.dll" `
    "$bld\botcore.obj" "$bld\kernel32.lib" "$bld\user32.lib" "$bld\msvcrt.lib"

# Post-process the image header: zero TimeDateStamp (a build-time giveaway) so the mapped image carries
# no link time. Nothing at runtime needs it.
$dll = Join-Path $bld "Bagnon.new.dll"
$bytes = [IO.File]::ReadAllBytes($dll)
$pe = [BitConverter]::ToInt32($bytes, 0x3C)
# IMAGE_FILE_HEADER.TimeDateStamp is at PE + 8
for ($i = 0; $i -lt 4; $i++) { $bytes[$pe + 8 + $i] = 0 }
# Rename the sections to game-like names (the packed client uses ".gpt0"); a scanner reading the PE
# header of the mapped image then sees ".gpt"-style names, not the default clang ".text/.rdata/...".
$nsec = [BitConverter]::ToUInt16($bytes, $pe + 6)
$optsz = [BitConverter]::ToUInt16($bytes, $pe + 20)
$sec = $pe + 24 + $optsz
$names = @(".gex0", ".gex1", ".gex2", ".gex3")
for ($i = 0; $i -lt $nsec -and $i -lt $names.Count; $i++) {
    $nb = [Text.Encoding]::ASCII.GetBytes($names[$i])
    for ($j = 0; $j -lt 8; $j++) { $bytes[$sec + $i * 40 + $j] = if ($j -lt $nb.Length) { $nb[$j] } else { 0 } }
}
[IO.File]::WriteAllBytes($dll, $bytes)
Write-Output "zeroed TimeDateStamp, renamed $nsec sections"

# Try to publish as Bagnon.dll. The game launcher (CERBERUS-GAMES) keeps Bagnon.dll open while it is the
# mapped module's source, so replacing it can fail -> keep Bagnon.new.dll and report it.
$final = Join-Path $bld "Bagnon.dll"
$published = $false
try {
    Copy-Item -LiteralPath $dll -Destination $final -Force
    Remove-Item -LiteralPath $dll -Force
    $published = $true
    Write-Output "built $final"
} catch {
    Write-Output "built $dll (Bagnon.dll is locked; mapper will pick the newest)"
}



