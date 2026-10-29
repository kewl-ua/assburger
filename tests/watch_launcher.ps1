param(
    [string]$Tag = "baseline",
    [int]$DurationSec = 1800,
    [string]$OutDir = "C:\SHARE\hwid\logs"
)

$ErrorActionPreference = "SilentlyContinue"
$start = Get-Date
$jsonl = Join-Path $OutDir ("watch_{0}.jsonl" -f $Tag)
$stop = Join-Path $OutDir ("watch_{0}.stop" -f $Tag)
Remove-Item -LiteralPath $stop -Force
Remove-Item -LiteralPath $jsonl -Force

function Emit($obj) {
    $obj.ts = (Get-Date).ToString("o")
    ($obj | ConvertTo-Json -Compress) | Add-Content -LiteralPath $jsonl -Encoding UTF8
}

Emit @{ event = "watch_start"; tag = $Tag; duration = $DurationSec; pid = $PID }
$seenPid = @{}
$seenNet = @{}
$seenDns = @{}

Get-DnsClientCache | ForEach-Object { $seenDns["$($_.Entry)|$($_.Data)"] = $true }

while (((Get-Date) - $start).TotalSeconds -lt $DurationSec -and -not (Test-Path -LiteralPath $stop)) {
    $procs = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(CERBERUS-GAMES|RF_Online)' })
    foreach ($p in $procs) {
        if (-not $seenPid.ContainsKey($p.Id)) {
            $seenPid[$p.Id] = $true
            $ci = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)"
            Emit @{
                event = "proc"; pid = $p.Id; parent = $ci.ParentProcessId
                path = $p.Path; start = $(try { $p.StartTime.ToString("o") } catch { "" })
                cmd = $ci.CommandLine
            }
        }
    }

    $pids = @($procs | ForEach-Object { $_.Id })
    if ($pids.Count -gt 0) {
        Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $pids -contains $_.OwningProcess } | ForEach-Object {
            $k = "t|$($_.OwningProcess)|$($_.LocalAddress)|$($_.LocalPort)|$($_.RemoteAddress)|$($_.RemotePort)|$($_.State)"
            if (-not $seenNet.ContainsKey($k)) {
                $seenNet[$k] = $true
                Emit @{ event = "tcp"; pid = $_.OwningProcess; local = "$($_.LocalAddress):$($_.LocalPort)"; remote = "$($_.RemoteAddress):$($_.RemotePort)"; state = "$($_.State)" }
            }
        }
        Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Where-Object { $pids -contains $_.OwningProcess } | ForEach-Object {
            $k = "u|$($_.OwningProcess)|$($_.LocalAddress)|$($_.LocalPort)"
            if (-not $seenNet.ContainsKey($k)) {
                $seenNet[$k] = $true
                Emit @{ event = "udp"; pid = $_.OwningProcess; local = "$($_.LocalAddress):$($_.LocalPort)" }
            }
        }
    }

    Get-DnsClientCache -ErrorAction SilentlyContinue | ForEach-Object {
        $k = "$($_.Entry)|$($_.Data)"
        if (-not $seenDns.ContainsKey($k)) {
            $seenDns[$k] = $true
            Emit @{ event = "dns"; entry = $_.Entry; data = $_.Data; type = "$($_.Type)"; status = "$($_.Status)" }
        }
    }

    Start-Sleep -Milliseconds 250
}

Emit @{ event = "watch_stop"; tag = $Tag }
