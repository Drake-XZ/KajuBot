param([ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Status')
$ErrorActionPreference = 'Stop'
$runtimeExe = Join-Path $PSScriptRoot 'runtime\ollama.exe'
$statePath = Join-Path $PSScriptRoot 'runtime-state.json'
$serviceUrl = 'http://127.0.0.1:11435'

function Get-OwnedProcess {
    if (-not (Test-Path -LiteralPath $statePath)) { return $null }
    $record = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    if ($process -and $process.Path -eq $runtimeExe -and
        $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $record.startedTicks) {
        return $process
    }
    return $null
}
function Get-Listener {
    @(Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue)
}
function Write-Status {
    $process = Get-OwnedProcess
    $listener = @(Get-Listener)
    $state = 'stopped'
    $version = $null
    if ($listener.Count -gt 0) { $state = 'foreign-port' }
    if ($process) {
        $state = 'starting'
        if ($listener.Count -eq 1 -and $listener[0].OwningProcess -eq $process.Id -and
            $listener[0].LocalAddress -eq '127.0.0.1') {
            $version = (Invoke-RestMethod "$serviceUrl/api/version" -TimeoutSec 5).version
            $state = 'running'
        }
    }
    [pscustomobject]@{ state = $state; pid = $(if ($process) { $process.Id } else { $null });
        url = $serviceUrl; version = $version; model = 'qwen3-vl:4b-instruct' } | ConvertTo-Json -Compress
}

if ($Action -eq 'Status') { Write-Status; return }
$ownedProcess = Get-OwnedProcess
$listeners = @(Get-Listener)
if ($listeners | Where-Object { -not $ownedProcess -or $_.OwningProcess -ne $ownedProcess.Id }) {
    throw 'Port 11435 belongs to another process; refusing to start or stop it.'
}
if ($Action -eq 'Stop') {
    if ($ownedProcess) {
        # Only terminate descendants whose executable belongs to this portable runtime.
        $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($ownedProcess.Id)" |
            Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith((Join-Path $PSScriptRoot 'runtime\'), [StringComparison]::OrdinalIgnoreCase) })
        Stop-Process -Id $ownedProcess.Id -Force
        foreach ($child in $children) {
            $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($child.ProcessId)"
            if ($current -and $current.CreationDate -eq $child.CreationDate) {
                Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        $ownedProcess.WaitForExit(5000) | Out-Null
    }
    if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath }
    Write-Status
    return
}
if ($ownedProcess) { Write-Status; return }
if (-not (Test-Path -LiteralPath $runtimeExe)) { throw "Portable runtime missing: $runtimeExe" }
foreach ($directory in 'models', 'logs', 'tmp', 'cache\cuda') {
    New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot $directory) -Force | Out-Null
}
$settings = @{
    OLLAMA_HOST = '127.0.0.1:11435'
    OLLAMA_MODELS = Join-Path $PSScriptRoot 'models'
    OLLAMA_TMPDIR = Join-Path $PSScriptRoot 'tmp'
    TEMP = Join-Path $PSScriptRoot 'tmp'
    TMP = Join-Path $PSScriptRoot 'tmp'
    CUDA_CACHE_PATH = Join-Path $PSScriptRoot 'cache\cuda'
    OLLAMA_NO_CLOUD = '1'
    # 2026-11-04: requests never exceed ~2k tokens (one image sheet + short prompt), so 4096 is enough;
    # q8_0 KV cache halves it again. That lets vision + rewriter + bge-m3 (~6.3 GB) stay loaded together
    # instead of evicting each other (vision 8 s / rewriter 2 s reloads).
    OLLAMA_CONTEXT_LENGTH = '4096'
    OLLAMA_FLASH_ATTENTION = '1'
    OLLAMA_KV_CACHE_TYPE = 'q8_0'
    OLLAMA_KEEP_ALIVE = '10m'
    OLLAMA_NUM_PARALLEL = '1'
    OLLAMA_MAX_LOADED_MODELS = '3'
    OLLAMA_DEBUG = '0'
    OLLAMA_DEBUG_LOG_REQUESTS = '0'
}
$previous = @{}
try {
    foreach ($key in $settings.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $settings[$key], 'Process')
    }
    # A detached console prevents the server inheriting a caller's captured pipeline handles.
    $started = Start-Process -FilePath (Join-Path $PSScriptRoot 'runtime-launch.cmd') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
} finally {
    foreach ($key in $previous.Keys) { [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process') }
}
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if ($started.HasExited) { throw 'Ollama exited during startup; inspect local_vision/logs/server.stderr.log.' }
    try {
        $null = Invoke-RestMethod "$serviceUrl/api/version" -TimeoutSec 1
        $listener = @(Get-Listener)
        if ($listener.Count -ne 1 -or $listener[0].LocalAddress -ne '127.0.0.1') { throw 'Unexpected listener address.' }
        $server = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener[0].OwningProcess)"
        if ($server.ExecutablePath -ne $runtimeExe -or $server.ParentProcessId -ne $started.Id) { throw 'Unexpected listener owner.' }
        $serverProcess = Get-Process -Id $server.ProcessId
        [pscustomobject]@{ pid = $serverProcess.Id; startedTicks = $serverProcess.StartTime.ToUniversalTime().Ticks.ToString() } |
            ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding ASCII
        Write-Status
        return
    } catch { Start-Sleep -Milliseconds 500 }
}
throw 'Ollama did not become ready within 60 attempts; inspect local_vision/logs/server.stderr.log.'
