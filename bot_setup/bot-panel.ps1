# 佳树控制台：上线 / 下线（主角）+ 群聊接话和暂停 + 加表情包，一个窗口
# 2026-11-23 改版：照佳树的样子换成奶油底 + 樱花粉；上线 / 下线做成上面一整张大卡片；去掉本地写手的说法
# 由 bot-toggle.ps1 和 add-memes.ps1 合并而来（原脚本已于 2026-10-28 移到回收站）
#
# 用法：
#   bot-panel.ps1                                       打开控制台窗口（桌面快捷方式用这个）
#   bot-panel.ps1 a.png b.gif                           打开窗口，并把这些图片放进待添加列表
#                                                       （把图片拖到桌面快捷方式上也是这个效果）
#   bot-panel.ps1 -Action toggle | start | stop         原「机器人开关」的小窗口模式
#   bot-panel.ps1 -Action status                        只查询状态（纯文本，供脚本调用；ready = 她本人在线，running = 连 QQ 也通了）
#   启动 = 先拉起她本人（本地模型 + AstrBot），就绪就算上线，再顺带连小号 QQ；QQ 连不上不算失败（2026-11-13 起不必登录 QQ）
#   bot-panel.ps1 -Action stop -Quiet                   静默停止 / 启动（自测 / 其它脚本调用）
#   bot-panel.ps1 -NoUi -Files a.png,b.gif -Category reply   不开界面，直接上传表情包（自测 / 批量）
#   bot-panel.ps1 -ReplyChance 15                       不开界面，把聪明插话的起步概率设成 15%（0 = 关闭插件）
#   bot-panel.ps1 -GroupPause on | off | status         不开界面，暂停 / 恢复她在群里说话（2026-11-17：跑训练时用；私聊照常）
#   人格微调窗口在 persona-editor.ps1（本脚本加载它），读写人格用 tools\persona.py
#   「记忆星海」按钮：后台跑 tools\memsea.py 生成 memsea\out\memory-sea.html，生成完用默认浏览器打开
#   「表情包管理」按钮：meme-manager.ps1，全部表情包的增删查改、一张图多个分类、回收站（后端 tools\memes.py）

[CmdletBinding(PositionalBinding = $false)]
param(
    [ValidateSet('panel', 'toggle', 'start', 'stop', 'status')]
    [string]$Action = 'panel',
    [ValidateRange(-1, 100)]
    [int]$ReplyChance = -1,
    [ValidateSet('', 'on', 'off', 'status')]
    [string]$GroupPause = '',
    [switch]$Quiet,
    [string[]]$Files = @(),
    [string]$Category = 'reply',
    [switch]$NoUi,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$DroppedFiles = @()
)

# =====================================================================
#  核心逻辑：从两个原脚本原样搬过来，界面线程和后台线程共用同一份
# =====================================================================
$Core = @'
Add-Type -AssemblyName System.Net.Http

# ---------- 机器人开关：AstrBot + SnowLuma + 小号 QQ 全部由控制台管，不再跟着大号 QQ 走 ----------
$Port      = 6185          # AstrBot 管理面板
$WsPort    = 6199          # AstrBot 收 QQ 消息的端口（SnowLuma 反向 WebSocket 连进来；cmd_config 里的 ws_reverse_port）
$ModelPort = 11435         # 便携 Ollama（local_vision\runtime.ps1 管）：记忆向量 bge-m3 + 看图后备 qwen3-vl（11-22 起本地写手删了）
$LumaPort  = 5099          # SnowLuma WebUI
$ObPort    = 3000          # SnowLuma 给小号开的 OneBot HTTP（小号登录后才会开）
$BotUin    = '555555555'
# 真号和面板密码只在本机 kaju_data\accounts\panel.json（不进仓库）；仓库里的是假号
$PanelLocal = 'D:\JiashuBot\kaju_data\accounts\panel.json'
$PanelConf  = $null
if (Test-Path $PanelLocal) { try { $PanelConf = Get-Content $PanelLocal -Raw -Encoding UTF8 | ConvertFrom-Json } catch {} }
if ($PanelConf -and $PanelConf.bot_uin) { $BotUin = [string]$PanelConf.bot_uin }
$Task      = 'AstrBot-QQBot'
$LumaTask  = 'SnowLuma-QQBot'
$QqPrefix  = 'C:\Program Files\Tencent\QQNT'      # 大号 QQ 安装目录：只拿来当升级来源，不要求它开着
$BotDir    = 'D:\JiashuBot\QQ-Bot'
$BotExe    = Join-Path $BotDir 'QQ.exe'
$BotQqAutoUpdate = $false
$LumaDir   = 'D:\JiashuBot\SnowLuma'
$LumaVbs   = Join-Path $LumaDir 'start-hidden.vbs'
$LumaCfg   = Join-Path $LumaDir "config\onebot_$BotUin.json"
$AstrVbs   = 'C:\Users\18525\.astrbot_launcher\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core\start-hidden.vbs'
$VisionScript = 'D:\JiashuBot\local_vision\runtime.ps1'
$LogFile   = 'D:\JiashuBot\QQ-Bot\toggle.log'
$SkipFile  = Join-Path $BotDir '.skip-version'    # 升级后挂不上 SnowLuma 的版本记在这里，以后不再自动升到它
$FeedUrl   = 'https://cdn-go.cn/qq-web/im.qq.com_new/latest/rainbow/windowsConfig.js'

function Write-Log([string]$msg) {
    try {
        "$(Get-Date -Format 'MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $LogFile -Append -Encoding utf8
    } catch { }
}

function Set-Phase([string]$phase, [string]$detail = '') {
    if ($null -ne $Sync) { $Sync.Detail = $detail; $Sync.Phase = $phase }
}

function Test-Port([int]$port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(400)
        $connected = ($ok -and $client.Connected)
        $client.Close()
        return $connected
    } catch { return $false }
}

function Get-BotQq {
    @(Get-Process QQ -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($BotDir + '\', 'OrdinalIgnoreCase') })
}

function Get-LumaProcs {
    @(Get-Process node -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($LumaDir + '\', 'OrdinalIgnoreCase') })
}

# 小号是不是真的登录在 SnowLuma 上：问 OneBot 的 get_login_info，返回 QQ 号（没登录返回 $null）
function Get-BotLoginUin {
    if (-not (Test-Port $ObPort)) { return $null }
    try {
        $token = ''
        try { $token = [string]((Get-Content $LumaCfg -Raw -Encoding UTF8 | ConvertFrom-Json).networks.httpServers[0].accessToken) } catch { }
        $h = @{}
        if ($token) { $h['Authorization'] = "Bearer $token" }
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$ObPort/get_login_info" -Method Post -Headers $h `
            -ContentType 'application/json' -Body '{}' -TimeoutSec 3
        if ($r.data.user_id) { return [string]$r.data.user_id }
    } catch { }
    return $null
}

function Get-PortOwners([int]$port) {
    return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 0 })
}

# SnowLuma 真的连上了 AstrBot 的收消息端口（光有 6185 面板不代表能收发 QQ 消息）
function Test-AdapterLinked {
    return [bool](Get-NetTCPConnection -LocalPort $WsPort -State Established -ErrorAction SilentlyContinue)
}

function Wait-AdapterLinked([int]$seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if (Test-AdapterLinked) { return $true }
        Start-Sleep -Seconds 1
    }
    return (Test-AdapterLinked)
}

# 启动 AstrBot 前：等 6185 / 6199 都空出来。旧进程还没退干净时直接启动，
# 新 AstrBot 抢不到 6199，面板能打开但收不到任何 QQ 消息（2026-10-29 16:24 出过一次）。
function Wait-AstrPortsFree([int]$seconds = 20) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if ((Get-PortOwners $Port).Count -eq 0 -and (Get-PortOwners $WsPort).Count -eq 0) { return $true }
        Start-Sleep -Seconds 1
    }
    # 还占着：是残留的 python（旧 AstrBot）就清掉，别的程序只记日志
    foreach ($p in @(Get-PortOwners $Port) + @(Get-PortOwners $WsPort) | Select-Object -Unique) {
        $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
        $name = if ($proc) { $proc.ProcessName } else { '?' }
        if ($name -like 'python*') {
            taskkill /PID $p /T /F 2>&1 | Out-Null
            Write-Log "killed leftover AstrBot pid $p ($name) still holding port $Port/$WsPort"
        } else {
            Write-Log "port $Port/$WsPort still held by pid $p ($name); AstrBot may fail to receive QQ messages"
        }
    }
    Start-Sleep -Seconds 2
    return ((Get-PortOwners $Port).Count -eq 0 -and (Get-PortOwners $WsPort).Count -eq 0)
}

# 她本人 = AstrBot + 本地模型（便携 Ollama，记忆向量和看图后备在上面）。QQ 只是聊天渠道之一：
# 没登录 QQ 她照样在线，B站 / 抖音私信照常回（2026-11-13 起私信不靠 QQ 客户端）。
function Get-BotState {
    $astr = Test-Port $Port
    $model = Test-Port $ModelPort
    $luma = Test-Port $LumaPort
    $qq   = (Get-BotQq).Count -gt 0
    $uin  = if ($qq -and $luma) { Get-BotLoginUin } else { $null }
    $online = ($uin -eq $BotUin)
    $wsHeld = (Get-PortOwners $WsPort).Count -gt 0
    $linked = $astr -and $online -and (Test-AdapterLinked)
    return [pscustomobject]@{
        Astr    = $astr
        Model   = $model
        Ready   = ($astr -and $model)                    # 她本人在线（不看 QQ）
        Luma    = $luma
        BotQq   = $qq
        Online  = $online
        Linked  = $linked                               # QQ 消息真的能进到 AstrBot
        QqOk    = $linked                               # QQ 这条渠道通了
        Running = ($astr -and $model -and $luma -and $online -and $linked)   # 全部都在（QQ 看门狗用这个判断要不要重连）
        Any     = ($astr -or $wsHeld -or $luma -or $qq -or $model)   # 有任何一部分在跑
        BotVer  = (Get-QqVersion $BotDir)
    }
}

# ---------- QQ 版本 / 升级 ----------
function Get-QqVersion([string]$root) {
    try {
        $cfg = Get-Content (Join-Path $root 'versions\config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $v = [string]$cfg.curVersion
        if ($v -and (Test-Path (Join-Path $root "versions\$v\QQNT.dll"))) { return $v }
    } catch { }
    return $null
}

# 比较 9.9.36-53644 这种版本号；$parts 只比前几段（官网只给 9.9.36）
function Compare-QqVersion([string]$a, [string]$b, [int]$parts = 4) {
    $x = @([regex]::Matches([string]$a, '\d+') | ForEach-Object { [int64]$_.Value })
    $y = @([regex]::Matches([string]$b, '\d+') | ForEach-Object { [int64]$_.Value })
    for ($i = 0; $i -lt $parts; $i++) {
        $p = if ($i -lt $x.Count) { $x[$i] } else { 0 }
        $q = if ($i -lt $y.Count) { $y[$i] } else { 0 }
        if ($p -ne $q) { return [Math]::Sign($p - $q) }
    }
    return 0
}

function Get-OfficialQqVersion {
    try {
        $js = (Invoke-WebRequest -Uri $FeedUrl -UseBasicParsing -TimeoutSec 6).Content
        if ($js -match '"version"\s*:\s*"([\d.]+)"') { return $Matches[1] }
    } catch { }
    return $null
}

function Set-BotQqCurVersion([string]$ver) {
    $f = Join-Path $BotDir 'versions\config.json'
    $text = [IO.File]::ReadAllText($f, [Text.Encoding]::UTF8)
    $text = [regex]::Replace($text, '("curVersion"\s*:\s*")[^"]*(")', "`${1}$ver`${2}")
    [IO.File]::WriteAllText($f, $text, (New-Object System.Text.UTF8Encoding($false)))
}

function Stop-BotQq {
    $procs = Get-BotQq
    if ($procs.Count -eq 0) { return }
    $procs | Stop-Process -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        if ((Get-BotQq).Count -eq 0) { break }
    }
    Write-Log "bot QQ client stopped"
}

# 小号 QQ 是大号安装目录的一份拷贝。大号 QQ 自己升级后（不用开着），这里把新版本同步到小号。
# 腾讯 CDN 不允许脚本直接下载安装包，所以官网版本只用来提示。
function Update-BotQq {
    $res = [pscustomobject]@{ From = $null; To = $null; Updated = $false; Note = ''; Failed = '' }
    $bot  = Get-QqVersion $BotDir
    $main = Get-QqVersion $QqPrefix
    $skip = ''
    try { $skip = [string](Get-Content $SkipFile -ErrorAction Stop | Select-Object -First 1).Trim() } catch { }
    $res.From = $bot

    if ($main -and $main -ne $skip -and (Compare-QqVersion $main $bot) -gt 0) {
        # 大号刚升级完、文件还在写的话先不动
        $vdir = Get-Item (Join-Path $QqPrefix "versions\$main") -ErrorAction SilentlyContinue
        if ($vdir -and ((Get-Date) - $vdir.LastWriteTime).TotalMinutes -lt 2) {
            $res.Note = "QQ 新版本 $main 还在安装中，这次先用 $bot，下次启动再升级。"
        } else {
            Set-Phase 'updating' "小号 QQ $bot → $main，复制文件中…"
            Write-Log "updating bot QQ $bot -> $main"
            Stop-BotQq
            & robocopy $QqPrefix $BotDir /E /XO /R:1 /W:1 /XF .synced-version .skip-version toggle.log /NFL /NDL /NJH /NJS /NP | Out-Null
            $code = $LASTEXITCODE
            $now = Get-QqVersion $BotDir
            if ($code -lt 8 -and $now -eq $main) {
                Set-Content -Path (Join-Path $BotDir '.synced-version') -Value $main -Encoding utf8
                $res.Updated = $true
                $res.To = $main
                Write-Log "bot QQ updated to $main (robocopy exit $code)"
            } else {
                if ($bot -and $now -ne $bot) { try { Set-BotQqCurVersion $bot } catch { } }
                $res.Failed = "升级到 $main 失败（robocopy $code），继续用 $bot。"
                Write-Log "bot QQ update FAILED (robocopy exit $code, now=$now)"
            }
        }
    }

    $cur = if ($res.Updated) { $res.To } else { $bot }
    $official = Get-OfficialQqVersion
    if ($official -and $cur -and (Compare-QqVersion $official $cur 3) -gt 0) {
        $res.Note = "官网已有 QQ $official（小号现在 $cur）。大号 QQ 自己升级后，下次点启动就会自动跟上。"
        Write-Log "official QQ $official is newer than bot copy $cur"
    }
    return $res
}

# ---------- SnowLuma 日志：确认小号 QQ 被挂上、登录的是哪个号 ----------
function Get-LumaLogPos {
    $f = Join-Path $LumaDir "logs\snowluma-$(Get-Date -Format 'yyyy-MM-dd').log"
    $len = 0
    try { $len = (Get-Item $f -ErrorAction Stop).Length } catch { }
    return @{ File = $f; Pos = $len }
}

function Read-LumaLogSince($pos) {
    $out = ''
    $files = @($pos.File)
    $today = Join-Path $LumaDir "logs\snowluma-$(Get-Date -Format 'yyyy-MM-dd').log"
    if ($today -ne $pos.File) { $files += $today }
    foreach ($f in $files) {
        try {
            $fs = New-Object IO.FileStream($f, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]'ReadWrite, Delete')
            $start = if ($f -eq $pos.File) { [Math]::Min($pos.Pos, $fs.Length) } else { 0 }
            [void]$fs.Seek($start, 'Begin')
            $sr = New-Object IO.StreamReader($fs, [Text.Encoding]::UTF8)
            $out += $sr.ReadToEnd()
            $sr.Close()
        } catch { }
    }
    return $out
}

function Show-BotQqWindow {
    try {
        if (-not ('JiashuCtl.Win' -as [type])) {
            $sig = '[DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int n); ' +
                   '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);'
            Add-Type -Namespace JiashuCtl -Name Win -MemberDefinition $sig
        }
        foreach ($p in Get-BotQq) {
            if ($p.MainWindowHandle -ne [IntPtr]::Zero) {
                [void][JiashuCtl.Win]::ShowWindow($p.MainWindowHandle, 9)
                [void][JiashuCtl.Win]::SetForegroundWindow($p.MainWindowHandle)
            }
        }
    } catch { }
}

