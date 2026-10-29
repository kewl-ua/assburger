# build.ps1 - compile the 32-bit spoof DLL from spoof.c with the bundled 32-bit gcc.
# Usage: powershell -ExecutionPolicy Bypass -File build.ps1
#
# The live clients may keep the previous rfspoof*.dll open (SEC_IMAGE mapping keeps the file
# section alive), so the output is written to the first writable name. The loaders pick the
# newest of rfspoof.dll / rfspoof.new.dll / rfspoof.next.dll / rfspoof.build.dll.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$gcc = Join-Path $here "tools\mingw32\bin\gcc.exe"
if (-not (Test-Path $gcc)) {
    Write-Host "32-bit gcc not found at $gcc" -ForegroundColor Red
    Write-Host "Expected a WinLibs i686 build under tools\mingw32."
    exit 1
}
$src = Join-Path $here "spoof.c"
$flags = @("-shared", "-s", "-O2", "-Wno-cpp", "-Wno-unknown-pragmas", "-Wno-cast-function-type",
           "-Wl,--dynamicbase")
$libs = @("-lkernel32", "-luser32", "-lws2_32")

function Build-One([string]$name, [string[]]$extra) {
    foreach ($outname in @($name, ($name -replace '\.dll$', '.next.dll'), ($name -replace '\.dll$', '.build.dll'))) {
        $out = Join-Path $here $outname
        Write-Host "compiling spoof.c -> $outname ..."
        & $gcc @flags @extra -o $out $src @libs
        if ($LASTEXITCODE -eq 0) {
            # zero TimeDateStamp + rename sections (build-time/toolchain giveaways), like Bagnon
            $bytes = [IO.File]::ReadAllBytes($out)
            $pe = [BitConverter]::ToInt32($bytes, 0x3C)
            for ($i = 0; $i -lt 4; $i++) { $bytes[$pe + 8 + $i] = 0 }
            $nsec = [BitConverter]::ToUInt16($bytes, $pe + 6)
            $optsz = [BitConverter]::ToUInt16($bytes, $pe + 20)
            $sec = $pe + 24 + $optsz
            for ($i = 0; $i -lt $nsec; $i++) {
                $nb = [Text.Encoding]::ASCII.GetBytes((".gex{0}" -f $i))
                for ($j = 0; $j -lt 8; $j++) {
                    $bytes[$sec + $i * 40 + $j] = if ($j -lt $nb.Length) { $nb[$j] } else { 0 }
                }
            }
            [IO.File]::WriteAllBytes($out, $bytes)
            Write-Host ("OK: {0} ({1} bytes)" -f $outname, (Get-Item $out).Length) -ForegroundColor Green
            return $out
        }
        Write-Host "  $outname is locked/failed, trying the next name" -ForegroundColor Yellow
    }
    throw "build FAILED for $name"
}

$full = Build-One "rfspoof.dll" @()
$net = Build-One "rfspoof.net.dll" @("-DNETONLY")

# Static contract: a manual map needs a .reloc section and must see the MinGW TLS directory
# (the mapper runs the TLS callbacks explicitly).
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($py) {
    foreach ($dll in @($full, $net)) {
        & $py (Join-Path $here "manualmap.py") --check $dll
        if ($LASTEXITCODE -ne 0) { throw "PE check failed: $dll" }
    }
}
Write-Host "OK: full=$full net=$net" -ForegroundColor Green
