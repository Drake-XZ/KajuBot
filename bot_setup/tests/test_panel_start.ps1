# 控制台「启动」流程的离线测试：把 bot-panel.ps1 的核心逻辑拿出来，用假的端口 / 进程 / 登录结果跑各种情况。
# 不碰真的机器人。用法：powershell -NoProfile -ExecutionPolicy Bypass -File D:\JiashuBot\bot_setup\tests\test_panel_start.ps1
# 退出码 0 = 全过。

$ErrorActionPreference = 'Stop'
$panel = Join-Path $PSScriptRoot '..\bot-panel.ps1'
$text = [IO.File]::ReadAllText($panel, [Text.Encoding]::UTF8)
$m = [regex]::Match($text, "(?s)\`$Core = @'\r?\n(.*?)\r?\n'@")
if (-not $m.Success) { Write-Output 'FAIL: 找不到 $Core'; exit 1 }
. ([scriptblock]::Create($m.Groups[1].Value))

$script:Fail = 0
function Expect([string]$label, $got, $want) {
    if ([string]$got -ne [string]$want) { $script:Fail++; Write-Output "FAIL $label`n  got:  $got`n  want: $want" }
}

# ---- 假环境：$F 描述一种情况 ----
$VisionScript = 'Z:\no-such\runtime.ps1'
function Write-Log([string]$msg) { $script:Log += $msg }
function Set-Phase([string]$phase, [string]$detail = '') { $script:Phases += $phase }
function Get-BotState {
    $s = $script:F.Initial
    return [pscustomobject]@{ Astr = $s.Astr; Model = $s.Model; Ready = ($s.Astr -and $s.Model); Luma = $s.Luma; BotQq = $false
        Online = $false; Linked = $s.Running; QqOk = $s.Running; Running = $s.Running; Any = $s.Astr; BotVer = '9' }
}
# 参数别叫 $port：PowerShell 变量不分大小写，会把面板的 $Port（6185）盖掉
function Wait-Port([int]$which, [int]$seconds, [bool]$up = $true) {
    if ($which -eq 6185) { return $script:F.AstrUp }
    if ($which -eq 11435) { return $script:F.ModelUp }
    if ($which -eq 5099) { return $script:F.LumaUp }
    return $false
}
function Wait-AstrPortsFree([int]$seconds = 20) { return $true }
function Start-Component([string]$task, [string]$vbs, [string]$label) { $script:Started += $label }
function Get-LumaProcs { @() }
function Get-BotLoginUin { if ($script:F.AlreadyLoggedIn) { return $BotUin }; return $null }
function Get-BotQq { @() }
function Start-BotQq { $script:Started += 'QQ'; return @{ File = 'x'; Pos = 0 } }
function Wait-BotLogin($logPos, [int]$seconds) { return $script:F.Login }
function Wait-AdapterLinked([int]$seconds) { $script:LinkTries++; return ($script:LinkTries -ge $script:F.LinkAfter) }
function Stop-ByPort([int]$port, [string]$label) { $script:Stopped += $label }
function Stop-BotQq { $script:Stopped += 'QQ' }
function Show-BotQqWindow { $script:Shown = $true }
function Get-PortOwners([int]$port) { @() }
# Start-Process（AstrBot 的备用启动器）不能真的跑
function Start-Process { $script:Started += 'fallback' }

function Run($f) {
    $script:F = $f; $script:Log = @(); $script:Phases = @(); $script:Started = @(); $script:Stopped = @(); $script:LinkTries = 0; $script:Shown = $false
    $r = Start-Bot
    return @{ R = $r; T = (Get-ResultText $r) }
}
$down = @{ Astr = $false; Model = $false; Luma = $false; Running = $false }

# 1. 全部正常：QQ 也连上
$x = Run @{ Initial = $down; AstrUp = $true; ModelUp = $true; LumaUp = $true; Login = 'online'; LinkAfter = 1 }
Expect 'all ok: Ok' $x.R.Ok $true
Expect 'all ok: Code' $x.R.Code 'online'
Expect 'all ok: tone' $x.T.Tone 'green'
Expect 'all ok: started AstrBot+SnowLuma+QQ' ($script:Started -join ',') 'AstrBot,SnowLuma,QQ'