# 等小号登录。返回 online / wrong:<uin> / needlogin / nohook / exited
function Wait-BotLogin($logPos, [int]$seconds) {
    $hooked = $false
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $seconds) {
        Start-Sleep -Seconds 2
        $left = [int]($seconds - ((Get-Date) - $t0).TotalSeconds)
        Set-Phase 'login' "等小号 $BotUin 自动登录…（最多再等 $([Math]::Max(0, $left)) 秒）"
        if ((Get-BotLoginUin) -eq $BotUin) { return 'online' }
        $procs = Get-BotQq
        if ($procs.Count -eq 0) { return 'exited' }
        $ids = @($procs | ForEach-Object { [string]$_.Id })
        $text = Read-LumaLogSince $logPos
        foreach ($m in [regex]::Matches($text, '\[Hook\] (pipe connected|awaiting login): PID=(\d+)')) {
            if ($ids -contains $m.Groups[2].Value) { $hooked = $true }
        }
        foreach ($m in [regex]::Matches($text, '\[Hook\] login detected: PID=(\d+) UIN=(\d+)')) {
            if ($ids -contains $m.Groups[1].Value) {
                $hooked = $true
                if ($m.Groups[2].Value -ne $BotUin) { return "wrong:$($m.Groups[2].Value)" }
            }
        }
    }
    if ((Get-BotLoginUin) -eq $BotUin) { return 'online' }
    if ($hooked) { return 'needlogin' }
    return 'nohook'
}

function Start-BotQq {
    $pos = Get-LumaLogPos
    Start-Process -FilePath $BotExe -WorkingDirectory $BotDir -WindowStyle Minimized
    Write-Log "bot QQ client started"
    return $pos
}

function Wait-Port([int]$port, [int]$seconds, [bool]$up = $true) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if ((Test-Port $port) -eq $up) { return $true }
        Start-Sleep -Seconds 1
    }
    return ((Test-Port $port) -eq $up)
}

function Start-Component([string]$task, [string]$vbs, [string]$label) {
    schtasks /change /tn $task /enable 2>&1 | Out-Null
    schtasks /run /tn $task 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0 -and (Test-Path $vbs)) {
        Start-Process -FilePath 'wscript.exe' -ArgumentList "`"$vbs`"" -WindowStyle Hidden
        Write-Log "$label started via fallback launcher"
    } else {
        Write-Log "$label started (task $task)"
    }
}

function Stop-ByPort([int]$port, [string]$label) {
    $owners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($procId in $owners) {
        if ($procId -and $procId -gt 0) {
            taskkill /PID $procId /T /F 2>&1 | Out-Null
            Write-Log "killed $label pid $procId (port $port)"
        }
    }
}

# 一键启动：先把她本人（本地模型 + AstrBot）拉起来，就绪就算上线；再顺带连小号 QQ。
# QQ 连不上不算启动失败（2026-11-13 起她不靠 QQ 也在线，B站 / 抖音私信照常回），只在结果里说明；
# QQ 掉线由计划任务 KajuQQWatchdog 每 3 分钟重连（它也调这里，只补缺的部分）。
# 返回：Ok = 她本人起来了；Code = already / online（QQ 也通了）/ core（QQ 没通，看 QqCode）/ astrfail
#       QqCode = online / needlogin / nohook / exited / wrong:<号> / lumafail / adapterfail；Model = 本地模型开着
function Start-Bot {
    Set-Phase 'checking' '正在检查…'
    $upd = $null
    $s = Get-BotState
    if ($s.Running) { return [pscustomobject]@{ Kind = 'start'; Ok = $true; Code = 'already'; QqCode = 'online'; Model = $true; Update = $null; Uin = $BotUin } }

    # 1. 本地模型（记忆向量、看图后备）
    if (-not $s.Model -and (Test-Path -LiteralPath $VisionScript)) {
        Set-Phase 'starting' '启动本地模型…'
        try { & $VisionScript -Action Start | Out-Null; Write-Log 'local model service (Ollama 11435) started' }
        catch { Write-Log "local model start failed: $($_.Exception.Message)" }
    }

    # 小号 QQ 自动升级（默认关），只在小号没开时做
    if ($BotQqAutoUpdate -and -not $s.BotQq) {
        Set-Phase 'checking' '检查小号 QQ 有没有新版本…'
        $upd = Update-BotQq
    }

    # 2. AstrBot 和 SnowLuma 一起开（SnowLuma 只给 QQ 用，开得慢不耽误她）
    Set-Phase 'starting' '启动 AstrBot…'
    if (-not $s.Astr) {
        if (-not (Wait-AstrPortsFree 20)) { Write-Log 'starting AstrBot although port 6185/6199 is still busy' }
        Start-Component $Task $AstrVbs 'AstrBot'
    }
    if (-not $s.Luma -and (Get-LumaProcs).Count -eq 0) { Start-Component $LumaTask $LumaVbs 'SnowLuma' }

    # 3. 等她本人就绪
    Set-Phase 'starting' '等 AstrBot 就绪…'
    $astrOk = Wait-Port $Port 90
    if (-not $astrOk -and (Test-Path $AstrVbs)) {
        Start-Process -FilePath 'wscript.exe' -ArgumentList "`"$AstrVbs`"" -WindowStyle Hidden
        Write-Log 'AstrBot fallback launcher started'
        $astrOk = Wait-Port $Port 60
    }
    $modelOk = Wait-Port $ModelPort 30
    if (-not $modelOk) { Write-Log 'local model port 11435 not open' }
    if (-not $astrOk) {
        Write-Log 'start finished: ok=False code=astrfail'
        return [pscustomobject]@{ Kind = 'start'; Ok = $false; Code = 'astrfail'; QqCode = ''; Model = $modelOk; Update = $upd; Uin = $BotUin }
    }

    # 4. 小号 QQ（可选）
    Set-Phase 'qq' '她已经上线了，正在连 QQ…'
    $qq = 'online'
    if (-not (Wait-Port $LumaPort 40)) {
        Write-Log 'SnowLuma did not open port 5099'
        $qq = 'lumafail'
    } elseif ((Get-BotLoginUin) -ne $BotUin) {
        if ((Get-BotQq).Count -eq 0) {
            Set-Phase 'qq' '她已经上线了，正在打开小号 QQ…'
            $pos = Start-BotQq
        } else {
            $pos = @{ File = (Get-LumaLogPos).File; Pos = 0 }
        }
        $qq = Wait-BotLogin $pos 60

        # 刚升级过、但新版本 SnowLuma 挂不上 → 退回旧版本，以后不再自动升到这个版本
        if ($qq -eq 'nohook' -and $upd -and $upd.Updated -and $upd.From) {
            Write-Log "SnowLuma could not hook QQ $($upd.To); rolling back to $($upd.From)"
            Set-Phase 'updating' "新版本 $($upd.To) 挂不上 SnowLuma，退回 $($upd.From)…"
            Stop-BotQq
            try {
                Set-BotQqCurVersion $upd.From
                Set-Content -Path $SkipFile -Value $upd.To -Encoding utf8
                Set-Content -Path (Join-Path $BotDir '.synced-version') -Value $upd.From -Encoding utf8
                $upd.Failed = "新版本 $($upd.To) 和 SnowLuma 不兼容，已退回 $($upd.From)，以后不会再自动升到 $($upd.To)。"
                $upd.Updated = $false
            } catch { }
            $pos = Start-BotQq
            $qq = Wait-BotLogin $pos 60
        }

        if ($qq -like 'wrong:*') {
            Write-Log "bot QQ logged in as $($qq.Substring(6)) instead of $BotUin; closed it"
            Stop-BotQq
        } elseif ($qq -eq 'needlogin') {
            Show-BotQqWindow
        }
        Write-Log "bot QQ login result: $qq"
    }

    # 5. 小号登录了，确认 SnowLuma 真的连上了 AstrBot（6199）。没连上 = 收不到 QQ 消息，重启一次 AstrBot。
    if ($qq -eq 'online') {
        Set-Phase 'qq' '确认 QQ 消息能收到…'
        $linked = Wait-AdapterLinked 45
        if (-not $linked) {
            Write-Log "QQ adapter not linked (port $WsPort listening: $((Get-PortOwners $WsPort).Count -gt 0)); restarting AstrBot once"
            Set-Phase 'qq' 'QQ 连接没接上，重启 AstrBot…'
            Stop-ByPort $Port 'AstrBot'
            Stop-ByPort $WsPort 'AstrBot adapter'
            [void](Wait-AstrPortsFree 20)
            Start-Component $Task $AstrVbs 'AstrBot'
            $astrOk = Wait-Port $Port 120
            $linked = $astrOk -and (Wait-AdapterLinked 60)
            if (-not $astrOk) {
                Write-Log 'start finished: ok=False code=astrfail (after adapter restart)'
                return [pscustomobject]@{ Kind = 'start'; Ok = $false; Code = 'astrfail'; QqCode = 'adapterfail'; Model = $modelOk; Update = $upd; Uin = $BotUin }
            }
        }
        Write-Log "QQ adapter linked: $linked"
        if (-not $linked) { $qq = 'adapterfail' }
    }

    $code = if ($qq -eq 'online') { 'online' } else { 'core' }
    Write-Log ("start finished: ok=True code=$code qq=$qq model=$modelOk")
    return [pscustomobject]@{ Kind = 'start'; Ok = $true; Code = $code; QqCode = $qq; Model = $modelOk; Update = $upd; Uin = $BotUin }
}

# 一键停止：小号 QQ、SnowLuma、AstrBot、本地模型全关（AstrBot 先关，不然它的插件会把本地模型又拉起来）
function Stop-Bot {
    Set-Phase 'stopping' '关小号 QQ…'
    Stop-BotQq

    Set-Phase 'stopping' '关 SnowLuma…'
    Stop-ByPort $LumaPort 'SnowLuma'
    foreach ($p in Get-LumaProcs) {
        taskkill /PID $p.Id /T /F 2>&1 | Out-Null
        Write-Log "killed SnowLuma pid $($p.Id)"
    }

    Set-Phase 'stopping' '关 AstrBot…'
    Stop-ByPort $Port 'AstrBot'
    Stop-ByPort $WsPort 'AstrBot adapter'

    Set-Phase 'stopping' '关本地模型…'
    if (Test-Path -LiteralPath $VisionScript) {
        try { & $VisionScript -Action Stop | Out-Null; Write-Log 'local model service stopped' }
        catch { Write-Log "local model stop failed: $($_.Exception.Message)" }
    }

    for ($i = 0; $i -lt 15; $i++) {
        $s = Get-BotState
        if (-not $s.Any) { break }
        Start-Sleep -Seconds 1
    }
    $s = Get-BotState
    if ($s.Any) {
        # 还有残留就再补一刀
        Stop-BotQq
        Stop-ByPort $LumaPort 'SnowLuma'
        Stop-ByPort $Port 'AstrBot'
        Stop-ByPort $WsPort 'AstrBot adapter'
        if ($s.Model -and (Test-Path -LiteralPath $VisionScript)) { try { & $VisionScript -Action Stop | Out-Null } catch { } }
        Start-Sleep -Seconds 2
        $s = Get-BotState
    }
    $ok = -not $s.Any
    Write-Log ("stop finished: ok=$ok")
    return [pscustomobject]@{ Kind = 'stop'; Ok = $ok; State = $s }
}

# QQ 没通时的一句话原因
function Get-QqReason([string]$code) {
    switch -Wildcard ($code) {
        'needlogin'   { return "小号 QQ 要手动登录一次：已把它的窗口叫出来，登录 $BotUin 并勾选「自动登录」，之后就不用管了" }
        'nohook'      { return '小号 QQ 开了，但 SnowLuma 没接上它' }
        'exited'      { return '小号 QQ 启动后又自己关掉了（直接双击 D:\JiashuBot\QQ-Bot\QQ.exe 看看报什么错）' }
        'wrong:*'     { return "小号 QQ 自动登录成了 $($code.Substring(6))，已经把它关了（双击 D:\JiashuBot\QQ-Bot\QQ.exe，选 $BotUin 登录并勾选「自动登录」）" }
        'lumafail'    { return 'SnowLuma 没起来（看 SnowLuma\logs\stdout.log）' }
        'adapterfail' { return '小号登录了，但 SnowLuma 连不上 AstrBot 的 6199 端口（重启过一次也不行）' }
        default       { return "QQ 没连上（$code）" }
    }
}

# 给界面 / 命令行用的一句话结果
function Get-ResultText($r) {
    $t = ''; $d = ''; $tone = 'red'
    if ($r.Kind -eq 'stop') {
        if ($r.Ok) { $t = '已下线'; $d = '她本人（AstrBot、记忆模型）和 QQ 都关了，她不会回话，也不烧 token。'; $tone = 'red' }
        else {
            $left = @()
            if ($r.State.Astr) { $left += 'AstrBot' }
            if ($r.State.Model) { $left += '记忆模型' }
            if ($r.State.Luma) { $left += 'SnowLuma' }
            if ($r.State.BotQq) { $left += '小号 QQ' }
            $t = '没停干净'; $d = "还在运行：$($left -join '、')。再点一次「全部关掉」，或看开关日志。"; $tone = 'red'
        }
    } else {
        $noModel = if ($r.Ok -and -not $r.Model) { ' 不过记忆模型（Ollama 11435）没开，她能说话但想不起以前的事；看看 local_vision\runtime.ps1 -Action Status。' } else { '' }
        switch ($r.Code) {
            'already'  { $t = '她已经在线了'; $d = '她本人和 QQ 都在跑。'; $tone = 'green' }
            'online'   { $t = '上线了'; $d = 'QQ 群聊 / 私聊、B站和抖音私信都能回。'; $tone = 'green' }
            'core'     { $t = '上线了（QQ 没连上）'; $d = "她在线，B站 / 抖音私信照常回；QQ 这边：$(Get-QqReason $r.QqCode)。QQ 掉线时看门狗每 3 分钟会自动重连，也可以点「补连 QQ」。"; $tone = 'amber' }
            'astrfail' { $t = 'AstrBot 没起来'; $d = '3 分钟内没等到 AstrBot（6185 端口），她没上线。看看 core\logs\stdout.log。'; $tone = 'red' }
            default    { $t = '启动失败'; $d = "结果：$($r.Code)。详情见开关日志。"; $tone = 'red' }
        }
        if ($noModel) { $d += $noModel; if ($tone -eq 'green') { $tone = 'amber' } }
        if ($r.Update) {
            if ($r.Update.Updated) { $d += " 小号 QQ 已从 $($r.Update.From) 升级到 $($r.Update.To)。" }
            if ($r.Update.Failed) { $d += ' ' + $r.Update.Failed }
            if ($r.Update.Note) { $d += ' ' + $r.Update.Note }
        }
    }
    return [pscustomobject]@{ Title = $t; Detail = $d; Tone = $tone }
}

# ---------- 加表情包（来自 add-memes.ps1） ----------
$Base    = 'http://127.0.0.1:6185'
$PackId  = 'kaju_memes'
$User    = 'astrbot'
$Pass    = 'AstrBot555555555'
if ($PanelConf -and $PanelConf.dashboard_password) { $Pass = [string]$PanelConf.dashboard_password }
$DataDir = 'C:\Users\18525\.astrbot_launcher\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core\data'
$PackDir = Join-Path $DataDir 'plugin_data\meme_manager\packs\kaju_memes'

$script:Token = $null
$script:Http = $null

function Get-HttpClient {
    if (-not $script:Http) {
        $script:Http = New-Object System.Net.Http.HttpClient
        $script:Http.Timeout = [TimeSpan]::FromSeconds(45)
    }
    return $script:Http
}

function Get-Mime([string]$path) {
    switch ([IO.Path]::GetExtension($path).ToLowerInvariant()) {
        '.png'  { 'image/png' }
        '.jpg'  { 'image/jpeg' }
        '.jpeg' { 'image/jpeg' }
        '.gif'  { 'image/gif' }
        '.webp' { 'image/webp' }
        default { 'application/octet-stream' }
    }
}

function Connect-Bot {
    $client = Get-HttpClient
    $json = @{ username = $User; password = $Pass } | ConvertTo-Json -Compress
    $content = New-Object System.Net.Http.StringContent($json, [Text.Encoding]::UTF8, 'application/json')
    try {
        $resp = $client.PostAsync("$Base/api/auth/login", $content).GetAwaiter().GetResult()
    } catch {
        throw "连不上 AstrBot（$Base）。她可能没上线，先点上面的「让佳树上线」。"
    }
    $text = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    if (-not $resp.IsSuccessStatusCode) { throw "登录 AstrBot 失败：$($resp.StatusCode) $text" }
    $script:Token = ($text | ConvertFrom-Json).data.token
}

function Get-Categories {
    $path = Join-Path $PackDir 'memes_data.json'
    try {
        $obj = Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $names = @($obj.PSObject.Properties.Name)
        if ($names.Count -gt 0) { return $names }
    } catch { }
    return @('happy', 'angry', 'sad', 'confused', 'surprised', 'shy', 'tired', 'eating',
             'affection', 'teasing', 'approval', 'reply', '嫌弃')
}

