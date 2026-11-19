# 佳树控制台 ·「人格微调」窗口（由 bot-panel.ps1 加载，不单独运行）
#
# 能改佳树人格的全部四样东西（存在 AstrBot 数据库 personas 表，persona_id = default）：
#   人设正文   system_prompt，每次回复前都会完整给她看；左边按行列出来，点一下跳到那一行
#   示例对话   begin_dialogs，放在每次聊天最前面的示范对话（兄长大人说 / 佳树回）
#   工具权限   tools，她能调用哪些工具（null = 全部，包括以后新装的）
#   出错回复   custom_error_message，模型请求彻底失败时直接发出去的话
# 再加一样不在数据库里的（2026-11-07 起人设只留两句身份，她是谁的细节放这里）：
#   关于自己   self_facts，kaju_life 的 self_facts.json，每轮按对方刚说的话想起最相关的几条；直接改文件，下一轮就用新的
# 还能看历史版本：每次保存前，tools\persona.py 会把当时的版本备份到 D:\JiashuBot\_backup\persona\。
# 读写都交给 tools\persona.py：机器人在线走 AstrBot 接口（马上生效），离线直接改数据库（下次启动生效）。

$PersonaPy   = 'D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\venv\Scripts\python.exe'
$PersonaTool = 'D:\JiashuBot\bot_setup\tools\persona.py'
$PersonaBackupDir = 'D:\JiashuBot\_backup\persona'