# 2. 小号要手动登录：她照样上线，QQ 窗口叫出来，结果是黄色提示不是失败
$x = Run @{ Initial = $down; AstrUp = $true; ModelUp = $true; LumaUp = $true; Login = 'needlogin'; LinkAfter = 1 }
Expect 'needlogin: Ok' $x.R.Ok $true
Expect 'needlogin: Code' $x.R.Code 'core'
Expect 'needlogin: QqCode' $x.R.QqCode 'needlogin'
Expect 'needlogin: window shown' $script:Shown $true
Expect 'needlogin: tone' $x.T.Tone 'amber'
Expect 'needlogin: title' $x.T.Title '已启动（QQ 没连上）'
Expect 'needlogin: no adapter wait' $script:LinkTries 0

# 3. SnowLuma 起不来：不等 QQ，她照样上线
$x = Run @{ Initial = $down; AstrUp = $true; ModelUp = $true; LumaUp = $false; Login = 'online'; LinkAfter = 1 }
Expect 'lumafail: Ok' $x.R.Ok $true
Expect 'lumafail: QqCode' $x.R.QqCode 'lumafail'
Expect 'lumafail: QQ not started' ($script:Started -contains 'QQ') $false

# 4. 小号登录了但收不到消息：重启一次 AstrBot，还不行就报 adapterfail（她仍在线）
$x = Run @{ Initial = $down; AstrUp = $true; ModelUp = $true; LumaUp = $true; Login = 'online'; LinkAfter = 99 }
Expect 'adapterfail: Ok' $x.R.Ok $true
Expect 'adapterfail: QqCode' $x.R.QqCode 'adapterfail'
Expect 'adapterfail: AstrBot restarted once' (@($script:Started | Where-Object { $_ -eq 'AstrBot' }).Count) 2
# 重启后接上了
$x = Run @{ Initial = $down; AstrUp = $true; ModelUp = $true; LumaUp = $true; Login = 'online'; LinkAfter = 2 }
Expect 'relinked: Code' $x.R.Code 'online'

# 5. AstrBot 起不来：这才算启动失败，不去碰 QQ
$x = Run @{ Initial = $down; AstrUp = $false; ModelUp = $true; LumaUp = $true; Login = 'online'; LinkAfter = 1 }
Expect 'astrfail: Ok' $x.R.Ok $false
Expect 'astrfail: Code' $x.R.Code 'astrfail'
Expect 'astrfail: QQ untouched' ($script:Started -contains 'QQ') $false
Expect 'astrfail: tone' $x.T.Tone 'red'

# 6. 本地模型没起来：她算上线但说不了话，提示里要说明
$x = Run @{ Initial = $down; AstrUp = $true; ModelUp = $false; LumaUp = $true; Login = 'online'; LinkAfter = 1 }
Expect 'nomodel: Ok' $x.R.Ok $true
Expect 'nomodel: tone' $x.T.Tone 'amber'
Expect 'nomodel: mentions model' ($x.T.Detail -like '*本地模型*') $true

# 7. 她本人已经在线、只缺 QQ（看门狗 / 「连 QQ」按钮）：不重启 AstrBot，只补 QQ
$x = Run @{ Initial = @{ Astr = $true; Model = $true; Luma = $true; Running = $false }; AstrUp = $true; ModelUp = $true; LumaUp = $true; Login = 'online'; LinkAfter = 1 }
Expect 'qq only: Code' $x.R.Code 'online'
Expect 'qq only: only QQ started' ($script:Started -join ',') 'QQ'

# 8. 全都在：already
$x = Run @{ Initial = @{ Astr = $true; Model = $true; Luma = $true; Running = $true }; AstrUp = $true; ModelUp = $true; LumaUp = $true; Login = 'online'; LinkAfter = 1 }
Expect 'already: Code' $x.R.Code 'already'
Expect 'already: nothing started' $script:Started.Count 0

# 9. 停止的结果文字
$t = Get-ResultText ([pscustomobject]@{ Kind = 'stop'; Ok = $false; State = [pscustomobject]@{ Astr = $false; Model = $true; Luma = $false; BotQq = $true } })
Expect 'stop leftover text' ($t.Detail -like '*本地模型、小号 QQ*') $true

if ($script:Fail) { Write-Output "panel start tests: $($script:Fail) FAILED"; exit 1 }
Write-Output 'panel start tests: ALL PASSED'
exit 0