function Send-Meme([string]$path, [string]$cat) {
    if (-not $script:Token) { Connect-Bot }
    $client = Get-HttpClient
    $name = [IO.Path]::GetFileName($path)

    $bytes = [IO.File]::ReadAllBytes($path)
    $fileContent = New-Object System.Net.Http.ByteArrayContent(, $bytes)
    $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse((Get-Mime $path))

    $form = New-Object System.Net.Http.MultipartFormDataContent
    $safeName = if ($name -match '[^\x20-\x7E]') { 'upload' + [IO.Path]::GetExtension($path) } else { $name }
    $form.Add($fileContent, 'file', $safeName)

    $url = "$Base/api/plug/meme_manager/emoji/add/$PackId/$([uri]::EscapeDataString($cat))"
    $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Post, $url)
    $req.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $script:Token)
    $req.Content = $form

    try {
        $resp = $client.SendAsync($req).GetAwaiter().GetResult()
    } catch {
        return [pscustomobject]@{ Ok = $false; Duplicate = $false; Message = "请求失败：$($_.Exception.Message)"; Name = $name }
    }
    $text = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    $code = [int]$resp.StatusCode

    if ($code -eq 201) {
        return [pscustomobject]@{ Ok = $true; Duplicate = $false; Message = ''; Name = $name }
    }
    if ($code -eq 409) {
        return [pscustomobject]@{ Ok = $false; Duplicate = $true; Message = ''; Name = $name }
    }
    $msg = ''
    try { $msg = ($text | ConvertFrom-Json).message } catch { $msg = $text }
    return [pscustomobject]@{ Ok = $false; Duplicate = $false; Message = "$code $msg"; Name = $name }
}

# ---------- 转移分类 / 新建分类（控制台新增），同样走插件接口 ----------
function Invoke-PluginJson([string]$route, [hashtable]$body) {
    if (-not $script:Token) { Connect-Bot }
    $client = Get-HttpClient
    $json = $body | ConvertTo-Json -Compress -Depth 4
    $content = New-Object System.Net.Http.StringContent($json, [Text.Encoding]::UTF8, 'application/json')
    $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Post, "$Base/api/plug/meme_manager/$route")
    $req.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $script:Token)
    $req.Content = $content
    try {
        $resp = $client.SendAsync($req).GetAwaiter().GetResult()
    } catch {
        return [pscustomobject]@{ Code = 0; Data = $null; Message = "请求失败：$($_.Exception.Message)" }
    }
    $text = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    $obj = $null
    try { $obj = $text | ConvertFrom-Json } catch { }
    $msg = if ($obj -and $obj.message) { $obj.message } else { $text }
    return [pscustomobject]@{ Code = [int]$resp.StatusCode; Data = $obj; Message = $msg }
}

function New-MemeCategory([string]$name, [string]$desc) {
    $r = Invoke-PluginJson 'category/restore' @{ category = $name; description = $desc; managed_pack_id = $PackId }
    return [pscustomobject]@{ Ok = ($r.Code -eq 200); Message = "$($r.Code) $($r.Message)" }
}

function Set-MemeCategoryDesc([string]$name, [string]$desc) {
    $r = Invoke-PluginJson 'category/update_description' @{ tag = $name; description = $desc; managed_pack_id = $PackId }
    return [pscustomobject]@{ Ok = ($r.Code -eq 200); Message = "$($r.Code) $($r.Message)" }
}

# ---------- 群聊主动接话（控制台新增）：聪明插话插件 astrbot_plugin_smart_chime_in 的配置 ----------
# 滑块 = 插件的 base_chance（一波聊天聊完后插话的起步概率），0 = 关掉插件的 enable。
# AstrBot 自带的 active_reply（每条消息随机插话）已被这个插件取代，保持关闭，这里不再碰它。
# 只改 enable / base_chance（必要时 max_chance）这几项文字，其它配置原样不动
$ChimePlugin = 'astrbot_plugin_smart_chime_in'
$CfgFile     = Join-Path $DataDir "config\$($ChimePlugin)_config.json"
$CfgBackup   = 'D:\JiashuBot\_backup\smart_chime_in_config.before-panel.json'   # 滑块改配置前的上一版
$NumRx       = '[-0-9.eE]+'

function Get-ChimeNumber([string]$text, [string]$key) {
    $p = [regex]::Match($text, '"' + $key + '"\s*:\s*(' + $NumRx + ')')
    if (-not $p.Success) { return $null }
    return [double]::Parse($p.Groups[1].Value, [Globalization.CultureInfo]::InvariantCulture)
}

# 返回 0-100 的整数（插件关着算 0）；读不到返回 $null
function Get-ReplyChance {
    $text = [IO.File]::ReadAllText($CfgFile, [Text.Encoding]::UTF8)
    if ($text -match '"enable"\s*:\s*false') { return 0 }
    $base = Get-ChimeNumber $text 'base_chance'
    if ($null -eq $base) { return $null }
    return [int][Math]::Round($base * 100)
}

# 机器人在线：交给 AstrBot 的插件配置接口保存（会热重载插件，立刻生效）；离线：直接改文件，下次启动生效
function Set-ReplyChance([int]$pct) {
    $pct = [Math]::Max(0, [Math]::Min(100, $pct))
    $raw  = [IO.File]::ReadAllBytes($CfgFile)
    $text = [IO.File]::ReadAllText($CfgFile, [Text.Encoding]::UTF8).TrimStart([char]0xFEFF)
    if ($text -notmatch '"enable"\s*:\s*(true|false)' -or $null -eq (Get-ChimeNumber $text 'base_chance')) {
        throw "配置文件里找不到 enable / base_chance，没有改动。"
    }
    $inv     = [Globalization.CultureInfo]::InvariantCulture
    $enable  = if ($pct -gt 0) { 'true' } else { 'false' }
    $newText = [regex]::Replace($text, '("enable"\s*:\s*)(true|false)', "`${1}$enable")
    if ($pct -gt 0) {
        $val = ($pct / 100.0).ToString('0.0#', $inv)
        $newText = [regex]::Replace($newText, '("base_chance"\s*:\s*)' + $NumRx, "`${1}$val")
        # 起步概率超过上限时，上限一起抬上去，不然滑块拉高了也没用
        $max = Get-ChimeNumber $newText 'max_chance'
        if ($null -ne $max -and $max * 100 -lt $pct) {
            $newText = [regex]::Replace($newText, '("max_chance"\s*:\s*)' + $NumRx, "`${1}$val")
        }
    }
    [IO.File]::WriteAllBytes($CfgBackup, $raw)

    if (-not (Test-Port $Port)) {
        $bom = ($raw.Length -ge 3 -and $raw[0] -eq 0xEF -and $raw[1] -eq 0xBB -and $raw[2] -eq 0xBF)
        [IO.File]::WriteAllText($CfgFile, $newText, (New-Object System.Text.UTF8Encoding($bom)))
        return [pscustomobject]@{ Pct = (Get-ReplyChance); Live = $false }
    }

    if (-not $script:Token) { Connect-Bot }
    $client = Get-HttpClient
    $json = $newText
    $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Post, "$Base/api/config/plugin/update?plugin_name=$ChimePlugin")
    $req.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $script:Token)
    $req.Content = New-Object System.Net.Http.StringContent($json, [Text.Encoding]::UTF8, 'application/json')
    try {
        $resp = $client.SendAsync($req).GetAwaiter().GetResult()
    } catch {
        throw "请求失败：$($_.Exception.Message)"
    }
    $respText = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    $obj = $null
    try { $obj = $respText | ConvertFrom-Json } catch { }
    if (-not $resp.IsSuccessStatusCode -or -not $obj -or $obj.status -ne 'ok') {
        $msg = if ($obj -and $obj.message) { $obj.message } else { $respText }
        throw "AstrBot 没接受这次修改：$([int]$resp.StatusCode) $msg"
    }
    $now = Get-ReplyChance
    if ($now -ne $pct) { throw "AstrBot 说保存成功，但配置文件里现在是 $now%。" }
    return [pscustomobject]@{ Pct = $now; Live = $true }
}

# ---------- 群聊暂停（2026-11-17 兄长：“我不希望在跑训练时她会说话”）----------
# 和 kaju_core\gpu_busy.py 用同一个文件：group_pause.json 在 = 暂停（不过期、只能手动恢复）；training.json 是训练脚本自己挂的（进程在、6 小时内才算）。
# 机器人每条群消息都看这两个文件，改了立刻生效、不用重启；机器人没开时也能改。私聊照常。
$QuietDir  = 'D:\JiashuBot\kaju_data\cache\gpu_busy'
$PauseFile = Join-Path $QuietDir 'group_pause.json'
$TrainFile = Join-Path $QuietDir 'training.json'