# 后台线程里跑 persona.py。不抛异常：总是返回 { PeId, Text, Err }，界面线程靠 PeId 找回调
$PersonaBody = @'
$ErrorActionPreference = 'Stop'
$text = ''; $fail = ''
$out = [IO.Path]::Combine([IO.Path]::GetTempPath(), 'jiashu-persona-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = '__PY__'
    $quoted = @(@('-I', '__TOOL__') + @($PyArgs) + @('--out', $out) | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' })
    $psi.Arguments = $quoted -join ' '
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardOutput = $true
    $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    $p = [System.Diagnostics.Process]::Start($psi)
    $errTask = $p.StandardError.ReadToEndAsync()
    [void]$p.StandardOutput.ReadToEndAsync()
    if (-not $p.WaitForExit(90000)) {
        try { $p.Kill() } catch { }
        $fail = '读写人格超时（90 秒），机器人可能卡住了。'
    } elseif ([IO.File]::Exists($out)) {
        $text = [IO.File]::ReadAllText($out, [Text.Encoding]::UTF8)
    } else {
        $fail = 'persona.py 没有输出结果：' + $errTask.Result
    }
} catch {
    $fail = $_.Exception.Message
} finally {
    try { if ([IO.File]::Exists($out)) { [IO.File]::Delete($out) } } catch { }
}
[pscustomobject]@{ PeId = $PeId; Text = $text; Err = $fail }
'@
$PersonaBody = $PersonaBody.Replace('__PY__', $PersonaPy).Replace('__TOOL__', $PersonaTool)

$script:PE = @{ Cbs = @{}; Seq = 0 }

function ConvertTo-Crlf([string]$s) { if ($null -eq $s) { return '' }; return ($s -replace "`r`n", "`n") -replace "`n", "`r`n" }
function ConvertTo-Lf([string]$s) { if ($null -eq $s) { return '' }; return $s -replace "`r`n", "`n" }
# 「关于自己」一条在界面里记成 "分类<TAB>这一条"，好比较；空白和 persona.py 一样收成一个空格
function ConvertTo-OneLine([string]$s) { if ($null -eq $s) { return '' }; return ($s -replace '\s+', ' ').Trim() }
function ConvertTo-FactKey($kind, $fact) { return (ConvertTo-OneLine ([string]$kind)) + "`t" + (ConvertTo-OneLine ([string]$fact)) }
function ConvertFrom-FactKey([string]$key) {
    $i = $key.IndexOf("`t")
    return [ordered]@{ fact = $key.Substring($i + 1); kind = $key.Substring(0, $i) }
}

# ---------- 后台调用 persona.py ----------
# 回调 $done 收到 (结果对象, 错误文字)；窗口关掉后才回来的结果直接丢掉
$PeDone = {
    param($res, $err)
    $pe = $script:PE
    if (-not $res -or -not $pe.Cbs.ContainsKey([int]$res.PeId)) { return }
    $id = [int]$res.PeId
    $cb = $pe.Cbs[$id]
    $pe.Cbs.Remove($id)
    $pe.Busy--
    if (-not $pe.Form -or $pe.Form.IsDisposed) { return }
    $obj = $null
    if (-not $err) { $err = [string]$res.Err }
    if (-not $err) {
        try { $obj = ([string]$res.Text) | ConvertFrom-Json } catch { $err = "看不懂 persona.py 的结果：$([string]$res.Text)" }
    }
    if (-not $err -and -not $obj.ok) { $err = [string]$obj.error }
    try { & $cb $obj $err } catch { Set-PeStatus "出错了：$($_.Exception.Message)" 'bad' }
    Update-PeButtons
}

function Invoke-PersonaTool([string[]]$pyArgs, [scriptblock]$done) {
    $pe = $script:PE
    $pe.Seq++
    $id = [int]$pe.Seq
    $pe.Cbs[$id] = $done
    $pe.Busy++
    Update-PeButtons
    Start-Work $PersonaBody @{ PyArgs = $pyArgs; PeId = $id } $PeDone
}

# ---------- 状态 ----------
function ConvertTo-PeState($p) {
    $tools = $null
    if ($null -ne $p.tools) { $tools = @(@($p.tools) | ForEach-Object { [string]$_ } | Sort-Object -Unique) }
    $facts = $null   # 11-07 之前的备份里没有「关于自己」
    if ($null -ne $p.self_facts) { $facts = @(@($p.self_facts) | Where-Object { $null -ne $_ } | ForEach-Object { ConvertTo-FactKey $_.kind $_.fact }) }
    return @{
        system_prompt        = (ConvertTo-Lf ([string]$p.system_prompt))
        begin_dialogs        = @(@($p.begin_dialogs) | Where-Object { $null -ne $_ } | ForEach-Object { ConvertTo-Lf ([string]$_) })
        tools                = $tools
        custom_error_message = ([string]$p.custom_error_message).Trim()
        self_facts           = $facts
    }
}

function Get-PeState {
    $d = New-Object System.Collections.ArrayList
    foreach ($pair in $script:PE.Dialogs) { [void]$d.Add((ConvertTo-Lf $pair.U)); [void]$d.Add((ConvertTo-Lf $pair.B)) }
    $tools = $null
    if ($script:PE.RbPick.Checked) {
        $tools = @(@(for ($i = 0; $i -lt $script:PE.ToolList.Items.Count; $i++) {
            if ($script:PE.ToolList.GetItemChecked($i)) { [string]$script:PE.ToolNames[$i] }
        }) | Sort-Object -Unique)
    }
    return @{
        system_prompt        = (ConvertTo-Lf $script:PE.Prompt.Text)
        begin_dialogs        = @($d.ToArray())
        tools                = $tools
        custom_error_message = $script:PE.ErrBox.Text.Trim()
        self_facts           = @($script:PE.Facts | ForEach-Object { ConvertTo-FactKey $_.K $_.F })
    }
}

function Test-PeSame($a, $b) {
    if ($null -eq $a -and $null -eq $b) { return $true }
    if ($null -eq $a -or $null -eq $b) { return $false }
    if ($a -is [array] -or $b -is [array]) {
        $a = @($a); $b = @($b)
        if ($a.Count -ne $b.Count) { return $false }
        for ($i = 0; $i -lt $a.Count; $i++) { if ([string]$a[$i] -cne [string]$b[$i]) { return $false } }
        return $true
    }
    return ([string]$a -ceq [string]$b)
}

function Get-PeChanges {
    if (-not $script:PE.Base) { return @() }
    $now = Get-PeState
    $changed = @()
    foreach ($k in @('system_prompt', 'begin_dialogs', 'tools', 'custom_error_message', 'self_facts')) {
        if (-not (Test-PeSame $now[$k] $script:PE.Base[$k])) { $changed += $k }
    }
    return $changed
}

$PeFieldNames = @{ system_prompt = '人设正文'; begin_dialogs = '示例对话'; tools = '工具权限'; custom_error_message = '出错回复'; self_facts = '关于自己' }

function Set-PeStatus([string]$text, [string]$kind = 'info') {
    $script:PE.Status.Text = $text
    switch ($kind) {
        'ok'   { $script:PE.Status.ForeColor = $Pal.GreenText }
        'bad'  { $script:PE.Status.ForeColor = $Pal.RedText }
        'warn' { $script:PE.Status.ForeColor = $Pal.AmberText }
        default { $script:PE.Status.ForeColor = $Pal.Sub }
    }
}

function Update-PeButtons {
    $pe = $script:PE
    if (-not $pe.Form -or $pe.Form.IsDisposed) { return }
    $changes = @(Get-PeChanges)
    $pe.Dirty = ($changes.Count -gt 0)
    $idle = ($pe.Busy -le 0) -and $pe.Base
    $pe.BtnSave.Enabled = $idle -and $pe.Dirty
    $pe.BtnRevert.Enabled = $idle -and $pe.Dirty
    $pe.BtnReload.Enabled = ($pe.Busy -le 0)
    $pe.BtnLoadHist.Enabled = $idle -and ($null -ne $pe.HistPersona)
    foreach ($k in $pe.TabKeys) {
        $label = $pe.TabLabels[$k]
        $field = $pe.TabField[$k]
        if ($field -and ($changes -contains $field)) { $label = "$label •" }
        if ($pe.Tabs[$k].Text -ne $label) { $pe.Tabs[$k].Text = $label }
    }
    $pe.Form.Text = if ($pe.Dirty) { '人格微调 · 有未保存的修改' } else { '人格微调' }
    # 人设正文的字数
    $t = $pe.Prompt.Text
    $lines = @(($t -split "`r`n") | Where-Object { $_.Trim() }).Count
    $pe.PromptInfo.Text = "$((ConvertTo-Lf $t).Length) 字 · $lines 行"
    $pe.DlgInfo.Text = if ($pe.Dialogs.Count) { "共 $($pe.Dialogs.Count) 组示范对话" } else { '现在没有示范对话（11-07 起有意清空）' }
    $kinds = @($pe.Facts | ForEach-Object { ConvertTo-OneLine $_.K } | Where-Object { $_ } | Sort-Object -Unique).Count
    $pe.FactInfo.Text = "共 $($pe.Facts.Count) 条 · $kinds 个分类"
}

# ---------- 人设正文：按行列出来 ----------
function Update-PeSections {
    $pe = $script:PE
    $text = $pe.Prompt.Text
    $sel = $pe.SecList.SelectedIndex
    $wasSyncing = $pe.Syncing
    $pe.Syncing = $true   # 重建列表时恢复选中行，别让它把光标跳过去
    $pe.Sections = New-Object System.Collections.ArrayList
    $pe.SecList.BeginUpdate()
    $pe.SecList.Items.Clear()
    $pos = 0; $n = 0
    foreach ($line in ($text -split "`r`n")) {
        $n++
        if ($line.Trim()) {
            $short = $line.Trim()
            if ($short.Length -gt 22) { $short = $short.Substring(0, 22) + '…' }
            [void]$pe.Sections.Add(@{ Start = $pos; Length = $line.Length })
            [void]$pe.SecList.Items.Add(("{0,2}  {1}" -f $n, $short))
        }
        $pos += $line.Length + 2
    }
    if ($sel -ge 0 -and $sel -lt $pe.SecList.Items.Count) { $pe.SecList.SelectedIndex = $sel }
    $pe.SecList.EndUpdate()
    $pe.Syncing = $wasSyncing
}

function Select-PeSection {
    $pe = $script:PE
    $i = $pe.SecList.SelectedIndex
    if ($pe.Syncing -or $i -lt 0 -or $i -ge $pe.Sections.Count) { return }
    $s = $pe.Sections[$i]
    $pe.Prompt.Focus() | Out-Null
    $pe.Prompt.Select($s.Start, $s.Length)
    $pe.Prompt.ScrollToCaret()
}

function Find-PeNext {
    $pe = $script:PE
    $q = $pe.FindBox.Text
    if (-not $q) { return }
    $t = $pe.Prompt.Text
    $from = $pe.Prompt.SelectionStart + [Math]::Max(1, $pe.Prompt.SelectionLength)
    if ($from -gt $t.Length) { $from = 0 }
    $i = $t.IndexOf($q, $from, [StringComparison]::OrdinalIgnoreCase)
    if ($i -lt 0) { $i = $t.IndexOf($q, 0, [StringComparison]::OrdinalIgnoreCase) }
    if ($i -lt 0) { Set-PeStatus "人设正文里没有「$q」。" 'warn'; return }
    $pe.Prompt.Focus() | Out-Null
    $pe.Prompt.Select($i, $q.Length)
    $pe.Prompt.ScrollToCaret()
    Set-PeStatus ''
}

# ---------- 示例对话 ----------
function Get-PeDialogLabel($pair, [int]$i) {
    $u = ($pair.U -replace "\s+", ' ').Trim()
    $b = ($pair.B -replace "\s+", ' ').Trim()
    if (-not $u) { $u = '（空）' }
    if (-not $b) { $b = '（空）' }
    if ($u.Length -gt 14) { $u = $u.Substring(0, 14) + '…' }
    if ($b.Length -gt 16) { $b = $b.Substring(0, 16) + '…' }
    return ("{0,2}. {1}  →  {2}" -f ($i + 1), $u, $b)
}

function Update-PeDialogList([int]$select = -2) {
    $pe = $script:PE
    if ($select -eq -2) { $select = $pe.DlgList.SelectedIndex }
    $pe.Syncing = $true
    $pe.DlgList.BeginUpdate()
    $pe.DlgList.Items.Clear()
    for ($i = 0; $i -lt $pe.Dialogs.Count; $i++) { [void]$pe.DlgList.Items.Add((Get-PeDialogLabel $pe.Dialogs[$i] $i)) }
    if ($select -ge $pe.Dialogs.Count) { $select = $pe.Dialogs.Count - 1 }
    $pe.DlgList.SelectedIndex = $select
    $pe.DlgList.EndUpdate()
    $pe.Syncing = $false
    Show-PeDialog
}

function Show-PeDialog {
    $pe = $script:PE
    $i = $pe.DlgList.SelectedIndex
    $pe.Syncing = $true
    $has = ($i -ge 0 -and $i -lt $pe.Dialogs.Count)
    $pe.DlgUser.Enabled = $has; $pe.DlgBot.Enabled = $has
    $pe.BtnDlgDel.Enabled = $has
    $pe.BtnDlgUp.Enabled = $has -and $i -gt 0
    $pe.BtnDlgDown.Enabled = $has -and $i -lt $pe.Dialogs.Count - 1
    if ($has) {
        $pe.DlgUser.Text = ConvertTo-Crlf $pe.Dialogs[$i].U
        $pe.DlgBot.Text = ConvertTo-Crlf $pe.Dialogs[$i].B
    } else {
        $pe.DlgUser.Text = ''; $pe.DlgBot.Text = ''
    }
    $pe.Syncing = $false
}

function Save-PeDialogEdit {
    $pe = $script:PE
    if ($pe.Syncing) { return }
    $i = $pe.DlgList.SelectedIndex
    if ($i -lt 0 -or $i -ge $pe.Dialogs.Count) { return }
    $pe.Dialogs[$i].U = $pe.DlgUser.Text
    $pe.Dialogs[$i].B = $pe.DlgBot.Text
    $pe.Syncing = $true
    $pe.DlgList.Items[$i] = Get-PeDialogLabel $pe.Dialogs[$i] $i
    $pe.Syncing = $false
    $pe.Touched = $true
}

function Move-PeDialog([int]$delta) {
    $pe = $script:PE
    $i = $pe.DlgList.SelectedIndex
    $j = $i + $delta
    if ($i -lt 0 -or $j -lt 0 -or $j -ge $pe.Dialogs.Count) { return }
    $tmp = $pe.Dialogs[$i]; $pe.Dialogs[$i] = $pe.Dialogs[$j]; $pe.Dialogs[$j] = $tmp
    Update-PeDialogList $j
    $pe.Touched = $true
}

# ---------- 关于自己 ----------
function Get-PeFactLabel($f, [int]$i) {
    $x = ConvertTo-OneLine $f.F
    if (-not $x) { $x = '（空）' }
    if ($x.Length -gt 34) { $x = $x.Substring(0, 34) + '…' }
    $k = ConvertTo-OneLine $f.K
    $tag = if ($k) { "［$k］" } else { '' }
    return ("{0,2}. {1}{2}" -f ($i + 1), $tag, $x)
}

function Update-PeFactKinds {
    $pe = $script:PE
    $kinds = @($pe.Facts | ForEach-Object { ConvertTo-OneLine $_.K } | Where-Object { $_ } | Sort-Object -Unique)
    $pe.Syncing = $true
    $keep = $pe.FactKind.Text
    $pe.FactKind.BeginUpdate()
    $pe.FactKind.Items.Clear()
    foreach ($k in $kinds) { [void]$pe.FactKind.Items.Add($k) }
    $pe.FactKind.EndUpdate()
    $pe.FactKind.Text = $keep
    $pe.Syncing = $false
}

function Update-PeFactList([int]$select = -2) {
    $pe = $script:PE
    if ($select -eq -2) { $select = $pe.FactList.SelectedIndex }
    $pe.Syncing = $true
    $pe.FactList.BeginUpdate()
    $pe.FactList.Items.Clear()
    for ($i = 0; $i -lt $pe.Facts.Count; $i++) { [void]$pe.FactList.Items.Add((Get-PeFactLabel $pe.Facts[$i] $i)) }
    if ($select -ge $pe.Facts.Count) { $select = $pe.Facts.Count - 1 }
    $pe.FactList.SelectedIndex = $select
    $pe.FactList.EndUpdate()
    $pe.Syncing = $false
    Update-PeFactKinds
    Show-PeFact
}

function Show-PeFact {
    $pe = $script:PE
    $i = $pe.FactList.SelectedIndex
    $pe.Syncing = $true
    $has = ($i -ge 0 -and $i -lt $pe.Facts.Count)
    $pe.FactText.Enabled = $has; $pe.FactKind.Enabled = $has
    $pe.BtnFactDel.Enabled = $has
    $pe.BtnFactUp.Enabled = $has -and $i -gt 0
    $pe.BtnFactDown.Enabled = $has -and $i -lt $pe.Facts.Count - 1
    if ($has) {
        $pe.FactText.Text = $pe.Facts[$i].F
        $pe.FactKind.Text = $pe.Facts[$i].K
    } else {
        $pe.FactText.Text = ''; $pe.FactKind.Text = ''
    }
    $pe.Syncing = $false
}

function Save-PeFactEdit {
    $pe = $script:PE
    if ($pe.Syncing) { return }
    $i = $pe.FactList.SelectedIndex
    if ($i -lt 0 -or $i -ge $pe.Facts.Count) { return }
    $pe.Facts[$i].F = $pe.FactText.Text
    $pe.Facts[$i].K = $pe.FactKind.Text
    $pe.Syncing = $true
    $pe.FactList.Items[$i] = Get-PeFactLabel $pe.Facts[$i] $i
    $pe.Syncing = $false
    $pe.Touched = $true
}

function Move-PeFact([int]$delta) {
    $pe = $script:PE
    $i = $pe.FactList.SelectedIndex
    $j = $i + $delta
    if ($i -lt 0 -or $j -lt 0 -or $j -ge $pe.Facts.Count) { return }
    $tmp = $pe.Facts[$i]; $pe.Facts[$i] = $pe.Facts[$j]; $pe.Facts[$j] = $tmp
    Update-PeFactList $j
    $pe.Touched = $true
}

# ---------- 工具权限 ----------
function Set-PeToolMode {
    $pe = $script:PE
    $pick = $pe.RbPick.Checked
    $pe.ToolList.Enabled = $pick
    $pe.BtnToolAll.Enabled = $pick
    $pe.BtnToolNone.Enabled = $pick
    $n = 0
    for ($i = 0; $i -lt $pe.ToolList.Items.Count; $i++) { if ($pe.ToolList.GetItemChecked($i)) { $n++ } }
    $pe.ToolInfo.Text = if ($pick) { "勾了 $n / $($pe.ToolList.Items.Count) 个。没勾的她就调用不了（比如去掉 post_qzone 她就发不了说说）。" }
                        else { "现在 $($pe.ToolList.Items.Count) 个工具她都能用；以后新装插件带来的工具也自动能用。" }
}

function Set-PeTools($toolInfos, $allowed) {
    $pe = $script:PE
    $pe.Syncing = $true
    $pe.ToolNames = New-Object System.Collections.ArrayList
    $pe.ToolList.BeginUpdate()
    $pe.ToolList.Items.Clear()
    $known = @{}
    foreach ($t in @($toolInfos)) {
        if (-not $t -or -not $t.name) { continue }
        $known[[string]$t.name] = $true
        $desc = ([string]$t.description -replace "\s+", ' ').Trim()
        if ($desc.Length -gt 60) { $desc = $desc.Substring(0, 60) + '…' }
        $from = if ($t.origin -eq 'builtin') { 'AstrBot 自带' } elseif ($t.origin_name) { [string]$t.origin_name } else { [string]$t.origin }
        $off = if ($t.active -eq $false) { '（插件里停用了）' } else { '' }
        [void]$pe.ToolNames.Add([string]$t.name)
        [void]$pe.ToolList.Items.Add(("{0}{1}   [{2}]   {3}" -f $t.name, $off, $from, $desc))
    }
    foreach ($name in @($allowed)) {
        if ($name -and -not $known.ContainsKey([string]$name)) {
            [void]$pe.ToolNames.Add([string]$name)
            [void]$pe.ToolList.Items.Add(("{0}   [现在找不到这个工具，插件可能卸了]" -f $name))
        }
    }
    $pe.RbAll.Checked = ($null -eq $allowed)
    $pe.RbPick.Checked = ($null -ne $allowed)
    for ($i = 0; $i -lt $pe.ToolNames.Count; $i++) {
        $on = ($null -eq $allowed) -or (@($allowed) -contains $pe.ToolNames[$i])
        $pe.ToolList.SetItemChecked($i, $on)
    }
    $pe.ToolList.EndUpdate()
    $pe.Syncing = $false
    Set-PeToolMode
}

# ---------- 把一份人格填进各个编辑框 ----------
function Set-PeEditors($state) {
    $pe = $script:PE
    $pe.Syncing = $true
    $pe.Prompt.Text = ConvertTo-Crlf $state.system_prompt
    $pe.Prompt.SelectionStart = 0
    $pe.Prompt.ScrollToCaret()
    $pe.Dialogs = New-Object System.Collections.ArrayList
    $d = @($state.begin_dialogs)
    for ($i = 0; $i + 1 -lt $d.Count; $i += 2) { [void]$pe.Dialogs.Add(@{ U = (ConvertTo-Crlf $d[$i]); B = (ConvertTo-Crlf $d[$i + 1]) }) }
    $pe.ErrBox.Text = $state.custom_error_message
    if ($null -ne $state.self_facts) {   # 旧备份没有「关于自己」：编辑器里的清单不动
        $pe.Facts = New-Object System.Collections.ArrayList
        foreach ($key in @($state.self_facts)) { $f = ConvertFrom-FactKey $key; [void]$pe.Facts.Add(@{ F = $f.fact; K = $f.kind }) }
    }
    $pe.Syncing = $false
    Set-PeTools $pe.ToolInfos $state.tools
    Update-PeSections
    Update-PeDialogList ($(if ($pe.Dialogs.Count) { 0 } else { -1 }))
    Update-PeFactList ($(if ($pe.Facts.Count) { 0 } else { -1 }))
    Update-PeButtons
}

function Set-PeOnlineText([bool]$online) {
    $script:PE.Online = $online
    $script:PE.Sub.Text = if ($online) { '机器人在线 · 保存后马上生效（她下一句话就用新人格）· 保存前自动备份旧版本' }
                          else { '机器人没开 · 保存会直接写进数据库，下次启动生效（「关于自己」直接写文件）· 保存前自动备份旧版本' }
    $script:PE.Sub.ForeColor = if ($online) { $Pal.GreenText } else { $Pal.AmberText }
}

function Start-PeLoad {
    Set-PeStatus '正在读取佳树现在的人格…'
    Invoke-PersonaTool @('get') {
        param($r, $err)
        if ($err) { Set-PeStatus "读取失败：$err" 'bad'; return }
        $pe = $script:PE
        $pe.ToolInfos = @($r.tools)
        $pe.Base = ConvertTo-PeState $r.persona
        Set-PeOnlineText ([bool]$r.online)
        Set-PeEditors $pe.Base
        $when = ''
        if ($r.persona.updated_at) { $when = "（上次修改：$(([string]$r.persona.updated_at) -replace 'T', ' ' -replace '\.\d+.*$', '')）" }
        $toolNote = if (-not $r.online) { ' 机器人没开，工具列表来自上次在线时的记录 + 插件源码。' } else { '' }
        Set-PeStatus "已读取当前人格$when。$toolNote" 'ok'
    }
}

# ---------- 保存 ----------
function Start-PeSave {
    $pe = $script:PE
    if ($pe.Busy -gt 0 -or -not $pe.Base) { return }
    $changes = @(Get-PeChanges)
    if ($changes.Count -eq 0) { Set-PeStatus '没有改动。'; return }
    $now = Get-PeState

    # 先在这边检查一遍，省得等后台报错
    if (-not $now.system_prompt.Trim()) { Set-PeTab 'prompt'; Set-PeStatus '人设正文不能是空的。' 'bad'; return }
    for ($i = 0; $i -lt $pe.Dialogs.Count; $i++) {
        if (-not $pe.Dialogs[$i].U.Trim() -or -not $pe.Dialogs[$i].B.Trim()) {
            Set-PeTab 'dialogs'; Update-PeDialogList $i
            Set-PeStatus "第 $($i + 1) 组示例对话有空的格子：填上，或者把这组删掉。" 'bad'; return
        }
    }
    $seen = @{}
    for ($i = 0; $i -lt $pe.Facts.Count; $i++) {
        $x = ConvertTo-OneLine $pe.Facts[$i].F
        $bad = if (-not $x) { "「关于自己」第 $($i + 1) 条是空的：写上，或者把它删掉。" }
               elseif ($seen.ContainsKey($x)) { "「关于自己」第 $($i + 1) 条和第 $($seen[$x]) 条一模一样，删掉一条吧。" }
        if ($bad) { Set-PeTab 'facts'; Update-PeFactList $i; Set-PeStatus $bad 'bad'; return }
        $seen[$x] = $i + 1
    }
    if ($null -ne $now.tools -and @($now.tools).Count -eq 0) {
        $ans = [System.Windows.Forms.MessageBox]::Show($pe.Form, '一个工具都没勾：她将不能查资料、存表情、发说说、看群……确定这样吗？', '人格微调', 'YesNo', 'Warning')
        if ($ans -ne 'Yes') { return }
    }

    $lines = @()
    foreach ($k in $changes) {
        switch ($k) {
            'system_prompt' { $lines += "· 人设正文：$($pe.Base.system_prompt.Length) 字 → $($now.system_prompt.Length) 字" }
            'begin_dialogs' { $lines += "· 示例对话：$([int](@($pe.Base.begin_dialogs).Count / 2)) 组 → $($pe.Dialogs.Count) 组" }
            'tools' {
                $desc = if ($null -eq $now.tools) { '全部都能用' } else { "只能用勾选的 $(@($now.tools).Count) 个" }
                $lines += "· 工具权限：$desc"
            }
            'custom_error_message' {
                $desc = if ($now.custom_error_message) { "「$($now.custom_error_message)」" } else { '留空（出错时会发英文技术报错！）' }
                $lines += "· 出错回复：$desc"
            }
            'self_facts' { $lines += "· 关于自己：$(@($pe.Base.self_facts).Count) 条 → $($pe.Facts.Count) 条（下一轮就用新的）" }
        }
    }
    $where = if ($pe.Online) { '机器人在线，保存后马上生效。' } else { '机器人没开，会直接写进数据库，下次启动生效。' }
    $msg = "要保存这些修改吗？`r`n`r`n$($lines -join "`r`n")`r`n`r`n$where`r`n保存前会自动备份现在的版本，随时能在「历史版本」里找回。"
    $ans = [System.Windows.Forms.MessageBox]::Show($pe.Form, $msg, '保存人格', 'OKCancel', 'Question')
    if ($ans -ne 'OK') { return }

    $payload = @{}
    foreach ($k in $changes) { $payload[$k] = $now[$k] }
    if ($payload.ContainsKey('begin_dialogs')) { $payload['begin_dialogs'] = [object[]]@($now.begin_dialogs) }
    if ($payload.ContainsKey('tools') -and $null -ne $now.tools) { $payload['tools'] = [object[]]@($now.tools) }
    if ($payload.ContainsKey('self_facts')) { $payload['self_facts'] = [object[]]@($now.self_facts | ForEach-Object { ConvertFrom-FactKey $_ }) }
    $json = ConvertTo-Json -InputObject $payload -Depth 6 -Compress
    $inFile = [IO.Path]::Combine([IO.Path]::GetTempPath(), 'jiashu-persona-in-' + [guid]::NewGuid().ToString('N') + '.json')
    [IO.File]::WriteAllText($inFile, $json, (New-Object System.Text.UTF8Encoding($false)))
    $pe.SaveIn = $inFile
    $pe.Saving = $true
    Set-PeStatus '正在保存…'
    Invoke-PersonaTool @('save', '--in', $inFile) {
        param($r, $err)
        $pe = $script:PE
        $pe.Saving = $false
        try { [IO.File]::Delete($pe.SaveIn) } catch { }
        if ($err) { Set-PeStatus "保存失败，什么都没改：$err" 'bad'; return }
        Set-PeOnlineText ([bool]$r.online)
        $pe.Base = ConvertTo-PeState $r.persona
        # 编辑框里的内容和保存后的一致就不动（保住光标位置），不一致（比如工具被排序）才重新填
        $now = Get-PeState
        $same = $true
        foreach ($k in $pe.Base.Keys) { if (-not (Test-PeSame $now[$k] $pe.Base[$k])) { $same = $false } }
        if (-not $same) { Set-PeEditors $pe.Base }
        $pe.HistLoaded = $false
        $names = @($r.changed | ForEach-Object { $PeFieldNames[[string]$_] }) -join '、'
        $bk = if ($r.backup) { " 旧版本备份：$([IO.Path]::GetFileName([string]$r.backup))" } else { '' }
        if (@($r.changed).Count -eq 0) { Set-PeStatus '和现在的人格一样，没有改动。' 'ok' }
        elseif ($r.online) { Set-PeStatus "已保存并生效：$names。$bk" 'ok' }
        else { Set-PeStatus "已写进数据库：$names，下次启动生效。$bk" 'ok' }
        Update-PeButtons
    }
}

# ---------- 历史版本 ----------
function Start-PeHistory {
    $pe = $script:PE
    $pe.HistList.Items.Clear()
    $pe.HistPreview.Text = ''
    $pe.HistPersona = $null
    $pe.HistInfo.Text = '读取中…'
    $pe.HistLoading = $true
    Invoke-PersonaTool @('history') {
        param($r, $err)
        $pe = $script:PE
        $pe.HistLoading = $false
        if ($err) { $pe.HistInfo.Text = "读取失败：$err"; return }
        $pe.HistLoaded = $true
        $pe.HistFiles = New-Object System.Collections.ArrayList
        $pe.HistList.BeginUpdate()
        foreach ($it in @($r.items)) {
            if (-not $it) { continue }
            [void]$pe.HistFiles.Add([string]$it.file)
            $when = ([string]$it.saved_at) -replace 'T', ' '
            if ($when.Length -ge 16) { $when = $when.Substring(5, 11) }
            $tools = if ($null -eq $it.tools) { '全部工具' } else { "$($it.tools) 个工具" }
            $facts = if ($null -eq $it.facts) { '' } else { " · 关于自己 $($it.facts) 条" }
            [void]$pe.HistList.Items.Add(("{0}   {1} 字 · {2} 组对话 · {3}{4}" -f $when, $it.chars, $it.dialogs, $tools, $facts))
        }
        $pe.HistList.EndUpdate()
        $pe.HistInfo.Text = if ($pe.HistFiles.Count) { "共 $($pe.HistFiles.Count) 个备份（每次保存前自动存的旧版本，最多留 200 个）" } else { '还没有备份。第一次保存时会把现在的版本备份下来。' }
    }
}

function Show-PeHistoryItem {
    $pe = $script:PE
    $i = $pe.HistList.SelectedIndex
    if ($i -lt 0 -or $i -ge $pe.HistFiles.Count) { return }
    $file = $pe.HistFiles[$i]
    $pe.HistPersona = $null
    $pe.HistWant = $file
    $pe.HistPreview.Text = '读取中…'
    Update-PeButtons
    Invoke-PersonaTool @('show', $file) {
        param($r, $err)
        $pe = $script:PE
        if ($r -and [string]$r.file -ne $pe.HistWant) { return }   # 已经点了别的版本
        if ($err) { $pe.HistPreview.Text = "读取失败：$err"; return }
        $pe.HistPersona = ConvertTo-PeState $r.persona
        $pe.HistPersonaFile = [string]$r.file
        $h = $pe.HistPersona
        $d = @($h.begin_dialogs)
        $parts = @("【人设正文】", (ConvertTo-Crlf $h.system_prompt), '', "【示例对话 $([int]($d.Count / 2)) 组】")
        for ($k = 0; $k + 1 -lt $d.Count; $k += 2) { $parts += ("兄长大人：" + ($d[$k] -replace "`n", ' / ')); $parts += ("佳树：" + ($d[$k + 1] -replace "`n", ' / ')) }
        $toolsText = if ($null -eq $h.tools) { '全部都能用' } else { (@($h.tools) -join '、') }
        $parts += @('', "【工具权限】$toolsText", '', "【出错回复】$($h.custom_error_message)")
        if ($null -eq $h.self_facts) {
            $parts += @('', '【关于自己】这个备份里没有（11-07 之前还没有这份清单），载入时保留现在的。')
        } else {
            $parts += @('', "【关于自己 $(@($h.self_facts).Count) 条】")
            foreach ($key in @($h.self_facts)) { $f = ConvertFrom-FactKey $key; $parts += $(if ($f.kind) { "［$($f.kind)］$($f.fact)" } else { $f.fact }) }
        }
        $pe.HistPreview.Text = $parts -join "`r`n"
        $reason = ''
        if ($r.saved_at) { $reason = "这是 $(([string]$r.saved_at) -replace 'T', ' ') 保存前的版本。" }
        $pe.HistInfo.Text = "$reason 点「载入到编辑器」，检查后再保存就恢复成它。"
        Update-PeButtons
    }
}

function Restore-PeHistory {
    $pe = $script:PE
    if (-not $pe.HistPersona) { return }
    if ($pe.Dirty) {
        $ans = [System.Windows.Forms.MessageBox]::Show($pe.Form, '编辑器里有还没保存的修改，载入旧版本会把它们替换掉。继续吗？', '人格微调', 'YesNo', 'Warning')
        if ($ans -ne 'Yes') { return }
    }
    Set-PeEditors $pe.HistPersona
    Set-PeTab 'prompt'
    Set-PeStatus "已把 $($pe.HistPersonaFile) 载入编辑器（还没保存）。检查一下，点「保存并生效」才会真的恢复。" 'warn'
}

# ---------- 分页 ----------
function Set-PeTab([string]$key) {
    $pe = $script:PE
    $pe.Tab = $key
    foreach ($k in $pe.TabKeys) {
        $pe.Pages[$k].Visible = ($k -eq $key)
        Set-SegStyle $pe.Tabs[$k] ($k -eq $key)
    }
    if ($key -eq 'history' -and -not $pe.HistLoaded -and -not $pe.HistLoading) { Start-PeHistory }
}

# =====================================================================
#  窗口
# =====================================================================
function Show-PersonaEditor {
    $pe = @{ Busy = 0; Base = $null; Dirty = $false; Syncing = $false; Touched = $false; SecDirty = $false; Saving = $false
             Cbs = @{}; Seq = [int]$script:PE.Seq   # 编号接着上一次的，免得旧窗口没回来的结果被认成新的
             Dialogs = (New-Object System.Collections.ArrayList); ToolNames = (New-Object System.Collections.ArrayList)
             ToolInfos = @(); HistFiles = (New-Object System.Collections.ArrayList); HistLoaded = $false; HistPersona = $null
             Sections = (New-Object System.Collections.ArrayList); Online = $false
             Facts = (New-Object System.Collections.ArrayList) }
    $script:PE = $pe

    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = '人格微调'
    $dlg.AutoScaleMode = 'None'
    $dlg.ClientSize = Sz 1000 690
    $dlg.FormBorderStyle = 'FixedDialog'
    $dlg.MaximizeBox = $false
    $dlg.MinimizeBox = $true
    $dlg.ShowInTaskbar = $true
    $dlg.StartPosition = 'CenterParent'
    $dlg.BackColor = $Pal.Bg
    $dlg.Font = Fnt 9
    $dlg.KeyPreview = $true
    if ($form.Icon) { $dlg.Icon = $form.Icon }
    $pe.Form = $dlg

    $title = New-Label '人格微调' 24 14 300 32 (Fnt 15 'Bold') $Pal.Text
    $pe.Sub = New-Label '读取中…' 25 46 760 20 (Fnt 9) $Pal.Muted
    $dlg.Controls.AddRange(@($title, $pe.Sub))

    # 分页按钮
    $pe.TabKeys = @('prompt', 'facts', 'dialogs', 'tools', 'error', 'history')
    $pe.TabLabels = @{ prompt = '人设正文'; facts = '关于自己'; dialogs = '示例对话'; tools = '工具权限'; error = '出错回复'; history = '历史版本' }
    $pe.TabField = @{ prompt = 'system_prompt'; facts = 'self_facts'; dialogs = 'begin_dialogs'; tools = 'tools'; error = 'custom_error_message'; history = '' }
    $seg = New-Object JiashuUi.Card
    $seg.Location = Pt 24 78
    $seg.Size = Sz 685 38
    $seg.Radius = Px 10
    $seg.Fill = $Pal.GreySoft
    $seg.Border = $Pal.Clear
    $pe.Tabs = @{}
    for ($i = 0; $i -lt $pe.TabKeys.Count; $i++) {
        $k = $pe.TabKeys[$i]
        $b = New-Button $pe.TabLabels[$k] (3 + $i * 113.2) 3 110 32 'ghost' 9.5
        $b.Radius = Px 8
        $b.Tag = $k
        $b.Add_Click({ param($s, $e) Set-PeTab ([string]$s.Tag) })
        $pe.Tabs[$k] = $b
        $seg.Controls.Add($b)
    }
    $pe.BtnReload = New-Button '重新读取' 870 80 106 34 'ghost' 9
    $dlg.Controls.AddRange(@($seg, $pe.BtnReload))

    $card = New-Card 24 128 952 482
    $dlg.Controls.Add($card)
    $pe.Pages = @{}
    foreach ($k in $pe.TabKeys) {
        $p = New-Object JiashuUi.Card
        $p.Location = Pt 1 1
        $p.Size = Sz 950 480
        $p.Radius = 0
        $p.Fill = $Pal.Card
        $p.Border = $Pal.Clear
        $p.Visible = $false
        $pe.Pages[$k] = $p
        $card.Controls.Add($p)
    }

    # ----- 人设正文 -----
    $pg = $pe.Pages['prompt']
    $l1 = New-Label '每一行（点一下跳过去）' 20 12 250 22 (Fnt 9 'Bold') $Pal.Sub
    $pe.SecList = New-Object System.Windows.Forms.ListBox
    $pe.SecList.Location = Pt 20 38
    $pe.SecList.Size = Sz 250 384
    $pe.SecList.IntegralHeight = $false
    $pe.SecList.Font = Fnt 9
    $pe.SecList.BorderStyle = 'FixedSingle'
    $pe.SecList.BackColor = $Pal.DropFill
    $pe.SecList.HorizontalScrollbar = $false
    $l2 = New-Label '她每次回复前都会看一遍。现在只放两句身份 + 几条做事规则；她是谁的细节放「关于自己」，口吻交给本地写手。' 290 12 640 22 (Fnt 9) $Pal.Muted
    $l2.AutoEllipsis = $true
    $pe.Prompt = New-Object System.Windows.Forms.TextBox
    $pe.Prompt.Location = Pt 290 38
    $pe.Prompt.Size = Sz 640 384
    $pe.Prompt.Multiline = $true
    $pe.Prompt.AcceptsReturn = $true
    $pe.Prompt.AcceptsTab = $false
    $pe.Prompt.WordWrap = $true
    $pe.Prompt.ScrollBars = 'Vertical'
    $pe.Prompt.MaxLength = 0
    $pe.Prompt.HideSelection = $false
    $pe.Prompt.Font = Fnt 10.5
    $pe.FindBox = New-Object System.Windows.Forms.TextBox
    $pe.FindBox.Location = Pt 290 437
    $pe.FindBox.Width = Px 170
    $pe.FindBox.Font = Fnt 9.5
    $pe.BtnFind = New-Button '查找下一个' 466 432 92 32 'ghost' 9
    $pe.PromptInfo = New-Label '' 566 432 190 32 (Fnt 9) $Pal.Muted
    $pe.BtnImport = New-Button '从文件导入…' 760 432 84 32 'ghost' 8.5
    $pe.BtnExport = New-Button '导出…' 850 432 80 32 'ghost' 8.5
    $pe.SecInfo = New-Label '查找：Ctrl+F，下一个：F3 / 回车' 20 432 250 32 (Fnt 8.5) $Pal.Muted
    $pg.Controls.AddRange(@($l1, $pe.SecList, $l2, $pe.Prompt, $pe.FindBox, $pe.BtnFind, $pe.PromptInfo, $pe.BtnImport, $pe.BtnExport, $pe.SecInfo))

    # ----- 关于自己 -----
    $pg = $pe.Pages['facts']
    $f1 = New-Label '她是谁的细节（家人、学校、喜好、习惯…）。每轮按对方刚说的话想起最相关的 5 条放进提示，用不上就不提。一条只写一件事，用「佳树……」开头。' 20 12 910 22 (Fnt 9) $Pal.Muted
    $f1.AutoEllipsis = $true
    $pe.FactList = New-Object System.Windows.Forms.ListBox
    $pe.FactList.Location = Pt 20 40
    $pe.FactList.Size = Sz 520 382
    $pe.FactList.IntegralHeight = $false
    $pe.FactList.Font = Fnt 9
    $pe.FactList.BorderStyle = 'FixedSingle'
    $pe.FactList.BackColor = $Pal.DropFill
    $pe.BtnFactAdd  = New-Button '＋ 新增一条' 20 432 104 32 'ghost' 9
    $pe.BtnFactDel  = New-Button '删除这条' 130 432 92 32 'ghost' 9
    $pe.BtnFactUp   = New-Button '上移' 228 432 70 32 'ghost' 9
    $pe.BtnFactDown = New-Button '下移' 304 432 70 32 'ghost' 9
    $pe.FactInfo = New-Label '' 382 432 158 32 (Fnt 9) $Pal.Muted 'MiddleRight'
    $f2 = New-Label '分类（可以选，也可以直接写新的）' 560 40 370 22 (Fnt 9 'Bold') $Pal.Sub
    $pe.FactKind = New-Object System.Windows.Forms.ComboBox
    $pe.FactKind.Location = Pt 560 64
    $pe.FactKind.Width = Px 220
    $pe.FactKind.DropDownStyle = 'DropDown'
    $pe.FactKind.Font = Fnt 10
    $pe.FactKind.MaxDropDownItems = 14
    $f3 = New-Label '这一条' 560 104 370 22 (Fnt 9 'Bold') $Pal.Sub
    $pe.FactText = New-Object System.Windows.Forms.TextBox
    $pe.FactText.Location = Pt 560 128
    $pe.FactText.Size = Sz 370 150
    $pe.FactText.Multiline = $true; $pe.FactText.AcceptsReturn = $false; $pe.FactText.ScrollBars = 'Vertical'
    $pe.FactText.Font = Fnt 10.5
    $f4 = New-Label ("写她自己会这样想的事实，别写口吻或说话规则（那些交给本地写手）。`r`n" +
                     "保存后直接写进 kaju_life 的 self_facts.json，下一轮就用新的；新句子的向量第一次用到时自动算。") 560 290 370 120 (Fnt 9) $Pal.Muted 'TopLeft'
    $pg.Controls.AddRange(@($f1, $pe.FactList, $pe.BtnFactAdd, $pe.BtnFactDel, $pe.BtnFactUp, $pe.BtnFactDown, $pe.FactInfo, $f2, $pe.FactKind, $f3, $pe.FactText, $f4))

    # ----- 示例对话 -----
    $pg = $pe.Pages['dialogs']
    $d1 = New-Label '放在每次聊天最前面的示范对话。11-07 起有意清空：口吻交给本地写手（照卡写），这里只会影响 DeepSeek 的草稿，一般不用加。' 20 12 910 22 (Fnt 9) $Pal.Muted
    $d1.AutoEllipsis = $true
    $pe.DlgList = New-Object System.Windows.Forms.ListBox
    $pe.DlgList.Location = Pt 20 40
    $pe.DlgList.Size = Sz 400 382
    $pe.DlgList.IntegralHeight = $false
    $pe.DlgList.Font = Fnt 9
    $pe.DlgList.BorderStyle = 'FixedSingle'
    $pe.DlgList.BackColor = $Pal.DropFill
    $pe.BtnDlgAdd  = New-Button '＋ 新增一组' 20 432 104 32 'ghost' 9
    $pe.BtnDlgDel  = New-Button '删除这组' 130 432 92 32 'ghost' 9
    $pe.BtnDlgUp   = New-Button '上移' 228 432 70 32 'ghost' 9
    $pe.BtnDlgDown = New-Button '下移' 304 432 70 32 'ghost' 9
    $d2 = New-Label '兄长大人说' 440 40 490 22 (Fnt 9 'Bold') $Pal.Sub
    $pe.DlgUser = New-Object System.Windows.Forms.TextBox
    $pe.DlgUser.Location = Pt 440 64
    $pe.DlgUser.Size = Sz 490 96
    $pe.DlgUser.Multiline = $true; $pe.DlgUser.AcceptsReturn = $true; $pe.DlgUser.ScrollBars = 'Vertical'
    $pe.DlgUser.Font = Fnt 10.5
    $d3 = New-Label '佳树回（每一行单独发一条）' 440 172 490 22 (Fnt 9 'Bold') $Pal.Sub
    $pe.DlgBot = New-Object System.Windows.Forms.TextBox
    $pe.DlgBot.Location = Pt 440 196
    $pe.DlgBot.Size = Sz 490 226
    $pe.DlgBot.Multiline = $true; $pe.DlgBot.AcceptsReturn = $true; $pe.DlgBot.ScrollBars = 'Vertical'
    $pe.DlgBot.Font = Fnt 10.5
    $pe.DlgInfo = New-Label '' 440 432 490 32 (Fnt 9) $Pal.Muted
    $pg.Controls.AddRange(@($d1, $pe.DlgList, $pe.BtnDlgAdd, $pe.BtnDlgDel, $pe.BtnDlgUp, $pe.BtnDlgDown, $d2, $pe.DlgUser, $d3, $pe.DlgBot, $pe.DlgInfo))

    # ----- 工具权限 -----
    $pg = $pe.Pages['tools']
    $pe.RbAll = New-Object System.Windows.Forms.RadioButton
    $pe.RbAll.Text = '全部工具都能用（以后新装插件带来的工具也自动能用）'
    $pe.RbAll.Location = Pt 20 12; $pe.RbAll.Size = Sz 900 26; $pe.RbAll.Font = Fnt 10; $pe.RbAll.BackColor = $Pal.Card
    $pe.RbPick = New-Object System.Windows.Forms.RadioButton
    $pe.RbPick.Text = '只能用下面勾选的'
    $pe.RbPick.Location = Pt 20 40; $pe.RbPick.Size = Sz 900 26; $pe.RbPick.Font = Fnt 10; $pe.RbPick.BackColor = $Pal.Card
    $pe.ToolList = New-Object System.Windows.Forms.CheckedListBox
    $pe.ToolList.Location = Pt 20 74
    $pe.ToolList.Size = Sz 910 348
    $pe.ToolList.IntegralHeight = $false
    $pe.ToolList.CheckOnClick = $true
    $pe.ToolList.Font = Fnt 9.5
    $pe.ToolList.BorderStyle = 'FixedSingle'
    $pe.BtnToolAll  = New-Button '全选' 20 432 80 32 'ghost' 9
    $pe.BtnToolNone = New-Button '全不选' 106 432 80 32 'ghost' 9
    $pe.ToolInfo = New-Label '' 196 432 734 32 (Fnt 9) $Pal.Muted
    $pe.ToolInfo.AutoEllipsis = $true
    $pg.Controls.AddRange(@($pe.RbAll, $pe.RbPick, $pe.ToolList, $pe.BtnToolAll, $pe.BtnToolNone, $pe.ToolInfo))

    # ----- 出错回复 -----
    $pg = $pe.Pages['error']
    $e1 = New-Label '出错时她说的话' 20 14 900 24 (Fnt 11 'Bold') $Pal.Text
    $e2 = New-Label '模型那边连着重试都失败时（比如 DeepSeek 卡住），机器人会把这句话原样发出去，不经过模型。留空的话，会把英文的技术报错原文（Error occurred during AI execution…）发到群里。' 20 42 900 44 (Fnt 9) $Pal.Sub 'TopLeft'
    $pe.ErrBox = New-Object System.Windows.Forms.TextBox
    $pe.ErrBox.Location = Pt 20 94
    $pe.ErrBox.Size = Sz 910 70
    $pe.ErrBox.Multiline = $true; $pe.ErrBox.AcceptsReturn = $true
    $pe.ErrBox.Font = Fnt 11
    $e3 = New-Label '建议：写成佳树自己的口气，像她走神了一样，不要提到报错、AI、服务器。' 20 172 900 22 (Fnt 9) $Pal.Muted
    $pg.Controls.AddRange(@($e1, $e2, $pe.ErrBox, $e3))

    # ----- 历史版本 -----
    $pg = $pe.Pages['history']
    $h1 = New-Label '每次保存前自动备份的旧版本（新的在上面）' 20 12 400 22 (Fnt 9 'Bold') $Pal.Sub
    $pe.HistList = New-Object System.Windows.Forms.ListBox
    $pe.HistList.Location = Pt 20 38
    $pe.HistList.Size = Sz 400 384
    $pe.HistList.IntegralHeight = $false
    $pe.HistList.Font = Fnt 9
    $pe.HistList.BorderStyle = 'FixedSingle'
    $pe.HistList.BackColor = $Pal.DropFill
    $h2 = New-Label '内容预览' 440 12 490 22 (Fnt 9 'Bold') $Pal.Sub
    $pe.HistPreview = New-Object System.Windows.Forms.TextBox
    $pe.HistPreview.Location = Pt 440 38
    $pe.HistPreview.Size = Sz 490 384
    $pe.HistPreview.Multiline = $true; $pe.HistPreview.ReadOnly = $true; $pe.HistPreview.ScrollBars = 'Vertical'
    $pe.HistPreview.BackColor = $Pal.DropFill
    $pe.HistPreview.Font = Fnt 9.5
    $pe.HistInfo = New-Label '' 20 428 410 44 (Fnt 8.5) $Pal.Muted 'TopLeft'
    $pe.BtnLoadHist = New-Button '载入到编辑器' 440 432 150 32 'primary' 9.5
    $pe.BtnHistDir  = New-Button '打开备份文件夹' 598 432 130 32 'ghost' 9
    $pg.Controls.AddRange(@($h1, $pe.HistList, $h2, $pe.HistPreview, $pe.HistInfo, $pe.BtnLoadHist, $pe.BtnHistDir))

    # ----- 底部 -----
    $pe.Status = New-Label '' 24 622 640 52 (Fnt 9) $Pal.Sub 'MiddleLeft'
    $pe.Status.AutoEllipsis = $true
    $pe.BtnRevert = New-Button '放弃修改' 676 624 110 46 'ghost' 10
    $pe.BtnSave   = New-Button '保存并生效' 796 624 180 46 'primary' 11
    $dlg.Controls.AddRange(@($pe.Status, $pe.BtnRevert, $pe.BtnSave))
    $tip = New-Object System.Windows.Forms.ToolTip
    $tip.SetToolTip($pe.BtnSave, '保存（Ctrl+S）。保存前会自动备份现在的版本。')
    $tip.SetToolTip($pe.BtnRevert, '把编辑器恢复成上次读取 / 保存时的样子')
    $tip.SetToolTip($pe.BtnReload, '重新从机器人读取人格（编辑器里没保存的修改会丢掉）')
    $pe.Tip = $tip

    # ----- 事件 -----
    $pe.Prompt.Add_TextChanged({ $p = $script:PE; $p.LastEdit = Get-Date; if (-not $p.Syncing) { $p.Touched = $true; $p.SecDirty = $true } })
    $pe.SecList.Add_SelectedIndexChanged({ Select-PeSection })
    $pe.SecList.Add_Click({ Select-PeSection })
    $pe.BtnFind.Add_Click({ Find-PeNext })
    $pe.FindBox.Add_KeyDown({ param($s, $e) if ($e.KeyCode -eq 'Enter') { Find-PeNext; $e.SuppressKeyPress = $true } })
    $pe.BtnImport.Add_Click({
        $ofd = New-Object System.Windows.Forms.OpenFileDialog
        $ofd.Filter = '文本文件 (*.txt;*.md)|*.txt;*.md|所有文件 (*.*)|*.*'
        $ofd.Title = '导入人设正文（会替换编辑器里的正文，保存后才生效）'
        if ($ofd.ShowDialog($script:PE.Form) -eq 'OK') {
            try {
                $t = [IO.File]::ReadAllText($ofd.FileName, [Text.Encoding]::UTF8)
                $script:PE.Prompt.Text = ConvertTo-Crlf ($t.TrimStart([char]0xFEFF))
                Set-PeStatus "已导入 $([IO.Path]::GetFileName($ofd.FileName))（还没保存）。" 'warn'
            } catch { Set-PeStatus "导入失败：$($_.Exception.Message)" 'bad' }
        }
    })
    $pe.BtnExport.Add_Click({
        $sfd = New-Object System.Windows.Forms.SaveFileDialog
        $sfd.Filter = '文本文件 (*.txt)|*.txt'
        $sfd.FileName = "佳树人设-$(Get-Date -Format 'yyyyMMdd-HHmm').txt"
        if ($sfd.ShowDialog($script:PE.Form) -eq 'OK') {
            try {
                [IO.File]::WriteAllText($sfd.FileName, (ConvertTo-Lf $script:PE.Prompt.Text), (New-Object System.Text.UTF8Encoding($false)))
                Set-PeStatus "已导出到 $($sfd.FileName)" 'ok'
            } catch { Set-PeStatus "导出失败：$($_.Exception.Message)" 'bad' }
        }
    })

    $pe.DlgList.Add_SelectedIndexChanged({ if (-not $script:PE.Syncing) { Show-PeDialog } })
    $pe.DlgUser.Add_TextChanged({ Save-PeDialogEdit })
    $pe.DlgBot.Add_TextChanged({ Save-PeDialogEdit })
    $pe.BtnDlgAdd.Add_Click({
        $p = $script:PE
        $at = $p.DlgList.SelectedIndex + 1
        if ($at -le 0) { $at = $p.Dialogs.Count }
        $p.Dialogs.Insert($at, @{ U = ''; B = '' })
        Update-PeDialogList $at
        $p.DlgUser.Focus() | Out-Null
        $p.Touched = $true
    })
    $pe.BtnDlgDel.Add_Click({
        $p = $script:PE
        $i = $p.DlgList.SelectedIndex
        if ($i -lt 0) { return }
        $p.Dialogs.RemoveAt($i)
        Update-PeDialogList ([Math]::Min($i, $p.Dialogs.Count - 1))
        $p.Touched = $true
    })
    $pe.BtnDlgUp.Add_Click({ Move-PeDialog -1 })
    $pe.BtnDlgDown.Add_Click({ Move-PeDialog 1 })

    $pe.FactList.Add_SelectedIndexChanged({ if (-not $script:PE.Syncing) { Show-PeFact } })
    $pe.FactText.Add_TextChanged({ Save-PeFactEdit })
    $pe.FactKind.Add_TextChanged({ Save-PeFactEdit })
    $pe.FactKind.Add_SelectedIndexChanged({ Save-PeFactEdit })
    $pe.BtnFactAdd.Add_Click({
        $p = $script:PE
        $at = $p.FactList.SelectedIndex + 1
        $kind = if ($at -gt 0) { [string]$p.Facts[$at - 1].K } else { '' }   # 默认跟上一条同一类
        if ($at -le 0) { $at = $p.Facts.Count }
        $p.Facts.Insert($at, @{ F = '佳树'; K = $kind })
        Update-PeFactList $at
        $p.FactText.Focus() | Out-Null
        $p.FactText.SelectionStart = $p.FactText.Text.Length
        $p.Touched = $true
    })
    $pe.BtnFactDel.Add_Click({
        $p = $script:PE
        $i = $p.FactList.SelectedIndex
        if ($i -lt 0) { return }
        $p.Facts.RemoveAt($i)
        Update-PeFactList ([Math]::Min($i, $p.Facts.Count - 1))
        $p.Touched = $true
    })
    $pe.BtnFactUp.Add_Click({ Move-PeFact -1 })
    $pe.BtnFactDown.Add_Click({ Move-PeFact 1 })

    $pe.RbAll.Add_CheckedChanged({ if (-not $script:PE.Syncing) { Set-PeToolMode; $script:PE.Touched = $true } })
    $pe.RbPick.Add_CheckedChanged({ if (-not $script:PE.Syncing) { Set-PeToolMode; $script:PE.Touched = $true } })
    $pe.ToolList.Add_ItemCheck({ if (-not $script:PE.Syncing) { $script:PE.Touched = $true; $script:PE.ToolDirty = $true } })
    $pe.BtnToolAll.Add_Click({ $p = $script:PE; for ($i = 0; $i -lt $p.ToolList.Items.Count; $i++) { $p.ToolList.SetItemChecked($i, $true) } })
    $pe.BtnToolNone.Add_Click({ $p = $script:PE; for ($i = 0; $i -lt $p.ToolList.Items.Count; $i++) { $p.ToolList.SetItemChecked($i, $false) } })

    $pe.ErrBox.Add_TextChanged({ if (-not $script:PE.Syncing) { $script:PE.Touched = $true } })

    $pe.HistList.Add_SelectedIndexChanged({ Show-PeHistoryItem })
    $pe.BtnLoadHist.Add_Click({ Restore-PeHistory })
    $pe.BtnHistDir.Add_Click({
        try { New-Item -ItemType Directory -Force -Path $PersonaBackupDir | Out-Null; Start-Process explorer.exe $PersonaBackupDir } catch { }
    })

    $pe.BtnSave.Add_Click({ Start-PeSave })
    $pe.BtnRevert.Add_Click({
        $p = $script:PE
        if (-not $p.Base) { return }
        $ans = [System.Windows.Forms.MessageBox]::Show($p.Form, '把所有没保存的修改都丢掉，恢复成上次读取 / 保存时的样子？', '放弃修改', 'YesNo', 'Question')
        if ($ans -eq 'Yes') { Set-PeEditors $p.Base; Set-PeStatus '已放弃修改。' }
    })
    $pe.BtnReload.Add_Click({
        $p = $script:PE
        if ($p.Dirty) {
            $ans = [System.Windows.Forms.MessageBox]::Show($p.Form, '编辑器里有还没保存的修改，重新读取会丢掉它们。继续吗？', '重新读取', 'YesNo', 'Warning')
            if ($ans -ne 'Yes') { return }
        }
        $p.HistLoaded = $false
        Start-PeLoad
    })

    $dlg.Add_KeyDown({
        param($s, $e)
        if ($e.Control -and $e.KeyCode -eq 'S') { Start-PeSave; $e.SuppressKeyPress = $true }
        elseif ($e.Control -and $e.KeyCode -eq 'F' -and $script:PE.Tab -eq 'prompt') { $script:PE.FindBox.Focus() | Out-Null; $script:PE.FindBox.SelectAll(); $e.SuppressKeyPress = $true }
        elseif ($e.KeyCode -eq 'F3' -and $script:PE.Tab -eq 'prompt') { Find-PeNext; $e.SuppressKeyPress = $true }
    })

    # 改动后稍等一下再刷新（左边的行列表、标签上的 •、按钮），打字不卡
    $tick = New-Object System.Windows.Forms.Timer
    $tick.Interval = 300
    $tick.Add_Tick({
        $p = $script:PE
        if ($p.SecDirty -and ((Get-Date) - $p.LastEdit).TotalMilliseconds -gt 500) {
            $p.SecDirty = $false; Update-PeSections
        }
        if ($p.Touched) {
            $p.Touched = $false
            if ($p.ToolDirty) { $p.ToolDirty = $false; Set-PeToolMode }
            Update-PeButtons
        }
    })
    $pe.LastEdit = Get-Date
    $pe.Tick = $tick

    $dlg.Add_FormClosing({
        param($s, $e)
        $p = $script:PE
        if ($p.Saving) {
            [void][System.Windows.Forms.MessageBox]::Show($p.Form, '正在保存，等它保存完再关。', '人格微调', 'OK', 'Information')
            $e.Cancel = $true; return
        }
        if ($p.Dirty) {
            $ans = [System.Windows.Forms.MessageBox]::Show($p.Form, '有还没保存的修改。关掉的话这些修改就没了，确定关掉吗？', '人格微调', 'YesNo', 'Warning')
            if ($ans -ne 'Yes') { $e.Cancel = $true }
        }
    })
    $dlg.Add_Shown({ $script:PE.Tick.Start(); Start-PeLoad })

    Set-PeTab 'prompt'
    Update-PeButtons
    [void]$dlg.ShowDialog($form)
    $tick.Stop(); $tick.Dispose()
    $dlg.Dispose()
    $script:PE.Form = $null
}
