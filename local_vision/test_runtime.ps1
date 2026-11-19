$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'runtime.ps1'
function Invoke-Control([string]$Action) {
    $ErrorActionPreference = 'Continue'
    $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $scriptPath $Action 2>&1
    [pscustomobject]@{ Code = $LASTEXITCODE; Output = ($output -join "`n") }
}
function Assert([bool]$Value, [string]$Message) {
    if (-not $Value) { throw $Message }
}
Assert (-not (Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue)) 'Stop the project runtime before this lifecycle check.'
$result = Invoke-Control 'Status'
Assert ($result.Code -eq 0) 'Status must succeed when the runtime is stopped.'
Assert (($result.Output | ConvertFrom-Json).state -eq 'stopped') 'Status must report stopped.'

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 11435)
$listener.Start()
try {
    $result = Invoke-Control 'Start'
    Assert ($result.Code -ne 0) 'Start must refuse an occupied port.'
    $result = Invoke-Control 'Stop'
    Assert ($result.Code -ne 0) 'Stop must refuse a foreign listener.'
    Assert ($listener.Server.IsBound) 'Foreign listener must survive start/stop.'
} finally { $listener.Stop() }

$beforeModels = $env:OLLAMA_MODELS
$beforeRequestLogging = $env:OLLAMA_DEBUG_LOG_REQUESTS
$env:OLLAMA_DEBUG_LOG_REQUESTS = '1'
$result = Invoke-Control 'Start'
Assert ($result.Code -eq 0) "Start failed: $($result.Output)"
try {
    $status = (Invoke-Control 'Status').Output | ConvertFrom-Json
    Assert ($status.state -eq 'running') 'Status must report a healthy owned runtime.'
    Assert ($status.url -eq 'http://127.0.0.1:11435') 'Runtime must use the isolated loopback endpoint.'
    Assert ([bool](Select-String -LiteralPath (Join-Path $PSScriptRoot 'logs\server.stderr.log') -Pattern 'OLLAMA_DEBUG_LOG_REQUESTS:false')) 'Start must disable request-body logging even when inherited as enabled.'
    Assert ($beforeModels -eq $env:OLLAMA_MODELS) 'Start must not change caller environment.'
    $again = Invoke-Control 'Start'
    Assert ($again.Code -eq 0) 'Start must be idempotent.'
    Assert ((($again.Output | ConvertFrom-Json).pid) -eq $status.pid) 'Start must reuse the owned process.'
} finally {
    $env:OLLAMA_DEBUG_LOG_REQUESTS = $beforeRequestLogging
    $result = Invoke-Control 'Stop'
    Assert ($result.Code -eq 0) "Stop failed: $($result.Output)"
}
Assert (((Invoke-Control 'Status').Output | ConvertFrom-Json).state -eq 'stopped') 'Stop must release its listener.'
Write-Output 'PASS: stopped status, foreign-port protection, start/status/idempotency/stop, caller environment, request-body logging disabled.'