function Get-GroupQuiet {
    $paused = Test-Path -LiteralPath $PauseFile
    $what = ''; $since = $null
    if ($paused) {
        try {
            $o = [IO.File]::ReadAllText($PauseFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
            $what = [string]$o.what
            $since = [DateTimeOffset]::FromUnixTimeMilliseconds([long]([double]$o.since * 1000)).LocalDateTime
        } catch { $what = '兄长暂停了群聊' }
    }
    $train = ''
    if (Test-Path -LiteralPath $TrainFile) {
        try {
            $t = [IO.File]::ReadAllText($TrainFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
            $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$t.since
            if ($age -lt 6 * 3600 -and (Get-Process -Id ([int]$t.pid) -ErrorAction SilentlyContinue)) { $train = [string]$t.what }
        } catch { }
    }
    return [pscustomobject]@{ Paused = $paused; What = $what; Since = $since; Training = $train }
}

function Set-GroupPause([bool]$on, [string]$what = '兄长在控制台暂停了群聊') {
    if ($on) {
        if (-not (Test-Path -LiteralPath $QuietDir)) { New-Item -ItemType Directory -Force -Path $QuietDir | Out-Null }
        $since = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
        $json = '{"since": ' + $since.ToString([Globalization.CultureInfo]::InvariantCulture) + ', "what": ' + (ConvertTo-Json $what) + '}'
        $tmp = "$PauseFile.panel.tmp"
        [IO.File]::WriteAllText($tmp, $json, (New-Object System.Text.UTF8Encoding($false)))   # 先写临时文件再换过去，机器人不会读到半个文件
        Move-Item -LiteralPath $tmp -Destination $PauseFile -Force
    } elseif (Test-Path -LiteralPath $PauseFile) {
        Remove-Item -LiteralPath $PauseFile -Force
    }
    return Get-GroupQuiet
}
'@
. ([scriptblock]::Create($Core))

# =====================================================================
#  命令行模式（行为和两个原脚本完全一样）
# =====================================================================

# ---------- 表情包：无界面模式（自测 / 批量） ----------
if ($NoUi) {
    $ErrorActionPreference = 'Stop'
    if ($Files.Count -eq 0) { Write-Output 'no files'; exit 1 }
    $results = @()
    foreach ($f in $Files) {
        $r = Send-Meme $f $Category
        $state = if ($r.Ok) { 'OK' } elseif ($r.Duplicate) { 'DUPLICATE' } else { 'FAIL' }
        Write-Output ("{0} {1} {2}" -f $state, $r.Name, $r.Message)
        $results += $r
    }
    exit 0
}

# ---------- 群聊主动接话概率：无界面模式（自测 / 批量） ----------
if ($ReplyChance -ge 0) {
    $ErrorActionPreference = 'Stop'
    try {
        $r = Set-ReplyChance $ReplyChance
        Write-Output ("OK reply_chance={0}% live={1}" -f $r.Pct, $r.Live)
        exit 0
    } catch {
        Write-Output "FAIL $($_.Exception.Message)"
        exit 1
    }
}

# ---------- 群聊暂停：无界面模式 ----------
if ($GroupPause) {
    $q = if ($GroupPause -eq 'status') { Get-GroupQuiet } else { Set-GroupPause ($GroupPause -eq 'on') }
    "group_paused=$($q.Paused) training=$([bool]$q.Training) what=$($q.What) $($q.Training)"
    exit 0
}

$ErrorActionPreference = 'Continue'

# ---------- 机器人：仅查询状态 ----------
if ($Action -eq 'status') {
    $s = Get-BotState
    # running = 全部都在（含 QQ，看门狗用）；ready = 她本人在线（AstrBot + 本地模型，不看 QQ）
    "running=$($s.Running) ready=$($s.Ready) astrbot=$($s.Astr) model=$($s.Model) snowluma=$($s.Luma) bot_qq=$($s.BotQq) online=$($s.Online) qq_linked=$($s.Linked) bot_qq_version=$($s.BotVer)"
    exit 0
}

# ---------- 机器人：静默模式（自测 / 其它脚本调用） ----------
if ($Quiet -and $Action -eq 'panel') { $Action = 'toggle' }
if ($Quiet) {
    $s = Get-BotState
    $toStop = ($Action -eq 'stop') -or ($Action -eq 'toggle' -and $s.Any)
    $r = if ($toStop) { Stop-Bot } else { Start-Bot }
    $t = Get-ResultText $r
    if ($r.Kind -eq 'stop') { "stopped=$($r.Ok)" } else { "started=$($r.Ok) code=$($r.Code) qq=$($r.QqCode) model=$($r.Model)" }
    "$($t.Title)：$($t.Detail)"
    exit 0
}

# ---------- 机器人：小窗口（-Action toggle / start / stop，给桌面快捷方式用） ----------
if ($Action -ne 'panel') {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $form = New-Object System.Windows.Forms.Form
    $form.FormBorderStyle = 'None'
    $form.StartPosition = 'CenterScreen'
    $form.Size = New-Object System.Drawing.Size(520, 180)
    $form.BackColor = [System.Drawing.Color]::FromArgb(250, 245, 241)   # 和控制台一样的奶油底
    $form.TopMost = $true
    $form.ShowInTaskbar = $false

    $title = New-Object System.Windows.Forms.Label
    $title.Dock = 'Top'
    $title.Height = 50
    $title.TextAlign = 'MiddleCenter'
    $title.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 13, [System.Drawing.FontStyle]::Bold)
    $title.ForeColor = [System.Drawing.Color]::FromArgb(223, 110, 135)
    $title.Text = '佳树'

    $detail = New-Object System.Windows.Forms.Label
    $detail.Dock = 'Fill'
    $detail.Padding = New-Object System.Windows.Forms.Padding(18, 0, 18, 12)
    $detail.TextAlign = 'MiddleCenter'
    $detail.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10)
    $detail.ForeColor = [System.Drawing.Color]::FromArgb(112, 90, 90)
    $detail.Text = ''

    $form.Controls.Add($detail)
    $form.Controls.Add($title)
    $form.Show()
    [System.Windows.Forms.Application]::DoEvents()

    $state = Get-BotState
    $stop = ($Action -eq 'stop') -or ($Action -eq 'toggle' -and $state.Any)
    $detail.Text = if ($stop) { '正在让她下线（她本人和 QQ 都关）…' } else { '正在让她上线，她本人大概 20~60 秒，之后再连 QQ…' }
    $form.Refresh(); [System.Windows.Forms.Application]::DoEvents()

    $r = if ($stop) { Stop-Bot } else { Start-Bot }
    $t = Get-ResultText $r
    $title.Text = $t.Title
    $title.ForeColor = switch ($t.Tone) {
        'green' { [System.Drawing.Color]::FromArgb(58, 124, 86) }
        'amber' { [System.Drawing.Color]::FromArgb(160, 100, 36) }
        default { if ($r.Kind -eq 'stop' -and $r.Ok) { [System.Drawing.Color]::FromArgb(112, 90, 90) } else { [System.Drawing.Color]::FromArgb(170, 64, 68) } }
    }
    $detail.Text = $t.Detail
    $form.Refresh()
    [System.Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds $(if ($r.Ok) { 2600 } else { 6000 })
    $form.Close()
    exit 0
}

# =====================================================================
#  控制台窗口
# =====================================================================

$WindowTitle = '佳树控制台'
$IconPath    = 'D:\JiashuBot\bot_setup\icons\kaju.ico'
$InboxFile   = Join-Path $env:TEMP 'jiashu-panel-inbox.txt'
$ImageExts   = @('.png', '.jpg', '.jpeg', '.gif', '.webp')

# ---------- 只开一个窗口：已经开着的话，把图片交给它，然后把它叫到前面 ----------
$createdNew = $false
$script:Mutex = [System.Threading.Mutex]::new($true, 'Local\JiashuBotPanel', [ref]$createdNew)
if (-not $createdNew) {
    $hand = @(@($Files) + @($DroppedFiles) | Where-Object { $_ })
    if ($hand.Count -gt 0) {
        try { [IO.File]::AppendAllLines($InboxFile, [string[]]$hand, [Text.UTF8Encoding]::new($false)) } catch { }
    }
    try {
        Add-Type -AssemblyName Microsoft.VisualBasic
        [Microsoft.VisualBasic.Interaction]::AppActivate($WindowTitle)
    } catch { }
    exit 0
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ---------- 自绘控件（圆角卡片 / 圆角按钮 / 状态灯 / 缩略图） ----------
$UiSource = @'
using System;
using System.IO;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace JiashuUi
{
    public static class Native
    {
        [DllImport("user32.dll")]
        public static extern bool SetProcessDPIAware();
    }

    public static class Gfx
    {
        public static GraphicsPath Round(RectangleF r, float radius)
        {
            GraphicsPath p = new GraphicsPath();
            float d = radius * 2f;
            if (d > r.Width) d = r.Width;
            if (d > r.Height) d = r.Height;
            if (d < 1f) { p.AddRectangle(r); return p; }
            p.AddArc(r.X, r.Y, d, d, 180, 90);
            p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }

        public static Color BackOf(Control c)
        {
            Control p = c.Parent;
            while (p != null)
            {
                Card card = p as Card;
                if (card != null) return card.Fill;
                if (p.BackColor.A == 255) return p.BackColor;
                p = p.Parent;
            }
            return SystemColors.Control;
        }

        public static Bitmap Thumb(string path, int size, Color tile, Color textColor, Font font)
        {
            Bitmap bmp = new Bitmap(size, size, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
            using (Graphics g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                g.PixelOffsetMode = PixelOffsetMode.HighQuality;
                g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                g.Clear(Color.Transparent);
                using (GraphicsPath tp = Round(new RectangleF(0, 0, size - 1, size - 1), size / 7f))
                using (SolidBrush tb = new SolidBrush(tile))
                    g.FillPath(tb, tp);
                bool drawn = false;
                try
                {
                    byte[] bytes = File.ReadAllBytes(path);
                    using (MemoryStream ms = new MemoryStream(bytes))
                    using (Image img = Image.FromStream(ms))
                    {
                        float pad = size * 0.07f;
                        float box = size - pad * 2f;
                        float scale = Math.Min(box / img.Width, box / img.Height);
                        float w = img.Width * scale, h = img.Height * scale;
                        RectangleF dst = new RectangleF((size - w) / 2f, (size - h) / 2f, w, h);
                        using (GraphicsPath clip = Round(dst, size / 12f))
                        {
                            g.SetClip(clip);
                            g.DrawImage(img, dst);
                            g.ResetClip();
                        }
                        drawn = true;
                    }
                }
                catch { }
                if (!drawn)
                {
                    string ext = Path.GetExtension(path).TrimStart('.').ToUpperInvariant();
                    using (StringFormat sf = new StringFormat())
                    using (SolidBrush b = new SolidBrush(textColor))
                    {
                        sf.Alignment = StringAlignment.Center;
                        sf.LineAlignment = StringAlignment.Center;
                        g.DrawString(ext, font, b, new RectangleF(0, 0, size, size), sf);
                    }
                }
            }
            return bmp;
        }
    }

    public class Card : Panel
    {
        private Color fill = Color.White;
        private Color border = Color.FromArgb(229, 231, 235);
        private int radius = 14;
        private bool dashed = false;
        private float borderWidth = 1f;

        public Card()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.ResizeRedraw | ControlStyles.UserPaint |
                     ControlStyles.SupportsTransparentBackColor, true);
        }

        public Color Fill { get { return fill; } set { fill = value; Invalidate(true); } }
        public Color Border { get { return border; } set { border = value; Invalidate(); } }
        public int Radius { get { return radius; } set { radius = value; Invalidate(); } }
        public bool Dashed { get { return dashed; } set { dashed = value; Invalidate(); } }
        public float BorderWidth { get { return borderWidth; } set { borderWidth = value; Invalidate(); } }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Gfx.BackOf(this));
            g.SmoothingMode = SmoothingMode.AntiAlias;
            float half = borderWidth / 2f;
            RectangleF r = new RectangleF(half, half, Width - borderWidth - 0.5f, Height - borderWidth - 0.5f);
            using (GraphicsPath p = Gfx.Round(r, radius))
            {
                using (SolidBrush b = new SolidBrush(fill)) g.FillPath(b, p);
                if (border.A > 0 && borderWidth > 0)
                {
                    using (Pen pen = new Pen(border, borderWidth))
                    {
                        if (dashed) pen.DashPattern = new float[] { 3f, 2.5f };
                        g.DrawPath(pen, p);
                    }
                }
            }
        }
    }

    public class Pill : Control
    {
        private Color baseColor = Color.FromArgb(37, 99, 235);
        private Color hoverColor = Color.FromArgb(29, 78, 216);
        private Color pressColor = Color.FromArgb(30, 64, 175);
        private Color borderColor = Color.Empty;
        private Color disabledColor = Color.FromArgb(229, 231, 235);
        private Color disabledText = Color.FromArgb(156, 163, 175);
        private int radius = 10;
        private bool interactive = true;
        private bool hover, down;

        public Pill()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.ResizeRedraw | ControlStyles.UserPaint |
                     ControlStyles.SupportsTransparentBackColor, true);
            SetStyle(ControlStyles.Selectable, false);
            ForeColor = Color.White;
            Cursor = Cursors.Hand;
        }

        public Color BaseColor { get { return baseColor; } set { baseColor = value; Invalidate(); } }
        public Color HoverColor { get { return hoverColor; } set { hoverColor = value; Invalidate(); } }
        public Color PressColor { get { return pressColor; } set { pressColor = value; Invalidate(); } }
        public Color BorderColor { get { return borderColor; } set { borderColor = value; Invalidate(); } }
        public Color DisabledColor { get { return disabledColor; } set { disabledColor = value; Invalidate(); } }
        public Color DisabledText { get { return disabledText; } set { disabledText = value; Invalidate(); } }
        public int Radius { get { return radius; } set { radius = value; Invalidate(); } }
        public bool Interactive
        {
            get { return interactive; }
            set { interactive = value; Cursor = value ? Cursors.Hand : Cursors.Default; Invalidate(); }
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; down = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { if (e.Button == MouseButtons.Left) { down = true; Invalidate(); } base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { down = false; Invalidate(); base.OnMouseUp(e); }
        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Gfx.BackOf(this));
            g.SmoothingMode = SmoothingMode.AntiAlias;
            Color f = !Enabled ? disabledColor
                    : (interactive && down) ? pressColor
                    : (interactive && hover) ? hoverColor
                    : baseColor;
            RectangleF r = new RectangleF(0.5f, 0.5f, Width - 1.5f, Height - 1.5f);
            using (GraphicsPath p = Gfx.Round(r, radius))
            {
                using (SolidBrush b = new SolidBrush(f)) g.FillPath(b, p);
                if (borderColor.A > 0 && Enabled)
                    using (Pen pen = new Pen(borderColor, 1f)) g.DrawPath(pen, p);
            }
            TextRenderer.DrawText(g, Text, Font, ClientRectangle, Enabled ? ForeColor : disabledText,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
        }
    }

    public class Dot : Control
    {
        private Color dotColor = Color.FromArgb(156, 163, 175);
        private bool pulse;
        private float phase;
        private Timer timer;

        public Dot()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.ResizeRedraw | ControlStyles.UserPaint |
                     ControlStyles.SupportsTransparentBackColor, true);
            timer = new Timer();
            timer.Interval = 40;
            timer.Tick += delegate { phase += 0.022f; if (phase > 1f) phase -= 1f; Invalidate(); };
        }

        public Color DotColor { get { return dotColor; } set { dotColor = value; Invalidate(); } }
        public bool Pulse
        {
            get { return pulse; }
            set { if (pulse == value) return; pulse = value; timer.Enabled = value; if (!value) phase = 0f; Invalidate(); }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && timer != null) { timer.Dispose(); timer = null; }
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Gfx.BackOf(this));
            g.SmoothingMode = SmoothingMode.AntiAlias;
            float s = Math.Min(Width, Height);
            float cx = Width / 2f, cy = Height / 2f;
            float rCore = s * 0.19f, rHalo = s * 0.33f, rMax = s * 0.5f - 1f;
            using (SolidBrush halo = new SolidBrush(Color.FromArgb(46, dotColor)))
                g.FillEllipse(halo, cx - rHalo, cy - rHalo, rHalo * 2f, rHalo * 2f);
            if (pulse)
            {
                float rr = rCore + (rMax - rCore) * phase;
                int a = (int)(130 * (1f - phase));
                using (Pen pen = new Pen(Color.FromArgb(Math.Max(0, a), dotColor), Math.Max(1.5f, s * 0.035f)))
                    g.DrawEllipse(pen, cx - rr, cy - rr, rr * 2f, rr * 2f);
            }
            using (SolidBrush b = new SolidBrush(dotColor))
                g.FillEllipse(b, cx - rCore, cy - rCore, rCore * 2f, rCore * 2f);
        }
    }

    // 控制台主角：一个圆圆的「佳」字徽章，外圈颜色 = 她现在的状态，在线 / 忙的时候外圈轻轻地呼吸
    public class Avatar : Control
    {
        private Color ring = Color.FromArgb(200, 190, 188);
        private Color inner = Color.FromArgb(250, 240, 240);
        private string glyph = "佳";
        private bool pulse;
        private float phase;
        private Timer timer;

        public Avatar()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.ResizeRedraw | ControlStyles.UserPaint |
                     ControlStyles.SupportsTransparentBackColor, true);
            timer = new Timer();
            timer.Interval = 40;
            timer.Tick += delegate { phase += 0.016f; if (phase > 1f) phase -= 1f; Invalidate(); };
        }

        public Color Ring { get { return ring; } set { ring = value; Invalidate(); } }
        public Color Inner { get { return inner; } set { inner = value; Invalidate(); } }
        public string Glyph { get { return glyph; } set { glyph = value; Invalidate(); } }
        public bool Pulse
        {
            get { return pulse; }
            set { if (pulse == value) return; pulse = value; timer.Enabled = value; if (!value) phase = 0f; Invalidate(); }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && timer != null) { timer.Dispose(); timer = null; }
            base.Dispose(disposing);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Gfx.BackOf(this));
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
            float s = Math.Min(Width, Height);
            float cx = Width / 2f, cy = Height / 2f;
            float rRing = s * 0.40f, rInner = s * 0.34f, rMax = s * 0.5f - 1f;
            float w = Math.Max(2f, s * 0.045f);
            if (pulse)
            {
                float rr = rRing + (rMax - rRing) * phase;
                int a = (int)(110 * (1f - phase));
                using (Pen pen = new Pen(Color.FromArgb(Math.Max(0, a), ring), Math.Max(1.5f, s * 0.025f)))
                    g.DrawEllipse(pen, cx - rr, cy - rr, rr * 2f, rr * 2f);
            }
            using (SolidBrush halo = new SolidBrush(Color.FromArgb(36, ring)))
                g.FillEllipse(halo, cx - rRing - w, cy - rRing - w, (rRing + w) * 2f, (rRing + w) * 2f);
            using (Pen pen = new Pen(ring, w))
                g.DrawEllipse(pen, cx - rRing, cy - rRing, rRing * 2f, rRing * 2f);
            using (SolidBrush b = new SolidBrush(inner))
                g.FillEllipse(b, cx - rInner, cy - rInner, rInner * 2f, rInner * 2f);
            using (StringFormat sf = new StringFormat())
            using (SolidBrush tb = new SolidBrush(ForeColor))
            {
                sf.Alignment = StringAlignment.Center;
                sf.LineAlignment = StringAlignment.Center;
                g.DrawString(glyph, Font, tb, new RectangleF(0, s * 0.02f, Width, Height), sf);
            }
        }
    }

    // 粉色小滑块（代替系统自带的蓝色 TrackBar）：点、拖、方向键 / PageUp / PageDown / 滚轮都能改
    public class Slider : Control
    {
        private int min = 0, max = 100, val = 0, small = 1, large = 5;
        private Color track = Color.FromArgb(240, 228, 226);
        private Color fill = Color.FromArgb(223, 110, 135);
        private Color knob = Color.White;
        private bool dragging, hover;
        public event EventHandler ValueChanged;

        public Slider()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.ResizeRedraw | ControlStyles.UserPaint |
                     ControlStyles.SupportsTransparentBackColor | ControlStyles.Selectable, true);
            Cursor = Cursors.Hand;
            TabStop = true;
        }

        public int Minimum { get { return min; } set { min = value; if (val < min) Value = min; Invalidate(); } }
        public int Maximum { get { return max; } set { max = value; if (val > max) Value = max; Invalidate(); } }
        public int SmallChange { get { return small; } set { small = value; } }
        public int LargeChange { get { return large; } set { large = value; } }
        public Color TrackColor { get { return track; } set { track = value; Invalidate(); } }
        public Color FillColor { get { return fill; } set { fill = value; Invalidate(); } }
        public int Value
        {
            get { return val; }
            set
            {
                int v = Math.Max(min, Math.Min(max, value));
                if (v == val) return;
                val = v;
                Invalidate();
                if (ValueChanged != null) ValueChanged(this, EventArgs.Empty);
            }
        }

        private float KnobR { get { return Height * 0.30f; } }
        private float Left0 { get { return KnobR + 2f; } }
        private float Right0 { get { return Width - KnobR - 2f; } }

        private void SetFromX(int x)
        {
            float t = (x - Left0) / Math.Max(1f, Right0 - Left0);
            t = Math.Max(0f, Math.Min(1f, t));
            Value = (int)Math.Round(min + t * (max - min));
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Left && Enabled) { Focus(); dragging = true; SetFromX(e.X); }
            base.OnMouseDown(e);
        }
        protected override void OnMouseMove(MouseEventArgs e) { if (dragging) SetFromX(e.X); base.OnMouseMove(e); }
        protected override void OnMouseUp(MouseEventArgs e) { dragging = false; base.OnMouseUp(e); }
        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnMouseWheel(MouseEventArgs e) { if (Enabled) Value += e.Delta > 0 ? small : -small; base.OnMouseWheel(e); }
        protected override void OnEnabledChanged(EventArgs e) { Cursor = Enabled ? Cursors.Hand : Cursors.Default; Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
        protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
        protected override bool IsInputKey(Keys k)
        {
            return k == Keys.Left || k == Keys.Right || k == Keys.Up || k == Keys.Down || base.IsInputKey(k);
        }
        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (Enabled)
            {
                if (e.KeyCode == Keys.Left || e.KeyCode == Keys.Down) Value -= small;
                else if (e.KeyCode == Keys.Right || e.KeyCode == Keys.Up) Value += small;
                else if (e.KeyCode == Keys.PageDown) Value -= large;
                else if (e.KeyCode == Keys.PageUp) Value += large;
                else if (e.KeyCode == Keys.Home) Value = min;
                else if (e.KeyCode == Keys.End) Value = max;
            }
            base.OnKeyDown(e);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Gfx.BackOf(this));
            g.SmoothingMode = SmoothingMode.AntiAlias;
            float cy = Height / 2f;
            float th = Math.Max(4f, Height * 0.16f);
            float t = max > min ? (val - min) / (float)(max - min) : 0f;
            float kx = Left0 + (Right0 - Left0) * t;
            Color f = Enabled ? fill : Color.FromArgb(214, 200, 198);
            using (GraphicsPath p = Gfx.Round(new RectangleF(Left0 - th / 2f, cy - th / 2f, Right0 - Left0 + th, th), th / 2f))
            using (SolidBrush b = new SolidBrush(track))
                g.FillPath(b, p);
            if (kx > Left0)
                using (GraphicsPath p = Gfx.Round(new RectangleF(Left0 - th / 2f, cy - th / 2f, kx - Left0 + th, th), th / 2f))
                using (SolidBrush b = new SolidBrush(f))
                    g.FillPath(b, p);
            float r = KnobR;
            if (Enabled && (hover || dragging || Focused))
                using (SolidBrush halo = new SolidBrush(Color.FromArgb(48, f)))
                    g.FillEllipse(halo, kx - r * 1.45f, cy - r * 1.45f, r * 2.9f, r * 2.9f);
            using (SolidBrush b = new SolidBrush(knob))
                g.FillEllipse(b, kx - r, cy - r, r * 2f, r * 2f);
            using (Pen pen = new Pen(f, Math.Max(2f, r * 0.28f)))
                g.DrawEllipse(pen, kx - r, cy - r, r * 2f, r * 2f);
        }
    }

    public class ThumbList : ListView
    {
        [DllImport("user32.dll")]
        private static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
        private int spaceX, spaceY;

        public ThumbList() { DoubleBuffered = true; }

        public void SetSpacing(int cx, int cy)
        {
            spaceX = cx; spaceY = cy;
            if (IsHandleCreated) ApplySpacing();
        }

        private void ApplySpacing()
        {
            if (spaceX > 0 && spaceY > 0)
                SendMessage(Handle, 0x1035, IntPtr.Zero, (IntPtr)((spaceY << 16) | (spaceX & 0xFFFF)));
        }

        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); ApplySpacing(); }
    }

    public static class Ico
    {
        // ICO 里的大图常常是 PNG 压缩的，System.Drawing.Icon 读不好，这里直接取最大那张
        public static Bitmap Largest(string path)
        {
            byte[] b = File.ReadAllBytes(path);
            int count = BitConverter.ToUInt16(b, 4);
            int best = -1, bestW = 0;
            for (int i = 0; i < count; i++)
            {
                int w = b[6 + i * 16] == 0 ? 256 : b[6 + i * 16];
                if (w > bestW) { bestW = w; best = i; }
            }
            if (best >= 0)
            {
                int eo = 6 + best * 16;
                int size = BitConverter.ToInt32(b, eo + 8);
                int off = BitConverter.ToInt32(b, eo + 12);
                try
                {
                    using (MemoryStream ms = new MemoryStream(b, off, size))
                    using (Image img = Image.FromStream(ms))
                        return new Bitmap(img);
                }
                catch { }
            }
            using (Icon ic = new Icon(path, 64, 64)) return ic.ToBitmap();
        }
    }
}
'@

