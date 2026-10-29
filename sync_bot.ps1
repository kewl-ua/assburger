# sync_bot.ps1 - refresh the curated bot/ snapshot from C:\SHARE\rfbot2.
# Runtime state (.target/.mapped/logs) and secrets are not copied.
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$src = "C:\SHARE\rfbot2"
$dst = Join-Path $repo "bot"
foreach ($d in @("", "src", "tools", "build", "profiles\bot1", "profiles\bot2")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $dst $d) | Out-Null
}
foreach ($f in @("rfbot.py", "run_bot.py", "run.cmd", "run_bot1.cmd", "run_bot2.cmd",
                 "build.ps1", "AGENTS.md", "PROMPT_CLAUDE.md", "rf_bot_config.json")) {
    Copy-Item (Join-Path $src $f) (Join-Path $dst $f) -Force
}
foreach ($f in @("botcore.c", "win32_min.h", "build.sh")) {
    Copy-Item (Join-Path $src "src\$f") (Join-Path $dst "src\$f") -Force
}
Copy-Item (Join-Path $src "tools\manualmap.py") (Join-Path $dst "tools\manualmap.py") -Force
try { Copy-Item (Join-Path $src "build\Bagnon.dll") (Join-Path $dst "build\Bagnon.dll") -Force } catch { Write-Host "Bagnon.dll busy; kept repo copy" }
foreach ($n in "bot1", "bot2") {
    Copy-Item (Join-Path $src "profiles\$n\BotCore.ini") (Join-Path $dst "profiles\$n\BotCore.ini") -Force
    Copy-Item (Join-Path $src "profiles\$n\rf_bot_config.json") (Join-Path $dst "profiles\$n\rf_bot_config.json") -Force
    try { Copy-Item (Join-Path $src "profiles\$n\Bagnon.new.dll") (Join-Path $dst "profiles\$n\Bagnon.dll") -Force }
    catch { try { Copy-Item (Join-Path $src "profiles\$n\Bagnon.dll") (Join-Path $dst "profiles\$n\Bagnon.dll") -Force } catch {} }
}
Write-Host "bot/ synced from $src" -ForegroundColor Green
