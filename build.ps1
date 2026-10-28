# build.ps1 - compile rfspoof.dll (32-bit) from spoof.c using the bundled 32-bit gcc.
# Usage: powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$gcc = Join-Path $here "tools\mingw32\bin\gcc.exe"
if (-not (Test-Path $gcc)) {
    Write-Host "32-bit gcc not found at $gcc" -ForegroundColor Red
    Write-Host "Expected a WinLibs i686 build under tools\mingw32."
    exit 1
}
$src = Join-Path $here "spoof.c"
$out = Join-Path $here "rfspoof.dll"
Write-Host "compiling spoof.c -> rfspoof.dll ..."
& $gcc -shared -s -O2 -Wno-cpp -o $out $src -lkernel32 -luser32 -lws2_32
if ($LASTEXITCODE -ne 0) { Write-Host "build FAILED" -ForegroundColor Red; exit 1 }
$size = (Get-Item $out).Length
Write-Host ("OK: rfspoof.dll ({0} bytes)" -f $size) -ForegroundColor Green