# 编译一次后缓存到 %TEMP%，之后打开窗口不用再等编译
if (-not ('JiashuUi.Card' -as [type])) {
    $md5  = [Security.Cryptography.MD5]::Create()
    $hash = -join ($md5.ComputeHash([Text.Encoding]::UTF8.GetBytes($UiSource)) | Select-Object -First 8 | ForEach-Object { $_.ToString('x2') })
    $dll  = Join-Path $env:TEMP "jiashu-panel-ui-$hash.dll"
    if (Test-Path $dll) { try { Add-Type -Path $dll } catch { } }
    if (-not ('JiashuUi.Card' -as [type])) {
        try {
            Add-Type -TypeDefinition $UiSource -ReferencedAssemblies System.Windows.Forms, System.Drawing -OutputAssembly $dll -OutputType Library -ErrorAction Stop
            Add-Type -Path $dll
        } catch {
            Add-Type -TypeDefinition $UiSource -ReferencedAssemblies System.Windows.Forms, System.Drawing
        }
    }
}

[void][JiashuUi.Native]::SetProcessDPIAware()
[System.Windows.Forms.Application]::EnableVisualStyles()

$g0 = [System.Drawing.Graphics]::FromHwnd([IntPtr]::Zero)
$Dpi  = $g0.DpiX / 96.0
$g0.Dispose()

# ---------- 小工具 ----------
function Px([double]$v) { [int][Math]::Round($v * $Dpi) }
function Pt([double]$x, [double]$y) { New-Object System.Drawing.Point((Px $x), (Px $y)) }
function Sz([double]$w, [double]$h) { New-Object System.Drawing.Size((Px $w), (Px $h)) }
function Rgb([int]$r, [int]$g, [int]$b) { [System.Drawing.Color]::FromArgb($r, $g, $b) }
function Fnt([double]$size, [string]$style = 'Regular') {
    New-Object System.Drawing.Font('Microsoft YaHei UI', [single]$size, [System.Drawing.FontStyle]$style)
}

# 配色（2026-11-23 改）：照佳树的样子——温温的奶油底、樱花粉做主色、抹茶绿表示在线，规规矩矩、软软的，不要冷冰冰的蓝灰
$Pal = @{
    Bg          = Rgb 250 245 241
    Card        = Rgb 255 253 251
    Line        = Rgb 239 226 221
    Text        = Rgb 66 46 48
    Sub         = Rgb 112 90 90
    Muted       = Rgb 163 143 141
    Accent      = Rgb 223 110 135
    AccentHover = Rgb 207 92 119
    AccentPress = Rgb 186 76 102
    AccentSoft  = Rgb 252 232 237
    Green       = Rgb 104 170 128
    GreenHover  = Rgb 88 152 112
    GreenPress  = Rgb 72 132 96
    GreenSoft   = Rgb 228 243 233
    GreenText   = Rgb 58 124 86
    Red         = Rgb 214 96 100
    RedHover    = Rgb 196 80 86
    RedPress    = Rgb 172 66 72
    RedSoft     = Rgb 251 233 231
    RedText     = Rgb 170 64 68
    Amber       = Rgb 230 160 80
    AmberSoft   = Rgb 253 240 220
    AmberText   = Rgb 160 100 36
    GreySoft    = Rgb 245 238 234
    GreyText    = Rgb 134 114 112
    DropFill    = Rgb 254 249 247
    DropLine    = Rgb 236 196 206
    DropHot     = Rgb 253 236 241
    HeroFill    = Rgb 255 250 251
    HeroLine    = Rgb 244 218 225
    White       = [System.Drawing.Color]::White
    Clear       = [System.Drawing.Color]::Transparent
}

function New-Label([string]$text, [double]$x, [double]$y, [double]$w, [double]$h, $font, $color, [string]$align = 'MiddleLeft') {
    $l = New-Object System.Windows.Forms.Label
    $l.AutoSize = $false
    $l.UseMnemonic = $false
    $l.Text = $text
    $l.Location = Pt $x $y
    $l.Size = Sz $w $h
    $l.Font = $font
    $l.ForeColor = $color
    $l.BackColor = $Pal.Clear
    $l.TextAlign = $align
    return $l
}

function New-Card([double]$x, [double]$y, [double]$w, [double]$h) {
    $c = New-Object JiashuUi.Card
    $c.Location = Pt $x $y
    $c.Size = Sz $w $h
    $c.Radius = Px 16
    $c.Fill = $Pal.Card
    $c.Border = $Pal.Line
    return $c
}

function New-Button([string]$text, [double]$x, [double]$y, [double]$w, [double]$h, [string]$kind = 'primary', [double]$fontSize = 10) {
    $b = New-Object JiashuUi.Pill
    $b.Text = $text
    $b.Location = Pt $x $y
    $b.Size = Sz $w $h
    $b.Radius = Px 10
    $b.Font = Fnt $fontSize 'Bold'
    $b.DisabledColor = Rgb 241 233 230
    $b.DisabledText = $Pal.Muted
    Set-ButtonKind $b $kind
    return $b
}

function Set-ButtonKind($b, [string]$kind) {
    switch ($kind) {
        'primary' { $b.BaseColor = $Pal.Accent; $b.HoverColor = $Pal.AccentHover; $b.PressColor = $Pal.AccentPress; $b.ForeColor = $Pal.White; $b.BorderColor = [System.Drawing.Color]::Empty }
        'green'   { $b.BaseColor = $Pal.Green;  $b.HoverColor = $Pal.GreenHover;  $b.PressColor = $Pal.GreenPress;  $b.ForeColor = $Pal.White; $b.BorderColor = [System.Drawing.Color]::Empty }
        'red'     { $b.BaseColor = $Pal.Red;    $b.HoverColor = $Pal.RedHover;    $b.PressColor = $Pal.RedPress;    $b.ForeColor = $Pal.White; $b.BorderColor = [System.Drawing.Color]::Empty }
        'ghost'   { $b.BaseColor = $Pal.Card;   $b.HoverColor = (Rgb 253 243 245); $b.PressColor = (Rgb 250 232 237); $b.ForeColor = $Pal.Text; $b.BorderColor = (Rgb 234 214 217) }
        'calm'    { $b.BaseColor = $Pal.RedSoft; $b.HoverColor = (Rgb 247 220 218); $b.PressColor = (Rgb 241 205 203); $b.ForeColor = $Pal.RedText; $b.BorderColor = (Rgb 238 200 198) }
    }
}

function New-Chip([double]$x, [double]$y, [double]$w, [double]$h) {
    $c = New-Object JiashuUi.Pill
    $c.Interactive = $false
    $c.Location = Pt $x $y
    $c.Size = Sz $w $h
    $c.Radius = Px ($h / 2)
    $c.Font = Fnt 8.5 'Bold'
    return $c
}

function Set-Chip($chip, [string]$kind, [string]$text) {
    switch ($kind) {
        'ok'   { $chip.BaseColor = $Pal.GreenSoft; $chip.ForeColor = $Pal.GreenText }
        'warn' { $chip.BaseColor = $Pal.AmberSoft; $chip.ForeColor = $Pal.AmberText }
        'bad'  { $chip.BaseColor = $Pal.RedSoft;   $chip.ForeColor = $Pal.RedText }
        default { $chip.BaseColor = $Pal.GreySoft; $chip.ForeColor = $Pal.GreyText }
    }
    $chip.Text = $text
}

function New-Divider([double]$x, [double]$y, [double]$w) {
    $d = New-Object System.Windows.Forms.Panel
    $d.Location = Pt $x $y
    $d.Size = New-Object System.Drawing.Size((Px $w), [Math]::Max(1, [int]$Dpi))
    $d.BackColor = $Pal.Line
    return $d
}

# ---------- 后台任务（耗时操作放后台，窗口不会卡住） ----------
$script:Sync = [hashtable]::Synchronized(@{ Phase = ''; Detail = ''; Progress = ''; DelProgress = '' })
$script:Pool = [runspacefactory]::CreateRunspacePool(1, 3)
$script:Pool.Open()
$script:Jobs = New-Object System.Collections.ArrayList
$JobHead = "param(`$Sync, `$UpFiles, `$UpCat, `$DelItems, `$BackupDir, `$MoveItems, `$MoveTarget, `$MoveCreate, `$MoveDesc, `$Chance, `$CatName, `$CatDesc, `$CatCreate, `$PyArgs, `$PeId)`n" + $Core + "`n"

function Start-Work([string]$body, [hashtable]$params, [scriptblock]$done) {
    $ps = [powershell]::Create()
    $ps.RunspacePool = $script:Pool
    [void]$ps.AddScript($JobHead + $body)
    [void]$ps.AddParameter('Sync', $script:Sync)
    foreach ($k in $params.Keys) { [void]$ps.AddParameter($k, $params[$k]) }
    $handle = $ps.BeginInvoke()
    [void]$script:Jobs.Add(@{ PS = $ps; Handle = $handle; Done = $done })
}

function Complete-Jobs {
    foreach ($j in @($script:Jobs)) {
        if (-not $j.Handle.IsCompleted) { continue }
        $script:Jobs.Remove($j)
        $out = $null; $err = $null
        try { $out = $j.PS.EndInvoke($j.Handle) } catch { $err = $_.Exception.InnerException; if (-not $err) { $err = $_.Exception }; $err = $err.Message }
        $j.PS.Dispose()
        $res = $null
        if ($out -and $out.Count -gt 0) { $res = $out[$out.Count - 1] }
        try { & $j.Done $res $err } catch { }
    }
}

# 状态查询：AstrBot / SnowLuma / 小号 QQ / 每个分类有几张图
$PollBody = @'
$ErrorActionPreference = 'Continue'
$s = Get-BotState
$counts = @{}
try {
    foreach ($d in Get-ChildItem -LiteralPath (Join-Path $PackDir 'memes') -Directory -ErrorAction Stop) {
        $counts[$d.Name] = @(Get-ChildItem -LiteralPath $d.FullName -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension.ToLowerInvariant() -in '.png', '.jpg', '.jpeg', '.gif', '.webp' }).Count
    }
} catch { }
$chance = $null
try { $chance = Get-ReplyChance } catch { }
$gq = $null
try { $gq = Get-GroupQuiet } catch { }
[pscustomobject]@{ Running = $s.Running; Ready = $s.Ready; Model = $s.Model; QqOk = $s.QqOk; Any = $s.Any; Astr = $s.Astr; Luma = $s.Luma; BotQq = $s.BotQq; Online = $s.Online; Linked = $s.Linked; BotVer = $s.BotVer; Counts = $counts; Chance = $chance; GroupQuiet = $gq }
'@

# 保存群聊主动接话概率
$ChanceBody = @'
$ErrorActionPreference = 'Stop'
$script:Token = $null
Set-ReplyChance $Chance
'@

# 一键启动 / 停止（逻辑在上面的 Start-Bot / Stop-Bot）
$StartBody = @'
$ErrorActionPreference = 'Continue'
$r = Start-Bot
$x = Get-ResultText $r
[pscustomobject]@{ Kind = $r.Kind; Ok = $r.Ok; Code = $r.Code; Title = $x.Title; Detail = $x.Detail; Tone = $x.Tone }
'@

$StopBody = @'
$ErrorActionPreference = 'Continue'
$r = Stop-Bot
$x = Get-ResultText $r
[pscustomobject]@{ Kind = $r.Kind; Ok = $r.Ok; Code = ''; Title = $x.Title; Detail = $x.Detail; Tone = $x.Tone }
'@

# 上传：和原「加表情包」点「添加」时的逻辑一样
$UploadBody = @'
$ErrorActionPreference = 'Stop'
$okCount = 0; $dupCount = 0; $fail = @()
$i = 0; $n = @($UpFiles).Count
foreach ($f in @($UpFiles)) {
    $i++
    $name = [IO.Path]::GetFileName($f)
    $Sync.Progress = "正在上传 $i/$n：$name"
    try {
        $r = Send-Meme $f $UpCat
    } catch {
        $fail += "$name（$($_.Exception.Message)）"
        continue
    }
    if ($r.Ok) { $okCount++ }
    elseif ($r.Duplicate) { $dupCount++ }
    else { $fail += "$name（$($r.Message)）" }
}
[pscustomobject]@{ Ok = $okCount; Dup = $dupCount; Fail = $fail; Cat = $UpCat }
'@

# 新建分类 / 修改分类描述（添加页的两个小按钮）
$CatBody = @'
$ErrorActionPreference = 'Stop'
$script:Token = $null
$r = if ($CatCreate) { New-MemeCategory $CatName $CatDesc } else { Set-MemeCategoryDesc $CatName $CatDesc }
[pscustomobject]@{ Ok = $r.Ok; Message = $r.Message; Name = $CatName; Desc = $CatDesc; Create = $CatCreate }
'@

# 「人格微调」窗口（单独一个文件）
. (Join-Path $PSScriptRoot 'persona-editor.ps1')

# 「表情包管理」窗口（单独一个文件）：全部表情包的增删查改、一张图多个分类、回收站
. (Join-Path $PSScriptRoot 'meme-manager.ps1')

# 「记忆星海」：tools\memsea.py 把佳树记得的东西（聊天记录、长期记忆、日记、此刻记着的事）画成一个能转的 3D 星图，
# 单个网页文件，数据都在里面。只读数据，不改任何东西；机器人开没开都能用
$SeaPy   = 'D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\venv\Scripts\python.exe'
$SeaTool = Join-Path $PSScriptRoot 'tools\memsea.py'
$SeaBody = @'
$ErrorActionPreference = 'Stop'
$text = ''; $fail = ''
$out = [IO.Path]::Combine([IO.Path]::GetTempPath(), 'jiashu-memsea-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = '__PY__'
    $psi.Arguments = '-I "__TOOL__" build --out "' + $out + '"'
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardOutput = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    $errTask = $p.StandardError.ReadToEndAsync()
    [void]$p.StandardOutput.ReadToEndAsync()
    if (-not $p.WaitForExit(120000)) {
        try { $p.Kill() } catch { }
        $fail = '生成记忆星海超时（2 分钟）。'
    } elseif ([IO.File]::Exists($out)) {
        $text = [IO.File]::ReadAllText($out, [Text.Encoding]::UTF8)
    } else {
        $fail = 'memsea.py 没有输出结果：' + $errTask.Result
    }
} catch {
    $fail = $_.Exception.Message
} finally {
    try { if ([IO.File]::Exists($out)) { [IO.File]::Delete($out) } } catch { }
}
[pscustomobject]@{ Text = $text; Err = $fail }
'@
$SeaBody = $SeaBody.Replace('__PY__', $SeaPy).Replace('__TOOL__', $SeaTool)
$script:SeaBusy = $false

# ---------- 窗口 ----------
# 2026-11-23 改版：上线 / 下线是主角（上面一整张大卡片），群聊和加表情包放下面两张小卡片；
# 去掉了本地写手相关的说法（11-22 写手整条删了，本地模型只剩记忆向量 bge-m3 和看图后备 qwen3-vl）
$form = New-Object System.Windows.Forms.Form
$form.Text = $WindowTitle
$form.AutoScaleMode = 'None'
$form.ClientSize = Sz 860 724
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox = $false
$form.BackColor = $Pal.Bg
$form.Font = Fnt 9
$form.AllowDrop = $true
if (Test-Path $IconPath) { try { $form.Icon = New-Object System.Drawing.Icon($IconPath) } catch { } }

$tips = New-Object System.Windows.Forms.ToolTip
$tips.AutoPopDelay = 20000

# 顶部：标题 + 三个小窗口的入口
$hTitle = New-Label '佳树控制台' 26 14 200 32 (Fnt 15 'Bold') $Pal.Text
$hSub   = New-Label '读取中…' 27 44 360 20 (Fnt 8.5) $Pal.Muted
$btnGallery = New-Button '☺ 表情包管理' 476 18 120 36 'ghost' 9.5
$btnSea     = New-Button '✦ 记忆星海' 604 18 112 36 'ghost' 9.5
$btnPersona = New-Button '✎ 人格微调' 724 18 112 36 'ghost' 9.5
$form.Controls.AddRange(@($hTitle, $hSub, $btnGallery, $btnSea, $btnPersona))

# ===== 上：上线 / 下线（主角） =====
$botCard = New-Card 24 72 812 244
$botCard.Fill = $Pal.HeroFill
$botCard.Border = $Pal.HeroLine
$botCard.Radius = Px 20

$avatar = New-Object JiashuUi.Avatar
$avatar.Location = Pt 30 22
$avatar.Size = Sz 136 136
$avatar.Font = Fnt 30 'Bold'
$avatar.ForeColor = $Pal.Muted

$bBig = New-Label '读取中…' 182 30 396 48 (Fnt 22 'Bold') $Pal.Text
$bSub = New-Label '' 184 78 396 24 (Fnt 10) $Pal.Sub
$bSub.AutoEllipsis = $true

