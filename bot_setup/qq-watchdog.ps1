# Kaju bot QQ watchdog (Task Scheduler "KajuQQWatchdog", every 3 minutes, started hidden by qq-watchdog.vbs).
# If AstrBot is running but the bot QQ is not fully online on two checks in a row, run "bot-panel.ps1 -Action start",
# which only starts the missing parts (bot QQ / SnowLuma) and leaves a running AstrBot alone.
# AstrBot not running = the bot was stopped on purpose (control panel stop / nightly shutdown): do nothing.
# After a failed restart (e.g. QQ needs a QR login) wait 30 minutes before trying again.
# ASCII only: Windows PowerShell 5.1 reads BOM-less scripts in the ANSI code page.
# Log: D:\JiashuBot\QQ-Bot\toggle.log (same file as the control panel, lines start with "watchdog:").

param(
    # overridable for tests (a fake panel that prints a chosen status)
    [string]$Panel     = 'D:\JiashuBot\bot_setup\bot-panel.ps1',
    [string]$StateFile = 'D:\JiashuBot\QQ-Bot\.watchdog.json',
    [string]$LogFile   = 'D:\JiashuBot\QQ-Bot\toggle.log'
)
$NeedStrikes = 2    # checks in a row that must see "offline" before restarting (PowerShell names ignore case: keep it unlike $strikes)
$BackoffMin = 30    # minutes to wait after a failed restart

function Write-Log([string]$msg) {
    try { "$(Get-Date -Format 'MM-dd HH:mm:ss')  watchdog: $msg" | Out-File -FilePath $LogFile -Append -Encoding utf8 } catch { }
}

function Read-State {
    try { return (Get-Content $StateFile -Raw -Encoding utf8 -ErrorAction Stop | ConvertFrom-Json) } catch { return $null }
}

function Save-State([int]$strikes, [string]$until) {
    try { (@{ strikes = $strikes; backoff_until = $until } | ConvertTo-Json) | Set-Content -Path $StateFile -Encoding utf8 } catch { }
}

function Get-Status {
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Panel -Action status 2>$null | Out-String
    $kv = @{}
    foreach ($m in [regex]::Matches($out, '(\w+)=(\S+)')) { $kv[$m.Groups[1].Value] = $m.Groups[2].Value }
    return $kv
}

$st = Read-State
$strikes = 0
$until = ''
if ($st) {
    try { $strikes = [int]$st.strikes } catch { }
    $until = [string]$st.backoff_until
}

$s = Get-Status
if ($s['astrbot'] -ne 'True') { Save-State 0 $until; exit 0 }      # stopped on purpose
if ($s['running'] -eq 'True') {
    if ($strikes -gt 0) { Write-Log 'bot QQ is online again' }
    Save-State 0 ''
    exit 0
}

$strikes++
if ($strikes -lt $NeedStrikes) {
    Write-Log ("bot not fully online (bot_qq=$($s['bot_qq']) online=$($s['online']) qq_linked=$($s['qq_linked'])), check again next run")
    Save-State $strikes $until
    exit 0
}
if ($until) {
    try {
        if ((Get-Date) -lt [datetime]::Parse($until)) { Save-State $strikes $until; exit 0 }
    } catch { }
}

Write-Log ("bot still not online (bot_qq=$($s['bot_qq']) online=$($s['online']) qq_linked=$($s['qq_linked'])), restarting the missing parts")
$res = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Panel -Action start -Quiet 2>$null | Out-String
$code = ''
$m = [regex]::Match($res, 'code=(\S+)')
if ($m.Success) { $code = $m.Groups[1].Value }
if ($code -eq 'online' -or $code -eq 'already') {
    Write-Log "restart ok ($code)"
    Save-State 0 ''
} else {
    $next = (Get-Date).AddMinutes($BackoffMin).ToString('s')
    Write-Log "restart failed (code=$code), next try after $next"
    Save-State 0 $next
}