# 三样东西各一个小标签：她本人 / 记忆模型 / QQ 小号（鼠标停上去看详细）
$rKeys = @('她本人', '记忆模型', 'QQ 小号')
$rTips = @(
    "AstrBot（127.0.0.1:$Port）：她本人，开着她才会说话",
    "本地 Ollama（127.0.0.1:$ModelPort）：记忆向量 bge-m3 + 看图后备 qwen3-vl；没开她想不起以前的事",
    "小号 $BotUin 经 SnowLuma 连进来；没连上不影响 B站 / 抖音私信，掉线看门狗每 3 分钟自动重连"
)
$chips = @()
for ($i = 0; $i -lt 3; $i++) {
    $x = 184 + $i * 128
    $lab = New-Label $rKeys[$i] $x 114 120 18 (Fnt 8.5) $Pal.Muted
    $chip = New-Chip $x 134 112 26
    Set-Chip $chip 'off' '…'
    $tips.SetToolTip($lab, $rTips[$i])
    $tips.SetToolTip($chip, $rTips[$i])
    $chips += $chip
    $botCard.Controls.AddRange(@($lab, $chip))
}
$chipAstr, $chipModel, $chipQq = $chips

$btnPower = New-Button '让佳树上线' 590 30 196 64 'primary' 13
$btnPower.Radius = Px 32
$btnPower.Enabled = $false
$btnQq = New-Button '补连 QQ' 590 104 196 32 'ghost' 9.5
$btnQq.Radius = Px 16
$btnQq.Visible = $false
$tips.SetToolTip($btnQq, '她本人已经在线，只把 QQ 这条渠道再连一次')

$lnkPanel = New-Object System.Windows.Forms.LinkLabel
$lnkLog   = New-Object System.Windows.Forms.LinkLabel
foreach ($pair in @(@($lnkPanel, '打开管理面板', 594), @($lnkLog, '查看开关日志', 692))) {
    $l = $pair[0]
    $l.Text = $pair[1]
    $l.Location = Pt $pair[2] 144
    $l.Size = Sz 94 20
    $l.Font = Fnt 8.5
    $l.LinkColor = $Pal.Accent
    $l.ActiveLinkColor = $Pal.AccentPress
    $l.LinkBehavior = 'HoverUnderline'
    $l.BackColor = $Pal.Clear
    $l.TextAlign = 'MiddleCenter'
}

$div1 = New-Divider 30 176 752
$div1.BackColor = $Pal.HeroLine

$mTitle  = New-Label '' 30 184 752 20 (Fnt 9.5 'Bold') $Pal.Text
$DefaultBotHint = '「上线」先开她本人（AstrBot + 记忆模型），就绪就算上线，再顺带连 QQ；QQ 没登录不影响 B站 / 抖音私信。「下线」全部关掉，她不回话、也不烧 token。'
$mDetail = New-Label $DefaultBotHint 30 204 752 34 (Fnt 8.5) $Pal.Sub 'TopLeft'
$mDetail.AutoEllipsis = $true
$mTip = New-Object System.Windows.Forms.ToolTip
$mTip.AutoPopDelay = 30000

$botCard.Controls.AddRange(@($avatar, $bBig, $bSub, $btnPower, $btnQq, $lnkPanel, $lnkLog, $div1, $mTitle, $mDetail))

# ===== 左下：群聊（主动接话 + 暂停） =====
$chanceCard = New-Card 24 332 396 372
$cTitle = New-Label '群聊' 22 16 200 26 (Fnt 11.5 'Bold') $Pal.Text
$cHint  = New-Label '没人 @ 她时插不插话，要不要先安静一会儿' 22 42 352 20 (Fnt 9) $Pal.Muted
$cHint.AutoEllipsis = $true

$cSec = New-Label '主动接话' 22 80 160 22 (Fnt 9.5 'Bold') $Pal.Sub
$cValue = New-Label '…' 270 72 104 34 (Fnt 15 'Bold') $Pal.Text 'MiddleRight'

$cTrack = New-Object JiashuUi.Slider
$cTrack.Location = Pt 16 107
$cTrack.Size = Sz 278 34
$cTrack.Minimum = 0
$cTrack.Maximum = 100
$cTrack.SmallChange = 1
$cTrack.LargeChange = 5
$cTrack.FillColor = $Pal.Accent
$cTrack.TrackColor = Rgb 242 230 228
$cTrack.Enabled = $false

$btnChance = New-Button '保存' 302 106 72 34 'primary' 9.5
$btnChance.Enabled = $false
$cStatus = New-Label '读取中…' 22 146 352 40 (Fnt 8.5) $Pal.Muted 'TopLeft'
$cStatus.AutoEllipsis = $true

$cDiv = New-Divider 22 196 352

$qHint = New-Label '群聊暂停' 22 212 160 22 (Fnt 9.5 'Bold') $Pal.Sub
$qChip = New-Chip 244 210 130 26
Set-Chip $qChip 'grey' '读取中…'
$qStatus = New-Label '' 22 244 352 56 (Fnt 8.5) $Pal.Muted 'TopLeft'
$qStatus.AutoEllipsis = $true
$btnPause = New-Button '暂停群聊' 22 310 352 42 'calm' 10
$btnPause.Radius = Px 21
$btnPause.Enabled = $false

$chanceCard.Controls.AddRange(@($cTitle, $cHint, $cSec, $cValue, $cTrack, $btnChance, $cStatus, $cDiv, $qHint, $qChip, $qStatus, $btnPause))

# ===== 右下：加表情包（查看 / 删除 / 改分类 / 回收站在「表情包管理」窗口里） =====
$memeCard = New-Card 436 332 400 372
$eTitle = New-Label '加表情包' 22 16 160 26 (Fnt 11.5 'Bold') $Pal.Text
$eHint  = New-Label '' 22 42 356 20 (Fnt 9) $Pal.Muted
$eHint.AutoEllipsis = $true
$btnManage = New-Button '管理全部 · 回收站 →' 216 12 162 30 'ghost' 8.5

$addPane = New-Object JiashuUi.Card
$addPane.Location = Pt 1 68
$addPane.Size = Sz 398 290
$addPane.Radius = 0
$addPane.Fill = $Pal.Card
$addPane.Border = $Pal.Clear
$addPane.AllowDrop = $true

$drop = New-Object JiashuUi.Card
$drop.Location = Pt 21 4
$drop.Size = Sz 356 138
$drop.Radius = Px 14
$drop.Fill = $Pal.DropFill
$drop.Border = $Pal.DropLine
$drop.BorderWidth = [single][Math]::Max(1.0, $Dpi)
$drop.Dashed = $true
$drop.AllowDrop = $true

$thumbSize = Px 72
$images = New-Object System.Windows.Forms.ImageList
$images.ColorDepth = 'Depth32Bit'
$images.ImageSize = New-Object System.Drawing.Size($thumbSize, $thumbSize)

$lv = New-Object JiashuUi.ThumbList
$lv.Location = Pt 8 8
$lv.Size = Sz 340 122
$lv.View = 'LargeIcon'
$lv.LargeImageList = $images
$lv.BorderStyle = 'None'
$lv.BackColor = $Pal.DropFill
$lv.ForeColor = $Pal.Sub
$lv.Font = Fnt 8.5
$lv.MultiSelect = $true
$lv.AllowDrop = $true
$lv.Visible = $false
$lv.SetSpacing((Px 98), (Px 108))

$lvMenu = New-Object System.Windows.Forms.ContextMenuStrip
$miRemove = $lvMenu.Items.Add('从列表里移除')
$lv.ContextMenuStrip = $lvMenu

# 空状态 / 结果提示（列表为空时显示）
$empty = New-Object JiashuUi.Card
$empty.Location = Pt 2 2
$empty.Size = Sz 352 134
$empty.Radius = 0
$empty.Fill = $Pal.DropFill
$empty.Border = $Pal.Clear
$empty.AllowDrop = $true
$empty.Cursor = [System.Windows.Forms.Cursors]::Hand

$glyph = New-Chip 154 12 44 44
$glyph.Font = Fnt 16 'Bold'
$glyph.Cursor = [System.Windows.Forms.Cursors]::Hand
$eBig = New-Label '' 8 58 336 26 (Fnt 10.5 'Bold') $Pal.Text 'MiddleCenter'
$eSmall = New-Label '' 16 86 320 46 (Fnt 8.5) $Pal.Sub 'TopCenter'
$eSmall.AutoEllipsis = $true
foreach ($c in @($glyph, $eBig, $eSmall)) { $c.AllowDrop = $true; $c.Cursor = [System.Windows.Forms.Cursors]::Hand }
$empty.Controls.AddRange(@($glyph, $eBig, $eSmall))
$drop.Controls.AddRange(@($lv, $empty))

$btnPick  = New-Button '选择图片…' 21 152 104 32 'ghost' 9
$btnClear = New-Button '清空列表' 131 152 86 32 'ghost' 9
$eCount   = New-Label '准备就绪。' 221 152 156 32 (Fnt 8.5) $Pal.Sub 'MiddleRight'
$eCount.AutoEllipsis = $true

function New-CatCombo([double]$x, [double]$y) {
    $cb = New-Object System.Windows.Forms.ComboBox
    $cb.Location = Pt $x $y
    $cb.Width = Px 230
    $cb.DropDownStyle = 'DropDownList'
    $cb.DrawMode = 'OwnerDrawFixed'
    $cb.ItemHeight = Px 24
    $cb.Font = Fnt 9.5
    $cb.MaxDropDownItems = 14
    $cb.IntegralHeight = $false
    return $cb
}

$catLabel = New-Label '分类' 21 192 40 30 (Fnt 9.5) $Pal.Sub
$combo = New-CatCombo 59 193
$combo.Width = Px 152
$combo.DropDownWidth = Px 230
$btnNewCat  = New-Button '＋ 新建' 217 192 78 30 'ghost' 9
$btnEditCat = New-Button '改描述' 301 192 76 30 'ghost' 9
$catDesc = New-Label '' 21 225 356 20 (Fnt 8.5) $Pal.Muted
$catDesc.AutoEllipsis = $true

$btnAdd = New-Button '添加到表情包' 21 248 356 40 'primary' 10.5
$btnAdd.Radius = Px 20

$addPane.Controls.AddRange(@($drop, $btnPick, $btnClear, $eCount, $catLabel, $combo, $catDesc, $btnNewCat, $btnEditCat, $btnAdd))
$memeCard.Controls.AddRange(@($eTitle, $eHint, $btnManage, $addPane))

$form.Controls.AddRange(@($botCard, $chanceCard, $memeCard))

# =====================================================================
#  机器人：状态显示 + 开关
# =====================================================================
$script:BotState = $null
$script:BotBusy  = ''
$script:Polling  = $false
$script:Counts   = @{}

function Show-BotMessage([string]$title, [string]$detail, $color) {
    $mTitle.Text = $title
    $mTitle.ForeColor = $color
    $mDetail.Text = $detail
    $mTip.SetToolTip($mDetail, $detail)
}

# 主角卡片：徽章外圈颜色 + 大字 + 一个大按钮（上线 / 下线）；QQ 没通或没开全时，下面多一个小按钮
function Set-Hero([string]$tone, [bool]$pulse, [string]$big, [string]$sub) {
    switch ($tone) {
        'green' { $avatar.Ring = $Pal.Green; $avatar.Inner = $Pal.GreenSoft; $avatar.ForeColor = $Pal.GreenText }
        'amber' { $avatar.Ring = $Pal.Amber; $avatar.Inner = $Pal.AmberSoft; $avatar.ForeColor = $Pal.AmberText }
        'rose'  { $avatar.Ring = $Pal.Accent; $avatar.Inner = $Pal.AccentSoft; $avatar.ForeColor = $Pal.Accent }
        default { $avatar.Ring = (Rgb 224 208 206); $avatar.Inner = $Pal.GreySoft; $avatar.ForeColor = $Pal.Muted }
    }
    $avatar.Pulse = $pulse
    $bBig.Text = $big
    $bSub.Text = $sub
    $tips.SetToolTip($bSub, $sub)
}

# $mode：on = 按下去让她上线；off = 按下去让她下线；busy = 正在做，按不了
function Set-Power([string]$mode, [string]$text = '') {
    $script:PowerMode = $mode
    switch ($mode) {
        'on'  { Set-ButtonKind $btnPower 'primary'; $btnPower.Text = '让佳树上线'; $btnPower.Enabled = $true }
        'off' { Set-ButtonKind $btnPower 'calm';    $btnPower.Text = '让佳树下线'; $btnPower.Enabled = $true }
        default { $btnPower.Text = $(if ($text) { $text } else { '稍等…' }); $btnPower.Enabled = $false }
    }
}

# 小按钮：qq = 补连 QQ（她本人在线、QQ 没通）；stop = 全部关掉（只开了一部分）；'' = 不显示
function Set-Second([string]$what) {
    $script:SecondAction = $what
    switch ($what) {
        'qq'   { $btnQq.Text = '补连 QQ'; $btnQq.Visible = $true; $tips.SetToolTip($btnQq, '她本人已经在线，只把 QQ 这条渠道再连一次') }
        'stop' { $btnQq.Text = '全部关掉'; $btnQq.Visible = $true; $tips.SetToolTip($btnQq, '把已经开着的那一部分也关掉') }
        default { $btnQq.Visible = $false }
    }
}

function Update-BotView {
    $st = $script:BotState
    $busy = $script:BotBusy
    if ($busy) {
        $big = switch ($busy) {
            'stopping' { '正在下线…' }
            'starting' { '正在上线…' }
            'updating' { '升级小号 QQ…' }
            'qq'       { '已上线，连 QQ…' }
            'login'    { '已上线，等小号登录…' }
            default    { '稍等…' }
        }
        $sub = if ($script:Sync.Detail) { [string]$script:Sync.Detail } else { '正在确认当前状态' }
        Set-Hero 'amber' $true $big $sub
        Set-Power 'busy' $(if ($script:BotBusyKind -eq 'stop') { '正在下线…' } else { '正在上线…' })
        Set-Second ''
    } elseif ($null -eq $st) {
        Set-Hero 'off' $false '读取中…' ''
        Set-Power 'busy' '读取中…'
        Set-Second ''
    } elseif ($st.Ready -and $st.QqOk) {
        Set-Hero 'green' $true '佳树在线' 'QQ 群聊 / 私聊、B站和抖音私信都能回'
        Set-Power 'off'
        Set-Second ''
    } elseif ($st.Ready) {
        # 她本人在线，只是 QQ 这条渠道没通：照样算在线，多一个「补连 QQ」
        $why = if (-not $st.Luma) { 'SnowLuma 没开' } elseif (-not $st.BotQq) { '小号 QQ 没开' } elseif (-not $st.Online) { '小号没登录' } else { 'QQ 消息收不到' }
        Set-Hero 'green' $true '佳树在线' "QQ 没连上（$why），B站 / 抖音私信照常回"
        Set-Power 'off'
        Set-Second 'qq'
    } elseif ($st.Any) {
        $miss = @()
        if (-not $st.Astr) { $miss += 'AstrBot' }
        if (-not $st.Model) { $miss += '记忆模型' }
        Set-Hero 'amber' $false '没完全上线' ('她本人还缺：' + ($miss -join '、') + '，点「让佳树上线」补上')
        Set-Power 'on'
        Set-Second 'stop'
    } else {
        Set-Hero 'off' $false '佳树在休息' '她现在不会回话，也不烧 token'
        Set-Power 'on'
        Set-Second ''
    }

    if ($null -ne $st) {
        if ($st.Astr) { Set-Chip $chipAstr 'ok' '在线' } else { Set-Chip $chipAstr 'off' '没开' }
        if ($st.Model) { Set-Chip $chipModel 'ok' '开着' } else { Set-Chip $chipModel 'off' '没开' }
        if ($st.QqOk) { Set-Chip $chipQq 'ok' '已连上' }
        elseif ($st.Online) { Set-Chip $chipQq 'warn' '收不到' }
        elseif ($st.BotQq) { Set-Chip $chipQq 'warn' '没登录' }
        elseif ($st.Luma) { Set-Chip $chipQq 'warn' '没开小号' }
        else { Set-Chip $chipQq 'off' '没开' }
        if (-not $mTitle.Text) {
            $ver = if ($st.BotVer) { "小号 QQ 版本 $($st.BotVer)。" } else { '' }
            $mDetail.Text = $ver + $DefaultBotHint
        }
    }
}

function Start-Poll {
    if ($script:Polling) { return }
    $script:Polling = $true
    Start-Work $PollBody @{} {
        param($r, $err)
        $script:Polling = $false
        if ($err -or $null -eq $r) { return }
        $script:BotState = $r
        if ($r.Counts -is [hashtable]) { $script:Counts = $r.Counts }
        $script:ChanceSaved = $r.Chance
        if ($null -ne $r.Chance -and -not $script:ChanceDirty -and -not $script:ChanceBusy) {
            $script:ChanceSyncing = $true
            $cTrack.Value = [Math]::Max(0, [Math]::Min(100, [int]$r.Chance))
            $script:ChanceSyncing = $false
        }
        Update-ChanceView
        if ($null -ne $r.GroupQuiet) { $script:GroupQuiet = $r.GroupQuiet }
        Update-QuietView
        $hSub.Text = '每 3 秒看一眼她 · 上次 ' + (Get-Date -Format 'HH:mm:ss')
        Update-BotView
        Update-PackInfo
    }
}

function Invoke-BotAction([string]$body, [string]$kind = 'start') {
    if ($script:BotBusy) { return }
    $script:BotBusy = 'checking'
    $script:BotBusyKind = $kind
    $script:Sync.Phase = ''
    $script:Sync.Detail = ''
    Show-BotMessage '' '' $Pal.Text
    Update-BotView
    Start-Work $body @{} {
        param($r, $err)
        $script:BotBusy = ''
        $script:Sync.Detail = ''
        if ($err -or $null -eq $r) {
            Show-BotMessage '出错了' ([string]$err) $Pal.RedText
        } else {
            $color = switch ($r.Tone) { 'green' { $Pal.GreenText } 'amber' { $Pal.AmberText } default { $Pal.RedText } }
            if ($r.Kind -eq 'stop' -and $r.Ok) { $color = $Pal.Sub }   # 好好下线了不算出错，不用红字
            Show-BotMessage $r.Title $r.Detail $color
        }
        Update-BotView
        Start-Poll
    }
}

# 下线前问一句：小号 QQ 不自动登录，下线再上线可能要兄长手动登 QQ
function Confirm-BotStop {
    $ans = [System.Windows.Forms.MessageBox]::Show($form,
        "让佳树下线？`r`n`r`n她本人、记忆模型、小号 QQ 都会关掉，她不再回话。`r`n小号 QQ 不自动登录，之后再上线可能要手动登一次 QQ。",
        '佳树控制台', [System.Windows.Forms.MessageBoxButtons]::OKCancel, [System.Windows.Forms.MessageBoxIcon]::Question,
        [System.Windows.Forms.MessageBoxDefaultButton]::Button2)
    return ($ans -eq [System.Windows.Forms.DialogResult]::OK)
}

$btnPower.Add_Click({
    if ($script:PowerMode -eq 'off') { if (Confirm-BotStop) { Invoke-BotAction $StopBody 'stop' } }
    elseif ($script:PowerMode -eq 'on') { Invoke-BotAction $StartBody 'start' }
})
$btnQq.Add_Click({
    if ($script:SecondAction -eq 'qq') { Invoke-BotAction $StartBody 'start' }
    elseif ($script:SecondAction -eq 'stop') { if (Confirm-BotStop) { Invoke-BotAction $StopBody 'stop' } }
})
$btnPersona.Add_Click({ Show-PersonaEditor })
$btnGallery.Add_Click({ Open-MemeManager })

# 「记忆星海」：后台生成网页，好了就用默认浏览器打开（每点一次都按最新的记忆重新画）
function Start-MemSea {
    if ($script:SeaBusy) { return }
    $script:SeaBusy = $true
    $btnSea.Text = '生成中…'
    $btnSea.Enabled = $false
    Start-Work $SeaBody @{} {
        param($r, $err)
        $script:SeaBusy = $false
        $btnSea.Text = '✦ 记忆星海'
        $btnSea.Enabled = $true
        if (-not $err -and $null -eq $r) { $err = '后台任务没有返回结果。' }
        if (-not $err) { $err = [string]$r.Err }
        $obj = $null
        if (-not $err) {
            try { $obj = ([string]$r.Text) | ConvertFrom-Json } catch { $err = "看不懂 memsea.py 的结果：$([string]$r.Text)" }
        }
        if (-not $err -and -not $obj.ok) { $err = [string]$obj.error }
        if ($err) {
            [void][System.Windows.Forms.MessageBox]::Show($form, "记忆星海没生成出来：`n$err", '记忆星海',
                [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
            return
        }
        try {
            Start-Process -FilePath ([string]$obj.path)
        } catch {
            [void][System.Windows.Forms.MessageBox]::Show($form, "生成好了，但没能打开浏览器，可以自己双击打开：`n$($obj.path)", '记忆星海',
                [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
        }
    }
}
$btnSea.Add_Click({ Start-MemSea })

$lnkPanel.Add_LinkClicked({ try { Start-Process 'http://127.0.0.1:6185' } catch { } })
$lnkLog.Add_LinkClicked({
    if (Test-Path $LogFile) { try { Start-Process notepad.exe -ArgumentList "`"$LogFile`"" } catch { } }
    else { Show-BotMessage '还没有日志' "日志文件 $LogFile 还不存在。" $Pal.Sub }
})

# =====================================================================
#  群聊主动接话概率
# =====================================================================
$script:ChanceSaved   = $null   # 配置文件里现在的值（0-100）
$script:ChanceDirty   = $false  # 滑块动过、还没保存
$script:ChanceBusy    = $false
$script:ChanceSyncing = $false  # 程序在设置滑块，不算用户改动
$script:ChanceNote    = $null   # 上一次保存的结果 @{ Text; Color }

function Update-ChanceView {
    $v = $cTrack.Value
    $saved = $script:ChanceSaved
    $cValue.Text = if ($null -eq $saved -and -not $script:ChanceDirty) { '…' } else { "$v%" }
    $cValue.ForeColor = if ($v -eq 0) { $Pal.Muted } else { $Pal.Text }
    $cTrack.Enabled = (-not $script:ChanceBusy) -and ($null -ne $saved)
    $btnChance.Enabled = (-not $script:ChanceBusy) -and $script:ChanceDirty -and ($null -ne $saved)
    $btnChance.Text = if ($script:ChanceBusy) { '保存中…' } else { '保存' }

    if ($script:ChanceBusy) {
        $cStatus.Text = "正在保存 $v%…"; $cStatus.ForeColor = $Pal.Sub
    } elseif ($null -eq $saved) {
        $cStatus.Text = '读不到聪明插话插件的配置（smart_chime_in）。'; $cStatus.ForeColor = $Pal.RedText
    } elseif ($script:ChanceDirty) {
        $cStatus.Text = "现在是 $saved%，改成 $v% 要点「保存」。"; $cStatus.ForeColor = $Pal.AmberText
    } elseif ($script:ChanceNote) {
        $cStatus.Text = $script:ChanceNote.Text; $cStatus.ForeColor = $script:ChanceNote.Color
    } elseif ($saved -eq 0) {
        $cStatus.Text = '已关闭聪明插话：没人 @ 她时不会主动插话。'; $cStatus.ForeColor = $Pal.Muted
    } else {
        $cStatus.Text = "正在生效：起步 $saved%，有人提问或聊到她关心的话题会更高；有冷却和每小时上限。"; $cStatus.ForeColor = $Pal.Muted
    }
    $tips.SetToolTip($cStatus, $cStatus.Text)
}

$tips.SetToolTip($cHint, '控制「聪明插话」插件：群里一波消息安静 8 秒后，按这个概率起步决定要不要插话（提问、相关话题、热聊会加概率）。被 @ 和戳一戳不受影响，照常回复。')
$tips.SetToolTip($cTrack, '拖动或用方向键微调，0% = 关闭聪明插话')

$cTrack.Add_ValueChanged({
    if ($script:ChanceSyncing) { return }
    $script:ChanceDirty = ($cTrack.Value -ne $script:ChanceSaved)
    $script:ChanceNote = $null
    Update-ChanceView
})

$btnChance.Add_Click({
    if ($script:ChanceBusy -or -not $script:ChanceDirty) { return }
    $script:ChanceBusy = $true
    $script:ChanceNote = $null
    Update-ChanceView
    Start-Work $ChanceBody @{ Chance = $cTrack.Value } {
        param($r, $err)
        $script:ChanceBusy = $false
        if ($err -or $null -eq $r) {
            $msg = if ($err) { [string]$err } else { '没有返回结果' }
            $script:ChanceNote = @{ Text = "保存失败：$msg"; Color = $Pal.RedText }
        } else {
            $script:ChanceSaved = $r.Pct
            $script:ChanceDirty = ($cTrack.Value -ne $r.Pct)
            $when = if ($r.Live) { '已经生效' } else { '机器人离线，下次启动时生效' }
            $script:ChanceNote = @{ Text = "已保存为 $($r.Pct)%，$when。"; Color = $Pal.GreenText }
        }
        Update-ChanceView
    }
})

# =====================================================================
#  群聊暂停（2026-11-17）：直接写 / 删 kaju_data\cache\gpu_busy\group_pause.json，机器人下一条群消息就看到
# =====================================================================
$script:GroupQuiet = $null
try { $script:GroupQuiet = Get-GroupQuiet } catch { }

function Update-QuietView {
    $q = $script:GroupQuiet
    if ($null -eq $q) {
        Set-Chip $qChip 'grey' '读不到'; $qStatus.Text = '读不到暂停状态。'; $btnPause.Enabled = $false; return
    }
    $btnPause.Enabled = $true
    if ($q.Paused) {
        Set-Chip $qChip 'warn' '群里暂停中'
        $when = if ($q.Since) { ([datetime]$q.Since).ToString('M-d HH:mm') + ' 起，' } else { '' }
        $extra = if ($q.Training) { "；训练也在跑（$($q.Training)）" } else { '' }
        $qStatus.Text = "$when$($q.What)。点「恢复群聊」她才会再在群里说话$extra。"
        $qStatus.ForeColor = $Pal.AmberText
        $btnPause.Text = '恢复群聊'; Set-ButtonKind $btnPause 'green'
    } elseif ($q.Training) {
        Set-Chip $qChip 'warn' '训练中不说话'
        $qStatus.Text = "训练脚本挂着（$($q.Training)），训练完自动恢复；想训练完也不说话就点「暂停群聊」。"
        $qStatus.ForeColor = $Pal.AmberText
        $btnPause.Text = '暂停群聊'; Set-ButtonKind $btnPause 'calm'
    } else {
        Set-Chip $qChip 'ok' '群里正常说话'
        $qStatus.Text = '想让她在群里先安静一会儿就点「暂停群聊」：被 @、插话、主动去群里说都停，私聊照常。'
        $qStatus.ForeColor = $Pal.Muted
        $btnPause.Text = '暂停群聊'; Set-ButtonKind $btnPause 'calm'
    }
    $tips.SetToolTip($qStatus, $qStatus.Text)
}

$btnPause.Add_Click({
    try {
        $on = -not ($script:GroupQuiet -and $script:GroupQuiet.Paused)
        $script:GroupQuiet = Set-GroupPause $on
    } catch {
        $qStatus.Text = "没改成：$($_.Exception.Message)"; $qStatus.ForeColor = $Pal.RedText; return
    }
    Update-QuietView
})
$tips.SetToolTip($qHint, '暂停期间她在群里一句都不说：被 @、聪明插话、刷完视频回群里汇报、私聊里让她去群里发消息，都会停。群聊记录照样记。机器人没开时也能改，下次启动照样生效。')
Update-QuietView

# =====================================================================
#  表情包：选图 / 拖图 / 上传
# =====================================================================
$script:Pending   = New-Object System.Collections.ArrayList
$script:Uploading = $false
$script:CatBusy   = $false

$catDescMap = @{}
try {
    $obj = Get-Content (Join-Path $PackDir 'memes_data.json') -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
    foreach ($p in $obj.PSObject.Properties) { $catDescMap[$p.Name] = [string]$p.Value }
} catch { }

$AllCats = '全部分类'
$script:PackTotal = 0
$catNames = @(& { $ErrorActionPreference = 'Stop'; Get-Categories })
foreach ($c in $catNames) { [void]$combo.Items.Add($c) }
$combo.SelectedIndex = [Math]::Max(0, $combo.Items.IndexOf('reply'))

$comboDraw = {
    param($s, $e)
    if ($e.Index -lt 0) { return }
    $name = [string]$s.Items[$e.Index]
    $isEdit = ($e.State -band [System.Windows.Forms.DrawItemState]::ComboBoxEdit) -ne 0
    $isSel  = ($e.State -band [System.Windows.Forms.DrawItemState]::Selected) -ne 0
    $bg = if ($isSel -and -not $isEdit) { $Pal.AccentSoft } else { $Pal.White }
    $brush = New-Object System.Drawing.SolidBrush($bg)
    $e.Graphics.FillRectangle($brush, $e.Bounds)
    $brush.Dispose()
    $pad = Px 8
    $r = New-Object System.Drawing.Rectangle(($e.Bounds.X + $pad), $e.Bounds.Y, ($e.Bounds.Width - 2 * $pad), $e.Bounds.Height)
    [System.Windows.Forms.TextRenderer]::DrawText($e.Graphics, $name, $s.Font, $r, $Pal.Text,
        [System.Windows.Forms.TextFormatFlags]'Left, VerticalCenter, SingleLine, NoPrefix, EndEllipsis')
    $n = if ($name -eq $AllCats) { $script:PackTotal } else { $script:Counts[$name] }
    if ($null -ne $n -and -not $isEdit) {
        [System.Windows.Forms.TextRenderer]::DrawText($e.Graphics, "$n 张", $s.Font, $r, $Pal.Muted,
            [System.Windows.Forms.TextFormatFlags]'Right, VerticalCenter, SingleLine')
    }
}
$combo.Add_DrawItem($comboDraw)

function Update-PackInfo {
    $total = 0
    foreach ($v in $script:Counts.Values) { $total += [int]$v }
    $script:PackTotal = $total
    Update-Hint
    $cat = [string]$combo.SelectedItem
    $desc = $catDescMap[$cat]
    $n = $script:Counts[$cat]
    $parts = @()
    if ($desc) { $parts += $desc }
    if ($null -ne $n) { $parts += "已有 $n 张" }
    $catDesc.Text = ($parts -join '  ·  ')
    $tips.SetToolTip($catDesc, $catDesc.Text)
    $combo.Invalidate()
}

function Set-EmptyState([string]$glyphText, [string]$kind, [string]$big, [string]$small) {
    switch ($kind) {
        'ok'   { $glyph.BaseColor = $Pal.GreenSoft; $glyph.ForeColor = $Pal.GreenText }
        'warn' { $glyph.BaseColor = $Pal.AmberSoft; $glyph.ForeColor = $Pal.AmberText }
        default { $glyph.BaseColor = $Pal.AccentSoft; $glyph.ForeColor = $Pal.Accent }
    }
    $glyph.Text = $glyphText
    $eBig.Text = $big
    $eSmall.Text = $small
    $tips.SetToolTip($eSmall, $small)
}

function Set-DropHot([bool]$on) {
    $fill = if ($on) { $Pal.DropHot } else { $Pal.DropFill }
    $drop.Fill = $fill
    $drop.Border = if ($on) { $Pal.Accent } else { $Pal.DropLine }
    $empty.Fill = $fill
    $lv.BackColor = $fill
}

function Update-MemeView {
    $n = $script:Pending.Count
    $has = $n -gt 0
    $lv.Visible = $has
    $empty.Visible = -not $has
    $cat = [string]$combo.SelectedItem
    if ($script:Uploading) { $btnAdd.Text = '上传中…' }
    elseif ($has) { $btnAdd.Text = "添加 $n 张到「$cat」" }
    else { $btnAdd.Text = '添加到表情包' }
    $idle = -not ($script:Uploading -or $script:CatBusy)
    $btnAdd.Enabled  = $idle
    $btnPick.Enabled = -not $script:Uploading
    $btnClear.Enabled = -not $script:Uploading
    $btnNewCat.Enabled  = $idle
    $btnEditCat.Enabled = $idle -and ($null -ne $combo.SelectedItem)
    $combo.Enabled = $idle
}

function Add-FilesTo([string[]]$paths) {
    if ($script:Uploading) { return }
    foreach ($p in $paths) {
        if (-not $p) { continue }
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { continue }
        $ext = [IO.Path]::GetExtension($p).ToLowerInvariant()
        if ($ext -notin $ImageExts) { continue }
        if ($script:Pending -contains $p) { continue }
        [void]$script:Pending.Add($p)
        if (-not $images.Images.ContainsKey($p)) {
            try {
                $bmp = [JiashuUi.Gfx]::Thumb($p, $thumbSize, $Pal.White, $Pal.Muted, (Fnt 10 'Bold'))
                $images.Images.Add($p, $bmp)
            } catch { }
        }
        $item = New-Object System.Windows.Forms.ListViewItem([IO.Path]::GetFileName($p))
        $item.ImageKey = $p
        $item.Tag = $p
        $item.ToolTipText = $p
        [void]$lv.Items.Add($item)
    }
    $eCount.Text = "待添加 $($script:Pending.Count) 张。"
    Update-MemeView
}

function Remove-SelectedFiles {
    if ($script:Uploading) { return }
    foreach ($it in @($lv.SelectedItems)) {
        $script:Pending.Remove([string]$it.Tag)
        $lv.Items.Remove($it)
    }
    $eCount.Text = "待添加 $($script:Pending.Count) 张。"
    if ($script:Pending.Count -eq 0) { Reset-EmptyState }
    Update-MemeView
}

function Reset-EmptyState {
    Set-EmptyState '+' 'accent' '把图片拖到这里' '或者点这里选择图片（可以多选）'
}

function Open-Picker {
    if ($script:Uploading) { return }
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Filter = '图片 (*.png;*.jpg;*.jpeg;*.gif;*.webp)|*.png;*.jpg;*.jpeg;*.gif;*.webp'
    $dlg.Multiselect = $true
    if ($dlg.ShowDialog($form) -eq 'OK') { Add-FilesTo $dlg.FileNames }
}

$btnPick.Add_Click({ Open-Picker })
foreach ($c in @($empty, $glyph, $eBig, $eSmall)) { $c.Add_Click({ Open-Picker }) }

$btnClear.Add_Click({
    if ($script:Uploading) { return }
    $script:Pending.Clear()
    $lv.Items.Clear()
    $images.Images.Clear()
    $eCount.Text = '已清空。'
    Reset-EmptyState
    Update-MemeView
})

$miRemove.Add_Click({ Remove-SelectedFiles })
$lv.Add_KeyDown({ param($s, $e) if ($e.KeyCode -eq 'Delete') { Remove-SelectedFiles } })
$lvMenu.Add_Opening({ param($s, $e) if ($lv.SelectedItems.Count -eq 0 -or $script:Uploading) { $e.Cancel = $true } })

$dragEnter = {
    param($s, $e)
    if (-not $script:Uploading -and $e.Data.GetDataPresent([System.Windows.Forms.DataFormats]::FileDrop)) {
        $e.Effect = [System.Windows.Forms.DragDropEffects]::Copy
        Set-DropHot $true
    } else {
        $e.Effect = [System.Windows.Forms.DragDropEffects]::None
    }
}
$dragDrop = {
    param($s, $e)
    Set-DropHot $false
    $paths = $e.Data.GetData([System.Windows.Forms.DataFormats]::FileDrop)
    Add-FilesTo $paths
}
$dragLeave = { Set-DropHot $false }
foreach ($c in @($form, $addPane, $drop, $lv, $empty, $glyph, $eBig, $eSmall)) {
    $c.Add_DragEnter($dragEnter)
    $c.Add_DragDrop($dragDrop)
    $c.Add_DragLeave($dragLeave)
}

$combo.Add_SelectedIndexChanged({ Update-PackInfo; Update-MemeView })

$btnAdd.Add_Click({
    if ($script:Uploading) { return }
    if ($script:Pending.Count -eq 0) { $eCount.Text = '还没选图片。'; return }
    $cat = [string]$combo.SelectedItem
    $upList = [string[]]@($script:Pending)
    $script:Uploading = $true
    $script:Sync.Progress = ''
    $combo.Enabled = $false
    Update-MemeView
    Start-Work $UploadBody @{ UpFiles = $upList; UpCat = $cat } {
        param($r, $err)
        $script:Uploading = $false
        $combo.Enabled = $true
        $script:Pending.Clear()
        $lv.Items.Clear()
        $images.Images.Clear()
        if ($err -or $null -eq $r) {
            Set-EmptyState '!' 'warn' '上传出错了' ([string]$err)
            $eCount.Text = '上传出错。'
        } else {
            $fail = @($r.Fail)
            $lines = @()
            if ($fail.Count -gt 0) { $lines += '失败：'; $lines += ($fail | ForEach-Object { "· $_" }) }
            $lines += "分类：$($r.Cat)"
            $big = "完成：成功 $($r.Ok) 张，重复跳过 $($r.Dup) 张，失败 $($fail.Count) 张。"
            if ($fail.Count -gt 0) { Set-EmptyState '!' 'warn' $big ($lines -join "`r`n") }
            else { Set-EmptyState ([string][char]0x2713) 'ok' $big (($lines -join "`r`n") + "`r`n继续拖图片进来就能接着加") }
            $eCount.Text = '完成，可以继续添加。'
        }
        Update-MemeView
        Start-Poll
    }
})

# =====================================================================
#  表情包：分类小窗口 + 打开「表情包管理」
# =====================================================================

function Update-Hint {
    $eHint.Text = '拖进来 → 选分类 → 添加。支持 png / jpg / gif / webp。'
}

function Set-SegStyle($pill, [bool]$on) {
    if ($on) {
        $pill.BaseColor = $Pal.White; $pill.HoverColor = $Pal.White; $pill.PressColor = $Pal.White
        $pill.ForeColor = $Pal.Text;  $pill.BorderColor = $Pal.Line
    } else {
        $pill.BaseColor = $Pal.GreySoft; $pill.HoverColor = (Rgb 240 229 226); $pill.PressColor = (Rgb 234 220 217)
        $pill.ForeColor = $Pal.GreyText; $pill.BorderColor = [System.Drawing.Color]::Empty
    }
}


function Test-BotOnlineFor([string]$what) {
    if ($script:BotState -and $script:BotState.Astr) { return $true }
    [void][System.Windows.Forms.MessageBox]::Show($form,
        "机器人离线时不能$what。`r`n这要通过 AstrBot 来做，它记着的表情索引才会一起更新。`r`n请先点上面的「让佳树上线」。",
        '佳树控制台', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
    return $false
}

# 分类名不能带路径符号，也不能和 Windows 文件名规则冲突
function Test-CategoryName([string]$name) {
    if (-not $name) { return '请填写分类名。' }
    if ($name -ne $name.Trim()) { return '分类名前后不能有空格。' }
    if ($name -in '.', '..') { return '分类名不能是 . 或 ..' }
    if ($name -match '[\\/:*?"<>|]') { return '分类名不能包含 \ / : * ? " < > | 这些符号。' }
    if ($name.Length -gt 40) { return '分类名太长了（最多 40 个字）。' }
    return ''
}


# 「新建分类 / 改描述」小窗口。$cat 为空 = 新建；否则修改这个分类的描述
function Show-CategoryDialog([string]$cat) {
    $isNew = -not $cat
    $existing = @($combo.Items | ForEach-Object { [string]$_ })
    $oldDesc = if ($isNew) { '' } else { [string]$catDescMap[$cat] }

    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = if ($isNew) { '新建分类' } else { '修改分类描述' }
    $dlg.AutoScaleMode = 'None'
    $dlg.FormBorderStyle = 'FixedDialog'
    $dlg.MaximizeBox = $false
    $dlg.MinimizeBox = $false
    $dlg.ShowInTaskbar = $false
    $dlg.StartPosition = 'CenterParent'
    $dlg.BackColor = $Pal.Card
    $dlg.Font = Fnt 9
    $dlg.KeyPreview = $true
    if ($form.Icon) { $dlg.Icon = $form.Icon }

    $title = if ($isNew) { '新建一个表情分类' } else { "修改「$cat」的描述" }
    $n = $script:Counts[$cat]
    $sub = if ($isNew) { '建好后会出现在分类下拉框里，拖图进去就能用。' } elseif ($null -ne $n) { "这个分类里有 $n 张图。" } else { '' }
    $dTitle = New-Label $title 24 18 372 26 (Fnt 11 'Bold') $Pal.Text
    $dTitle.AutoEllipsis = $true
    $dSub = New-Label $sub 24 44 372 20 (Fnt 9) $Pal.Muted
    $ctrls = @($dTitle, $dSub)

    $y = 76
    $dName = $null
    if ($isNew) {
        $ctrls += New-Label '分类名（会作为文件夹名，比如：猫猫、无语）' 24 $y 372 20 (Fnt 9) $Pal.Sub
        $dName = New-Object System.Windows.Forms.TextBox
        $dName.Location = Pt 24 ($y + 22); $dName.Width = Px 372; $dName.Font = Fnt 10; $dName.MaxLength = 40
        $ctrls += $dName
        $y += 58
    }
    $ctrls += New-Label '什么时候用这类表情（写给佳树看的说明）' 24 $y 372 20 (Fnt 9) $Pal.Sub
    $dDescT = New-Object System.Windows.Forms.TextBox
    $dDescT.Location = Pt 24 ($y + 22); $dDescT.Size = Sz 372 64; $dDescT.Font = Fnt 10
    $dDescT.Multiline = $true; $dDescT.WordWrap = $true; $dDescT.AcceptsReturn = $false
    $dDescT.ScrollBars = 'Vertical'; $dDescT.MaxLength = 200
    $dDescT.Text = $oldDesc
    $ctrls += $dDescT
    $y += 92
    $dErr = New-Label '' 24 $y 372 38 (Fnt 9) $Pal.RedText 'TopLeft'
    $dCancel = New-Button '取消' 206 ($y + 44) 90 38 'ghost' 9.5
    $dOk     = New-Button $(if ($isNew) { '新建' } else { '保存' }) 306 ($y + 44) 90 38 'primary' 9.5
    $ctrls += @($dErr, $dCancel, $dOk)
    $dlg.ClientSize = Sz 420 ($y + 100)
    $dlg.Controls.AddRange($ctrls)

    $script:CatChoice = $null
    $accept = {
        $name = if ($isNew) { $dName.Text } else { $cat }
        if ($isNew) {
            $bad = Test-CategoryName $name
            if ($bad) { $dErr.Text = $bad; return }
            if ($existing -contains $name) { $dErr.Text = "已经有「$name」这个分类了，在下拉框里选它，再点「改描述」就行。"; return }
        }
        $desc = ($dDescT.Text -replace '\s*[\r\n]+\s*', ' ').Trim()
        if (-not $desc) { $dErr.Text = '写一句说明吧，佳树靠它判断什么时候发这类表情。'; return }
        if (-not $isNew -and $desc -eq $oldDesc.Trim()) { $dlg.Close(); return }
        $script:CatChoice = @{ Name = $name; Desc = $desc; Create = $isNew }
        $dlg.Close()
    }
    $dOk.Add_Click($accept)
    $dCancel.Add_Click({ $dlg.Close() })
    $dlg.Add_KeyDown({ param($s, $e) if ($e.KeyCode -eq 'Escape') { $dlg.Close() } elseif ($e.KeyCode -eq 'Enter') { & $accept; $e.SuppressKeyPress = $true } })
    $dlg.Add_Shown({ if ($dName) { $dName.Focus() } else { $dDescT.Focus(); $dDescT.SelectionStart = $dDescT.TextLength } })

    [void]$dlg.ShowDialog($form)
    $dlg.Dispose()
    return $script:CatChoice
}

function Start-CategoryEdit([string]$cat) {
    if ($script:Uploading -or $script:CatBusy) { return }
    if (-not (Test-BotOnlineFor $(if ($cat) { '修改分类描述' } else { '新建分类' }))) { return }
    $choice = Show-CategoryDialog $cat
    if (-not $choice) { return }

    $script:CatBusy = $true
    $script:CatJob = $choice
    $eCount.Text = if ($choice.Create) { "正在新建「$($choice.Name)」…" } else { "正在保存「$($choice.Name)」的描述…" }
    Update-MemeView
    Start-Work $CatBody @{ CatName = $choice.Name; CatDesc = $choice.Desc; CatCreate = $choice.Create } {
        param($r, $err)
        $script:CatBusy = $false
        $c = $script:CatJob
        if ($err -or $null -eq $r -or -not $r.Ok) {
            $why = if ($err) { [string]$err } elseif ($r) { $r.Message } else { '没有返回结果' }
            $what = if ($c.Create) { "新建分类「$($c.Name)」" } else { "修改「$($c.Name)」的描述" }
            $eCount.Text = '没保存成功。'
            [void][System.Windows.Forms.MessageBox]::Show($form, "$what 失败：`r`n$why", '佳树控制台',
                [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
        } else {
            $catDescMap[$r.Name] = $r.Desc
            if ($r.Create) {
                if (-not $combo.Items.Contains($r.Name)) { [void]$combo.Items.Add($r.Name) }
                if ($null -eq $script:Counts[$r.Name]) { $script:Counts[$r.Name] = 0 }
                $combo.SelectedItem = $r.Name
                $eCount.Text = "已新建「$($r.Name)」，可以往里加图了。"
            } else {
                $eCount.Text = "已更新「$($r.Name)」的描述。"
            }
            Update-PackInfo
        }
        Update-MemeView
    }
}

function Invoke-CategoryEdit([string]$cat) {
    try { Start-CategoryEdit $cat }
    catch {
        $script:CatBusy = $false; Update-MemeView
        [void][System.Windows.Forms.MessageBox]::Show($form, "出错了：$($_.Exception.Message)`r`n（第 $($_.InvocationInfo.ScriptLineNumber) 行）", '佳树控制台',
            [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
    }
}
$btnNewCat.Add_Click({ Invoke-CategoryEdit '' })
$btnEditCat.Add_Click({ Invoke-CategoryEdit ([string]$combo.SelectedItem) })
$tips.SetToolTip($btnNewCat, '新建一个表情分类，要写一句什么时候用')
$tips.SetToolTip($btnEditCat, '修改当前分类的说明，佳树靠它判断什么时候发这类表情')


# 管理窗口关掉后：分类可能新建 / 改名 / 删除了，重新读一遍「添加」用的分类和描述
function Update-AddCats {
    $keep = [string]$combo.SelectedItem
    $catDescMap.Clear()
    try {
        $obj = Get-Content (Join-Path $PackDir 'memes_data.json') -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
        foreach ($p in $obj.PSObject.Properties) { $catDescMap[$p.Name] = [string]$p.Value }
    } catch { }
    $combo.Items.Clear()
    foreach ($c in @(& { $ErrorActionPreference = 'Stop'; Get-Categories })) { [void]$combo.Items.Add($c) }
    $i = $combo.Items.IndexOf($keep)
    if ($i -lt 0) { $i = [Math]::Max(0, $combo.Items.IndexOf('reply')) }
    if ($combo.Items.Count) { $combo.SelectedIndex = $i }
    Update-PackInfo
    Update-MemeView
}

function Open-MemeManager {
    try { [void](Show-MemeManager) }
    catch {
        [void][System.Windows.Forms.MessageBox]::Show($form, "表情包管理出错了：$($_.Exception.Message)`r`n（第 $($_.InvocationInfo.ScriptLineNumber) 行）", '佳树控制台',
            [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
    }
    try { Update-AddCats } catch { }
    Start-Poll
}
$btnManage.Add_Click({ Open-MemeManager })
$tips.SetToolTip($btnManage, '看全部表情包、删除、改分类（一张图可以在好几个分类里）、回收站')

# =====================================================================
#  定时器 + 启动
# =====================================================================
$workTimer = New-Object System.Windows.Forms.Timer
$workTimer.Interval = 120
$workTimer.Add_Tick({
    Complete-Jobs
    # 刚打开的头 3 秒里如果被系统最小化了，自动还原
    if ($script:ShownAt -and ((Get-Date) - $script:ShownAt).TotalSeconds -lt 3 -and $form.WindowState -eq 'Minimized') {
        $form.WindowState = 'Normal'
        $form.Activate()
    }
    if ($script:BotBusy -and $script:Sync.Phase -and
        ($script:BotBusy -ne $script:Sync.Phase -or $bSub.Text -ne [string]$script:Sync.Detail)) {
        $script:BotBusy = $script:Sync.Phase
        Update-BotView
    }
    if ($script:Uploading -and $script:Sync.Progress -and $eCount.Text -ne $script:Sync.Progress) {
        $eCount.Text = $script:Sync.Progress
    }
    # 窗口开着时又把图片拖到了桌面快捷方式上
    if (-not $script:Uploading -and [IO.File]::Exists($InboxFile)) {
        try {
            $more = [IO.File]::ReadAllLines($InboxFile, [Text.Encoding]::UTF8)
            [IO.File]::Delete($InboxFile)
            Add-FilesTo $more
        } catch { }
    }
})

$pollTimer = New-Object System.Windows.Forms.Timer
$pollTimer.Interval = 3000
$pollTimer.Add_Tick({ Start-Poll })

$script:ShownAt = $null
$form.Add_Shown({
    $script:ShownAt = Get-Date
    $workTimer.Start()
    $pollTimer.Start()
    Start-Poll
    if ($form.WindowState -eq 'Minimized') { $form.WindowState = 'Normal' }
    $form.Activate()
})
$form.Add_FormClosing({
    $workTimer.Stop()
    $pollTimer.Stop()
})

Reset-EmptyState
Update-Hint
Update-BotView
Update-PackInfo
Update-ChanceView
if ([IO.File]::Exists($InboxFile)) { try { [IO.File]::Delete($InboxFile) } catch { } }
$startFiles = @(@($Files) + @($DroppedFiles) | Where-Object { $_ })
if ($startFiles.Count -gt 0) { Add-FilesTo $startFiles }
Update-MemeView

[void]$form.ShowDialog()

# 窗口关了，但机器人还在启动 / 停止、或者图片还在上传时，等它在后台做完再退出
foreach ($j in @($script:Jobs)) {
    try { [void]$j.PS.EndInvoke($j.Handle) } catch { }
    try { $j.PS.Dispose() } catch { }
}
try { $script:Pool.Close(); $script:Pool.Dispose() } catch { }
try { $script:Mutex.ReleaseMutex() } catch { }
