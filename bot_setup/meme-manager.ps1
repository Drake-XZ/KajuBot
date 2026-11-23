# 佳树控制台 ·「表情包管理」窗口（由 bot-panel.ps1 加载，不单独运行）
# 取代了原来的「表情图鉴」和主窗口卡片里的「查看 / 删除」。
#
#   默认视图「全部表情包（共用一套分类）」：所有能用的包合在一起，分类取并集，同义的小分类（别名表，比如 food）
#       并进大分类（eating）——点「开心」就能看到每个包里开心的图。在这里勾分类 / 改名 / 改说明 / 删分类，
#       会落到每个包各自对应的分类目录上（包里还没有这个分类就自动建上，用同一句说明）；新加的图放进佳树表情包。
#   下拉框里也能单独看某一个包（只改这一个包）。
#   看：每个分类她看不看得到、来自哪些包、缩略图、大图预览（GIF 会动）
#   增：「＋ 添加图片」或者把图片拖进窗口，加到当前分类
#   删：删掉的图先进回收站（D:\JiashuBot\_backup\meme-trash），能原样恢复，也能彻底删除
#   改：右边勾选这张图属于哪些分类，「保存分类」—— 一张图可以同时在好几个分类里
#       右键「移动到」= 只留在那一个分类；「也加到」= 多加一个分类
#   分类：新建 / 改名 / 改描述 / 删除（只在这个分类里的图进回收站）
# 读和改都交给 tools\memes.py：改动走表情包插件自己的接口，所以机器人要开着；没开时只能看。

$MemesTool = 'D:\JiashuBot\bot_setup\tools\memes.py'
$MmAllCats = '（全部）'
$MmCn = @{
    happy = '开心'; angry = '生气'; sad = '难过'; confused = '疑惑'; surprised = '吃惊'; shy = '害羞'
    tired = '累 / 无语'; sleep = '困 / 睡觉'; eating = '吃东西'; food = '吃东西'; affection = '喜欢 / 贴贴'
    teasing = '调侃 / 玩梗'; approval = '赞同 / 点赞'; reply = '普通回应'; greeting = '打招呼'; work = '工作'
    money = '钱'; entertainment = '娱乐'; tech = '技术'; portrait = '立绘'; action = '动作'; refusal = '拒绝'
    apology = '道歉'; attack = '揍你（玩笑）'; interaction = '互动'; question = '疑问'; surrender = '投降'
    thinking = '思考'; proud = '得意'; 'cold-shoulder' = '嫌弃 / 冷淡'; comfort = '安慰'; pray = '拜托 / 祈祷'
    relax = '放松'; mischief = '调皮'; sorry = '道歉'; refuse = '拒绝'; like = '喜欢'; thanks = '谢谢'; bye = '再见'
    morning = '早安'; concern = '关心'; fool = '搞怪'; sigh = '叹气'
}
$MmThumbDir = Join-Path ([IO.Path]::GetTempPath()) 'jiashu-gallery-thumbs'

Add-Type -AssemblyName System.Web.Extensions
$script:MmJson = New-Object System.Web.Script.Serialization.JavaScriptSerializer
$script:MmJson.MaxJsonLength = [int]::MaxValue

# 后台线程跑 memes.py（和人格微调同一个办法）。不抛异常：总是返回 { PeId, Text, Err }
$MemesBody = @'
$ErrorActionPreference = 'Stop'
$text = ''; $fail = ''
$out = [IO.Path]::Combine([IO.Path]::GetTempPath(), 'jiashu-memes-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = '__PY__'
    $quoted = @(@('-I', '__TOOL__') + @($PyArgs) + @('--out', $out) | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' })
    $psi.Arguments = $quoted -join ' '
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardOutput = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    $errTask = $p.StandardError.ReadToEndAsync()
    [void]$p.StandardOutput.ReadToEndAsync()
    if (-not $p.WaitForExit(600000)) {
        try { $p.Kill() } catch { }
        $fail = '超时（10 分钟），机器人可能卡住了。'
    } elseif ([IO.File]::Exists($out)) {
        $text = [IO.File]::ReadAllText($out, [Text.Encoding]::UTF8)
    } else {
        $fail = 'memes.py 没有输出结果：' + $errTask.Result
    }
} catch {
    $fail = $_.Exception.Message
} finally {
    try { if ([IO.File]::Exists($out)) { [IO.File]::Delete($out) } } catch { }
}
[pscustomobject]@{ PeId = $PeId; Text = $text; Err = $fail }
'@
$MemesBody = $MemesBody.Replace('__PY__', $PersonaPy).Replace('__TOOL__', $MemesTool)

$script:MM = @{ Cbs = @{}; Seq = 100000 }

$MmDone = {
    param($res, $err)
    $mm = $script:MM
    if (-not $res -or -not $mm.Cbs.ContainsKey([int]$res.PeId)) { return }
    $id = [int]$res.PeId
    $cb = $mm.Cbs[$id]
    $mm.Cbs.Remove($id)
    $mm.Busy--
    if (-not $mm.Form -or $mm.Form.IsDisposed) { return }
    $obj = $null
    if (-not $err) { $err = [string]$res.Err }
    if (-not $err) {
        try { $obj = $script:MmJson.DeserializeObject([string]$res.Text) } catch { $err = "看不懂 memes.py 的结果：$([string]$res.Text)" }
    }
    if (-not $err -and -not $obj['ok']) { $err = [string]$obj['error'] }
    try { & $cb $obj $err } catch { Set-MmStatus "出错了：$($_.Exception.Message)（第 $($_.InvocationInfo.ScriptLineNumber) 行）" 'bad' }
    Update-MmButtons
}

function Invoke-MemesTool([string[]]$pyArgs, [scriptblock]$done) {
    $mm = $script:MM
    $mm.Seq++
    $id = [int]$mm.Seq
    $mm.Cbs[$id] = $done
    $mm.Busy++
    Update-MmButtons
    Start-Work $MemesBody @{ PyArgs = $pyArgs; PeId = $id } $MmDone
}

# 跑一串改动，跑完重新读一遍
function Invoke-MmOps($ops, [string]$doing, [scriptblock]$after) {
    $mm = $script:MM
    if ($mm.Busy -gt 0) { return }
    if (-not $mm.Online) { Set-MmStatus '机器人没开：改表情包要通过表情包插件，先在主窗口点「让佳树上线」。现在只能看。' 'warn'; return }
    $file = [IO.Path]::Combine([IO.Path]::GetTempPath(), 'jiashu-memes-in-' + [guid]::NewGuid().ToString('N') + '.json')
    [IO.File]::WriteAllText($file, $script:MmJson.Serialize(@{ ops = @($ops) }), (New-Object System.Text.UTF8Encoding($false)))
    $mm.OpFile = $file
    $mm.After = $after
    Set-MmStatus "$doing…"
    Invoke-MemesTool @('apply', '--in', $file) {
        param($r, $err)
        $mm = $script:MM
        try { [IO.File]::Delete($mm.OpFile) } catch { }
        $results = if ($r) { @($r['results']) } else { @() }
        if ($mm.After) { try { & $mm.After $results } catch { } }
        if ($err) { Set-MmStatus "没全部做成：$err" 'bad'; $mm.KeepStatus = $true }
        Start-MmLoad
    }
}

function Set-MmStatus([string]$text, [string]$kind = 'info') {
    $s = $script:MM.Status
    $s.Text = $text
    $s.ForeColor = switch ($kind) { 'ok' { $Pal.GreenText } 'bad' { $Pal.RedText } 'warn' { $Pal.AmberText } default { $Pal.Sub } }
    $script:MM.Tips.SetToolTip($s, $text)
}

# System.Drawing 读不了 WebP：用 Windows 自带的 WIC 转成 PNG 存到临时目录（按路径+修改时间缓存）
function Get-MmViewable([string]$path) {
    if ([IO.Path]::GetExtension($path).ToLowerInvariant() -ne '.webp') { return $path }
    try {
        $fi = Get-Item -LiteralPath $path
        $md5 = [Security.Cryptography.MD5]::Create()
        $hash = -join ($md5.ComputeHash([Text.Encoding]::UTF8.GetBytes("$path|$($fi.LastWriteTimeUtc.Ticks)")) | ForEach-Object { $_.ToString('x2') })
        $png = Join-Path $MmThumbDir "$hash.png"
        if (-not [IO.File]::Exists($png)) {
            Add-Type -AssemblyName PresentationCore
            [void][IO.Directory]::CreateDirectory($MmThumbDir)
            $in = [IO.File]::OpenRead($path)
            try {
                $dec = [System.Windows.Media.Imaging.BitmapDecoder]::Create($in, 'None', 'OnLoad')
                $enc = New-Object System.Windows.Media.Imaging.PngBitmapEncoder
                $enc.Frames.Add([System.Windows.Media.Imaging.BitmapFrame]::Create($dec.Frames[0]))
                $out = [IO.File]::Create($png)
                try { $enc.Save($out) } finally { $out.Close() }
            } finally { $in.Close() }
        }
        return $png
    } catch { return $path }
}

function Get-MmShortName([string]$name) {
    $s = ($name -split ' · ')[0] -replace '\s*表情包$', ''
    if ($s) { return $s.Trim() }
    return $name
}

function Format-MmSize([double]$b) {
    if ($b -ge 1MB) { return ('{0:0.0} MB' -f ($b / 1MB)) }
    return ('{0:0} KB' -f [Math]::Max(1, $b / 1KB))
}

# 一个分类在她那里怎么样：@{ Visible; Alias(并进的大分类) }
function Get-MmCatState([string]$key) {
    $inv = $script:MM.Inv
    $main = $inv['aliases'][$key]
    if ($main -and $inv['visible'].ContainsKey($main)) { return @{ Visible = $true; Alias = [string]$main } }
    return @{ Visible = $inv['visible'].ContainsKey($key); Alias = '' }
}

# =====================================================================
#  读取 + 填列表
# =====================================================================
function Start-MmLoad {
    $mm = $script:MM
    if (-not $mm.KeepStatus) { Set-MmStatus '读取中…' }
    Invoke-MemesTool @('inventory') {
        param($r, $err)
        $mm = $script:MM
        if ($err) { Set-MmStatus "读取失败：$err" 'bad'; return }
        $mm.Inv = $r
        $mm.Online = [bool]$r['online']
        $mm.Packs = @($r['packs'])
        $mm.Trash = @($r['trash'])
        $mm.Shared = @($r['shared'])
        $mm.SharedMap = @{}
        foreach ($row in $mm.Shared) { $mm.SharedMap[[string]$row['key']] = $row }
        $mm.Primary = [string]$r['primary']
        $mm.PackNames = @{}
        $pics = 0; $used = 0
        foreach ($p in $mm.Packs) {
            $mm.PackNames[[string]$p['id']] = [string]$p['name']
            if ($p['in_use']) { $used++; $pics += @($p['items']).Count }
        }
        $keep = $mm.PackId
        if (-not $keep) { $keep = '*' }
        $mm.Syncing = $true
        $mm.Pack.Items.Clear()
        [void]$mm.Pack.Items.Add("全部表情包（共用一套分类）· $pics 张")
        $idx = 0
        for ($i = 0; $i -lt $mm.Packs.Count; $i++) {
            $p = $mm.Packs[$i]
            $tag = if ($p['primary']) { '★ ' } elseif (-not $p['in_use']) { '（没启用）' } else { '　' }
            [void]$mm.Pack.Items.Add("$tag$($p['name']) · $(@($p['items']).Count) 张")
            if ($p['id'] -eq $keep) { $idx = $i + 1 }
        }
        $mm.Pack.SelectedIndex = $idx
        $mm.Syncing = $false
        $mm.Sub.Text = "佳树现在能用 $used 个表情包、$pics 张图，所有包共用 $($mm.Shared.Count) 个分类（同义的已合并）。" +
            $(if ($mm.Online) { ' 机器人在线，可以直接改。' } else { ' 机器人没开：现在只能看，改动要先启动机器人。' })
        $mm.Sub.ForeColor = if ($mm.Online) { $Pal.Muted } else { $Pal.AmberText }
        $mm.BtnTrash.Text = "回收站（$($mm.Trash.Count)）"
        Fill-MmCats
        if (-not $mm.KeepStatus) { Set-MmStatus "已读取（$($r['seconds']) 秒）。" 'ok' }
        $mm.KeepStatus = $false
        $mm.Changed = $true
    }
}

# 下拉框第一项 = 全部表情包合在一起看（共用一套分类）；后面是单个包
function Test-MmShared { return ($script:MM.Pack.SelectedIndex -le 0) }
function Get-MmPack { $mm = $script:MM; $i = $mm.Pack.SelectedIndex; if ($i -ge 1) { return $mm.Packs[$i - 1] }; return $null }

# 当前视图里的图（共用视图 = 所有能用的包）
function Get-MmItems {
    $mm = $script:MM
    if (Test-MmShared) {
        foreach ($p in $mm.Packs) { if ($p['in_use']) { foreach ($it in @($p['items'])) { $it } } }
    } else {
        $p = Get-MmPack
        if ($p) { foreach ($it in @($p['items'])) { $it } }
    }
}

# 一张图在当前视图里属于哪些分类（共用视图里是合并后的用途）
function Get-MmItemKeys($it) {
    if (Test-MmShared) { return @($it['shared']) }
    return @($it['cats'].Keys)
}

function Get-MmPackShort([string]$id) { return (Get-MmShortName ([string]$script:MM.PackNames[$id])) }

# 左边分类表的行：@{ Key; Mean; Count; Desc; Tip; Muted }
function Get-MmRows {
    $mm = $script:MM
    if (Test-MmShared) {
        foreach ($row in $mm.Shared) {
            $key = [string]$row['key']
            $from = @(foreach ($packId in $row['members'].Keys) {
                $dirs = @($row['members'][$packId])
                $other = @($dirs | Where-Object { $_ -ne $key })
                $name = Get-MmPackShort $packId
                if ($other.Count) { "$name（叫 $($other -join '、')）" } else { $name }
            })
            $tip = if ($row['desc']) { "用途：$($row['desc'])" } else { '（没有描述）' }
            $tip += "`r`n来自：$($from -join '、')"
            if (-not $row['visible']) { $tip += "`r`n她看不到这个分类，这里的图她用不到。" }
            if ([int]$row['count'] -eq 0) { $tip += "`r`n现在是空的，空分类不会告诉她。" }
            @{ Key = $key; Mean = [string]$MmCn[$key]; Count = [int]$row['count']; Desc = [string]$row['desc']; Tip = $tip
               Muted = (-not $row['visible'] -or [int]$row['count'] -eq 0) }
        }
        return
    }
    $p = Get-MmPack
    if (-not $p) { return }
    foreach ($c in @($p['cats'])) {
        $key = [string]$c['key']
        $st = Get-MmCatState $key
        $cn = $MmCn[$key]
        $mean = if ($st.Alias) { "→ $($st.Alias)" } elseif ($cn) { $cn } else { '' }
        $tip = if ($c['desc']) { "用途：$($c['desc'])" } else { '（没有描述）' }
        if ($st.Alias) { $tip += "`r`n并进了「$($st.Alias)」：她写 $($st.Alias) 时，这里的图也会一起参与随机。" }
        elseif (-not $p['in_use']) { $tip += "`r`n这个包没启用，她用不到。" }
        elseif (-not $st.Visible) { $tip += "`r`n她看不到这个分类（没写进配置），这里的图她用不到。" }
        if ([int]$c['count'] -eq 0) { $tip += "`r`n现在是空的，空分类不会告诉她。" }
        @{ Key = $key; Mean = $mean; Count = [int]$c['count']; Desc = [string]$c['desc']; Tip = $tip
           Muted = (-not $p['in_use'] -or -not $st.Visible -or [int]$c['count'] -eq 0) }
    }
}

function Fill-MmCats {
    $mm = $script:MM
    $p = Get-MmPack
    $mm.PackId = if (Test-MmShared) { '*' } elseif ($p) { [string]$p['id'] } else { '' }
    $mm.Rows = @(Get-MmRows)
    $keep = $mm.Cat
    $mm.Syncing = $true
    $mm.Cats.BeginUpdate()
    $mm.Cats.Items.Clear()
    $all = New-Object System.Windows.Forms.ListViewItem($MmAllCats)
    [void]$all.SubItems.Add('')
    [void]$all.SubItems.Add([string]@(Get-MmItems).Count)
    $all.Tag = ''
    [void]$mm.Cats.Items.Add($all)
    $sel = $all
    foreach ($row in $mm.Rows) {
        $it = New-Object System.Windows.Forms.ListViewItem($row.Key)
        [void]$it.SubItems.Add($row.Mean)
        [void]$it.SubItems.Add([string]$row.Count)
        $it.ToolTipText = $row.Tip
        if ($row.Muted) { $it.ForeColor = $Pal.Muted }
        $it.Tag = $row.Key
        [void]$mm.Cats.Items.Add($it)
        if ($row.Key -eq $keep) { $sel = $it }
    }
    $mm.Cats.EndUpdate()
    $sel.Selected = $true
    $sel.EnsureVisible()
    $mm.Syncing = $false
    $mm.Cat = [string]$sel.Tag
    Fill-MmThumbs
}

function Fill-MmThumbs {
    $mm = $script:MM
    $keepSel = @{}
    foreach ($it in $mm.Thumbs.SelectedItems) { $keepSel[[string]$it.Name] = $true }
    $q = $mm.Search.Text.Trim()
    $mm.Thumbs.BeginUpdate()
    $mm.Thumbs.Items.Clear()
    $mm.Queue.Clear()
    $n = 0
    if ($mm.TrashMode) {
        $mm.CatTitle.Text = '回收站'
        $mm.CatDesc.Text = "删掉的图都在这里（$($mm.Inv['trash_dir'])），不会自己清掉。选中后可以恢复到原来的分类。"
        foreach ($t in $mm.Trash) {
            $cats = @($t['cats'].Keys)
            if ($q -and ("$($t['pack_name']) $($cats -join ' ') $($t['file'])").IndexOf($q, [StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
            $it = New-Object System.Windows.Forms.ListViewItem((Get-MmShortName ([string]$t['pack_name'])))
            $it.Name = [string]$t['id']
            $it.Tag = $t
            $it.ToolTipText = "$($t['pack_name']) / $($cats -join '、')`r`n删于 $(([string]$t['deleted_at']) -replace 'T', ' ')（$($t['reason'])）"
            [void]$mm.Thumbs.Items.Add($it)
            $mm.Queue.Enqueue($it)
            if ($keepSel.ContainsKey($it.Name)) { $it.Selected = $true }
            $n++
        }
        $mm.Empty.Text = '回收站是空的'
    } else {
        $shared = Test-MmShared
        $p = Get-MmPack
        $cat = $mm.Cat
        if ($cat) {
            $row = @($mm.Rows | Where-Object { $_.Key -eq $cat })[0]
            $cn = $MmCn[$cat]
            $mm.CatTitle.Text = if ($cn) { "$cat · $cn" } else { $cat }
            $mm.CatDesc.Text = if ($row -and $row.Desc) { "她看到的用途：$($row.Desc)" } else { '（这个分类没有描述）' }
        } elseif ($shared) {
            $mm.CatTitle.Text = '全部表情包 · 全部'
            $mm.CatDesc.Text = '所有包合在一起看，分类是共用的。图下面写着它来自哪个包。'
        } else {
            $mm.CatTitle.Text = "$($p['name']) · 全部"
            $mm.CatDesc.Text = '同一张图在几个分类里只算一张，图下面写着它在哪些分类。'
        }
        foreach ($item in @(Get-MmItems)) {
            $keys = @(Get-MmItemKeys $item)
            if ($cat -and $keys -notcontains $cat) { continue }
            $packShort = if ($shared) { Get-MmPackShort ([string]$item['pack']) } else { '' }
            if ($q -and ("$packShort $($keys -join ' ') $(@($item['cats'].Keys) -join ' ') $(@($item['cats'].Values) -join ' ')").IndexOf($q, [StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
            $others = @($keys | Where-Object { $_ -ne $cat })
            $label = if ($shared) {
                if ($cat) { $packShort + $(if ($others.Count) { ' +' + ($others -join '·') } else { '' }) } else { "$packShort · $($keys -join '·')" }
            } elseif ($cat) { $(if ($others.Count) { '+ ' + ($others -join '·') } else { '' }) } else { $keys -join '·' }
            $it = New-Object System.Windows.Forms.ListViewItem($label)
            $it.Name = [string]$item['pack'] + '|' + [string]$item['sha']
            $it.Tag = $item
            $where = if ($shared) { "$($mm.PackNames[[string]$item['pack']])`r`n" } else { '' }
            $it.ToolTipText = "$where分类：$($keys -join '、')`r`n$(Format-MmSize $item['size']) · $([IO.Path]::GetFileName([string]$item['path']))"
            [void]$mm.Thumbs.Items.Add($it)
            $mm.Queue.Enqueue($it)
            if ($keepSel.ContainsKey($it.Name)) { $it.Selected = $true }
            $n++
        }
        $mm.Empty.Text = if ($q) { "没有和「$q」对得上的图" } elseif ($cat) { "「$cat」里还没有图，点「＋ 添加图片」或者把图拖进来" } else { '这里还没有图' }
    }
    $mm.Thumbs.EndUpdate()
    $mm.Total = $n
    $mm.Empty.Visible = ($n -eq 0)
    Show-MmSelection
}

# 右边：所选图片的预览、信息、所在分类
function Show-MmSelection {
    $mm = $script:MM
    $sel = @($mm.Thumbs.SelectedItems | ForEach-Object { $_.Tag })
    $mm.Sel = $sel
    $n = $sel.Count
    $mm.Count.Text = if ($n) { "已选 $n / 共 $($mm.Total) 张" } else { "共 $($mm.Total) 张" }

    # 预览：读进内存再显示（不占着文件，删除时才不会失败），GIF 会自己动
    $old = $mm.Preview.Image
    $mm.Preview.Image = $null
    if ($old) { $old.Dispose() }
    if ($n -ge 1) {
        try {
            $bytes = [IO.File]::ReadAllBytes((Get-MmViewable ([string]$sel[0]['path'])))
            $mm.Preview.Image = [System.Drawing.Image]::FromStream((New-Object IO.MemoryStream(, $bytes)))
        } catch { }
    }

    $mm.Syncing = $true
    $mm.Checks.Items.Clear()
    $mm.CheckBase = @{}
    if ($mm.TrashMode) {
        $mm.ChecksLabel.Visible = $false; $mm.Checks.Visible = $false
        if ($n -eq 1) {
            $t = $sel[0]
            $mm.Info.Text = "来自：$($t['pack_name'])`r`n原来在：$(@($t['cats'].Keys) -join '、')`r`n删于 $(([string]$t['deleted_at']) -replace 'T', ' ')`r`n（$($t['reason'])）"
        } elseif ($n) { $mm.Info.Text = "选了 $n 张。恢复时各回各的包和分类。" }
        else { $mm.Info.Text = '点一张图看它原来在哪。' }
    } else {
        $mm.ChecksLabel.Visible = $true; $mm.Checks.Visible = $true
        if ($n -eq 1) {
            $it = $sel[0]
            $keys = @(Get-MmItemKeys $it)
            $from = if (Test-MmShared) { "来自：$($mm.PackNames[[string]$it['pack']])`r`n" } else { '' }
            $mm.Info.Text = "$from$([IO.Path]::GetFileName([string]$it['path']))`r`n$(Format-MmSize $it['size']) · 在 $($keys.Count) 个分类里"
        } elseif ($n) { $mm.Info.Text = "选了 $n 张。下面打勾 = 都在，方块 = 有的在。" }
        else { $mm.Info.Text = '点一张图：右边能看大图、改它属于哪些分类。可以 Ctrl / Shift 多选。' }
        if ($n) {
            $selKeys = @(foreach ($it in $sel) { , @(Get-MmItemKeys $it) })
            foreach ($row in $mm.Rows) {
                $key = $row.Key
                $have = @($selKeys | Where-Object { $_ -contains $key }).Count
                $state = if ($have -eq $n) { 'Checked' } elseif ($have) { 'Indeterminate' } else { 'Unchecked' }
                [void]$mm.Checks.Items.Add($(if ($row.Mean -and -not $row.Mean.StartsWith('→')) { "$key  $($row.Mean)" } else { $key }))
                $mm.Checks.SetItemCheckState($mm.Checks.Items.Count - 1, $state)
                $mm.CheckBase[$key] = $state
            }
        }
    }
    $mm.Syncing = $false
    Update-MmButtons
}

function Get-MmCheckKeys { return @($script:MM.Rows | ForEach-Object { $_.Key }) }

function Get-MmCheckChanges {
    $mm = $script:MM
    $add = @(); $remove = @()
    if ($mm.TrashMode -or -not $mm.Sel.Count) { return @{ Add = $add; Remove = $remove } }
    $keys = @(Get-MmCheckKeys)
    for ($i = 0; $i -lt $mm.Checks.Items.Count -and $i -lt $keys.Count; $i++) {
        $now = [string]$mm.Checks.GetItemCheckState($i)
        if ($now -eq $mm.CheckBase[$keys[$i]]) { continue }
        if ($now -eq 'Checked') { $add += $keys[$i] } elseif ($now -eq 'Unchecked') { $remove += $keys[$i] }
    }
    return @{ Add = $add; Remove = $remove }
}

function Update-MmButtons {
    $mm = $script:MM
    if (-not $mm.Form -or $mm.Form.IsDisposed) { return }
    $idle = ($mm.Busy -le 0)
    $can = $idle -and $mm.Online
    $n = @($mm.Sel).Count
    $view = (Test-MmShared) -or ($null -ne (Get-MmPack))
    foreach ($b in @($mm.BtnReload, $mm.BtnTrash, $mm.Pack)) { $b.Enabled = $idle }
    $mm.Search.Enabled = $true
    if ($mm.TrashMode) {
        $mm.BtnSave.Text = if ($n) { "恢复 $n 张" } else { '恢复' }
        $mm.BtnSave.Enabled = $can -and $n -gt 0
        $mm.BtnDelete.Text = '彻底删除'
        $mm.BtnDelete.Enabled = $idle -and $n -gt 0
        $mm.BtnAdd.Text = '清空回收站'
        Set-ButtonKind $mm.BtnAdd 'red'
        $mm.BtnAdd.Enabled = $idle -and $mm.Trash.Count -gt 0
        foreach ($b in @($mm.BtnCatNew, $mm.BtnCatEdit, $mm.BtnCatDel)) { $b.Enabled = $false }
        $mm.Cats.Enabled = $false
        $mm.BtnTrash.Text = '← 回到表情包'
    } else {
        $ch = Get-MmCheckChanges
        $dirty = ($ch.Add.Count + $ch.Remove.Count) -gt 0
        $mm.BtnSave.Text = if ($dirty) { '保存分类' } else { '保存分类（没改动）' }
        $mm.BtnSave.Enabled = $can -and $dirty
        $mm.BtnDelete.Text = if ($n -gt 1) { "删除 $n 张" } else { '删除' }
        $mm.BtnDelete.Enabled = $can -and $n -gt 0
        $mm.BtnAdd.Text = '＋ 添加图片…'
        Set-ButtonKind $mm.BtnAdd 'primary'
        $mm.BtnAdd.Enabled = $can -and $view
        $mm.BtnCatNew.Enabled = $can -and $view
        $mm.BtnCatEdit.Enabled = $can -and [bool]$mm.Cat
        $mm.BtnCatDel.Enabled = $can -and [bool]$mm.Cat
        $mm.Cats.Enabled = $idle
        $mm.BtnTrash.Text = "回收站（$(@($mm.Trash).Count)）"
    }
    $mm.BtnOpen.Enabled = ($n -gt 0)
    $mm.BtnSelAll.Enabled = ($mm.Total -gt 0)
    $mm.BtnSelAll.Text = if ($n -gt 0 -and $n -eq $mm.Total) { '取消全选' } else { '全选' }
}

# =====================================================================
#  改动
# =====================================================================
function Get-MmOpItems($sel) { return @($sel | ForEach-Object { @{ cats = $_['cats'] } }) }

# 共用分类在某个包里对应的目录（优先同名的；这个包还没有就用分类名本身，保存时会在那个包里建上）
function Get-MmDirFor([string]$key, [string]$packId) {
    $row = $script:MM.SharedMap[$key]
    if ($row -and $row['members'].ContainsKey($packId)) { return [string]@($row['members'][$packId])[0] }
    return $key
}
function Get-MmDirsFor([string]$key, [string]$packId) {
    $row = $script:MM.SharedMap[$key]
    if ($row -and $row['members'].ContainsKey($packId)) { return @($row['members'][$packId]) }
    return @($key)
}

# 把「加进 / 移出 / 只留在」翻译成每个包自己的操作：共用视图里选中的图可能来自好几个包
function New-MmCatOps($sel, $add, $remove, [string]$moveTo) {
    $mm = $script:MM
    if (-not (Test-MmShared)) {
        if ($moveTo) { return @{ op = 'move'; pack = $mm.PackId; items = @(Get-MmOpItems $sel); to = $moveTo } }
        return @{ op = 'set_cats'; pack = $mm.PackId; items = @(Get-MmOpItems $sel); add = @($add); remove = @($remove) }
    }
    $byPack = [ordered]@{}
    foreach ($it in $sel) {
        $packId = [string]$it['pack']
        if (-not $byPack.Contains($packId)) { $byPack[$packId] = New-Object System.Collections.ArrayList }
        [void]$byPack[$packId].Add($it)
    }
    foreach ($packId in $byPack.Keys) {
        $items = @(Get-MmOpItems @($byPack[$packId]))
        $descs = @{}
        if ($moveTo) {
            $to = Get-MmDirFor $moveTo $packId
            $descs[$to] = [string]$mm.SharedMap[$moveTo]['desc']
            @{ op = 'move'; pack = $packId; items = $items; to = $to; descs = $descs }
            continue
        }
        $a = @(foreach ($k in @($add)) { $d = Get-MmDirFor $k $packId; $descs[$d] = [string]$mm.SharedMap[$k]['desc']; $d })
        $r = @(foreach ($k in @($remove)) { Get-MmDirsFor $k $packId })
        @{ op = 'set_cats'; pack = $packId; items = $items; add = $a; remove = $r; descs = $descs }
    }
}

function New-MmTrashOps($sel) {
    $mm = $script:MM
    if (-not (Test-MmShared)) { return @{ op = 'trash'; pack = $mm.PackId; items = @(Get-MmOpItems $sel) } }
    $byPack = [ordered]@{}
    foreach ($it in $sel) {
        $packId = [string]$it['pack']
        if (-not $byPack.Contains($packId)) { $byPack[$packId] = New-Object System.Collections.ArrayList }
        [void]$byPack[$packId].Add($it)
    }
    foreach ($packId in $byPack.Keys) { @{ op = 'trash'; pack = $packId; items = @(Get-MmOpItems @($byPack[$packId])) } }
}

$MmOkDone = { param($results) if (@($results | Where-Object { $_['ok'] }).Count) { Set-MmStatus $script:MM.Note 'ok'; $script:MM.KeepStatus = $true } }

function Save-MmChecks {
    $mm = $script:MM
    $ch = Get-MmCheckChanges
    if (($ch.Add.Count + $ch.Remove.Count) -eq 0) { return }
    $sel = @($mm.Sel)
    # 哪些图会一个分类都不剩 → 进回收站，先说清楚
    $gone = 0
    foreach ($it in $sel) {
        $left = @(@(Get-MmItemKeys $it) | Where-Object { $ch.Remove -notcontains $_ }) + @($ch.Add)
        if (@($left | Where-Object { $_ }).Count -eq 0) { $gone++ }
    }
    if ($gone) {
        $ans = [System.Windows.Forms.MessageBox]::Show($mm.Form, "有 $gone 张会一个分类都不剩，等于删掉它们（会放进回收站，能恢复）。继续吗？", '保存分类', 'OKCancel', 'Warning')
        if ($ans -ne 'OK') { return }
    }
    $what = @()
    if ($ch.Add.Count) { $what += "加进 $($ch.Add -join '、')" }
    if ($ch.Remove.Count) { $what += "移出 $($ch.Remove -join '、')" }
    $mm.Note = "已把 $($sel.Count) 张" + ($what -join '，') + $(if ($gone) { "（$gone 张进了回收站）" } else { '' }) + '。'
    Invoke-MmOps @(New-MmCatOps $sel $ch.Add $ch.Remove '') '正在保存分类' $MmOkDone
}

function Move-MmTo([string]$cat, [bool]$keepOthers) {
    $mm = $script:MM
    $sel = @($mm.Sel)
    if (-not $sel.Count -or -not $cat) { return }
    $mm.Note = if ($keepOthers) { "已把 $($sel.Count) 张也加进「$cat」。" } else { "已把 $($sel.Count) 张移到「$cat」（只留在这一个分类）。" }
    $ops = if ($keepOthers) { @(New-MmCatOps $sel @($cat) @() '') } else { @(New-MmCatOps $sel @() @() $cat) }
    Invoke-MmOps $ops '正在移动' $MmOkDone
}

function Remove-MmSelected {
    $mm = $script:MM
    $sel = @($mm.Sel)
    if (-not $sel.Count -or $mm.Busy -gt 0) { return }
    if ($mm.TrashMode) {
        $ans = [System.Windows.Forms.MessageBox]::Show($mm.Form, "彻底删除这 $($sel.Count) 张？之后就找不回来了。", '彻底删除', 'YesNo', 'Warning', 'Button2')
        if ($ans -ne 'Yes') { return }
        $mm.Note = "已彻底删除 $($sel.Count) 张。"
        $ids = @($sel | ForEach-Object { [string]$_['id'] })
        # 彻底删除不需要机器人在线
        $mm.OnlineSave = $mm.Online; $mm.Online = $true
        Invoke-MmOps @(@{ op = 'purge'; ids = $ids }) '正在彻底删除' { param($results) Set-MmStatus $script:MM.Note 'ok'; $script:MM.KeepStatus = $true }
        $mm.Online = $mm.OnlineSave
        return
    }
    $where = if ($mm.Cat) { "（不只是从「$($mm.Cat)」里拿掉——它在所有分类里都会消失；只想移出这个分类的话，在右边取消勾选就行）" } else { '' }
    $ans = [System.Windows.Forms.MessageBox]::Show($mm.Form, "删除选中的 $($sel.Count) 张图？$where`r`n`r`n删掉的图会进回收站，能原样恢复。", '删除表情', 'YesNo', 'Question', 'Button2')
    if ($ans -ne 'Yes') { return }
    $mm.Note = "已删除 $($sel.Count) 张（在回收站里，能恢复）。"
    Invoke-MmOps @(New-MmTrashOps $sel) '正在删除' $MmOkDone
}

function Restore-MmSelected {
    $mm = $script:MM
    $sel = @($mm.Sel)
    if (-not $sel.Count) { return }
    $mm.Note = "已恢复 $($sel.Count) 张，回到了原来的分类。"
    Invoke-MmOps @(@{ op = 'restore'; ids = @($sel | ForEach-Object { [string]$_['id'] }) }) '正在恢复' $MmOkDone
}

function Clear-MmTrash {
    $mm = $script:MM
    if (-not $mm.Trash.Count) { return }
    $ans = [System.Windows.Forms.MessageBox]::Show($mm.Form, "清空回收站？里面 $($mm.Trash.Count) 张图会被彻底删除，找不回来。", '清空回收站', 'YesNo', 'Warning', 'Button2')
    if ($ans -ne 'Yes') { return }
    $mm.Note = '回收站已清空。'
    $mm.OnlineSave = $mm.Online; $mm.Online = $true
    Invoke-MmOps @(@{ op = 'purge_all' }) '正在清空回收站' { param($results) Set-MmStatus $script:MM.Note 'ok'; $script:MM.KeepStatus = $true }
    $mm.Online = $mm.OnlineSave
}

function Add-MmFiles([string[]]$paths) {
    $mm = $script:MM
    $paths = @($paths | Where-Object { $_ -and [IO.File]::Exists($_) -and ([IO.Path]::GetExtension($_).ToLowerInvariant() -in $ImageExts) })
    if (-not $paths.Count) { Set-MmStatus '没有可以加的图片（支持 png / jpg / gif / webp）。' 'warn'; return }
    if ($mm.TrashMode) { Set-MmStatus '先点「← 回到表情包」，再往分类里加图。' 'warn'; return }
    $cat = $mm.Cat
    if (-not $cat) {
        $cat = Show-MmPickCat "把 $($paths.Count) 张图加到哪个分类？" ''
        if (-not $cat) { return }
    }
    # 共用视图里加的图放进佳树表情包（排第一的包）
    $packId = $mm.PackId; $dir = $cat; $desc = ''
    if (Test-MmShared) {
        $packId = $mm.Primary
        $dir = Get-MmDirFor $cat $packId
        $desc = [string]$mm.SharedMap[$cat]['desc']
    }
    $mm.AddCat = $cat
    $mm.AddPack = Get-MmPackShort $packId
    Invoke-MmOps @(@{ op = 'add'; pack = $packId; cat = $dir; paths = $paths; desc = $desc }) "正在把 $($paths.Count) 张加到「$cat」" {
        param($results)
        $r = @($results)[0]
        if ($r -and $r['ok']) {
            $msg = "加到「$($script:MM.AddCat)」（$($script:MM.AddPack)）：成功 $($r['added']) 张"
            if ($r['dup']) { $msg += "，$($r['dup']) 张这个分类里本来就有" }
            $fail = @($r['fail'])
            if ($fail.Count) { $msg += "，失败 $($fail.Count) 张：$($fail -join '；')" }
            Set-MmStatus "$msg。" $(if ($fail.Count) { 'warn' } else { 'ok' })
            $script:MM.KeepStatus = $true
        }
    }
}

# 选一个分类（添加时在「全部」里用）
function Show-MmPickCat([string]$title, [string]$except) {
    $keys = @(Get-MmCheckKeys | Where-Object { $_ -ne $except })
    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = '选分类'
    $dlg.AutoScaleMode = 'None'
    $dlg.ClientSize = Sz 380 170
    $dlg.FormBorderStyle = 'FixedDialog'
    $dlg.MaximizeBox = $false; $dlg.MinimizeBox = $false; $dlg.ShowInTaskbar = $false
    $dlg.StartPosition = 'CenterParent'
    $dlg.BackColor = $Pal.Card
    $dlg.Font = Fnt 9
    $l = New-Label $title 20 16 340 26 (Fnt 10.5 'Bold') $Pal.Text
    $cb = New-Object System.Windows.Forms.ComboBox
    $cb.Location = Pt 20 54; $cb.Width = Px 340; $cb.DropDownStyle = 'DropDownList'; $cb.Font = Fnt 10; $cb.MaxDropDownItems = 16
    foreach ($k in $keys) { $cn = $MmCn[$k]; [void]$cb.Items.Add($(if ($cn) { "$k  $cn" } else { $k })) }
    if ($cb.Items.Count) { $cb.SelectedIndex = 0 }
    $ok = New-Button '确定' 270 110 90 38 'primary' 9.5
    $cancel = New-Button '取消' 172 110 90 38 'ghost' 9.5
    $dlg.Controls.AddRange(@($l, $cb, $ok, $cancel))
    $script:MmPicked = ''
    $ok.Add_Click({ if ($cb.SelectedIndex -ge 0) { $script:MmPicked = $keys[$cb.SelectedIndex] }; $dlg.Close() })
    $cancel.Add_Click({ $dlg.Close() })
    [void]$dlg.ShowDialog($script:MM.Form)
    $dlg.Dispose()
    return $script:MmPicked
}

# 新建分类 / 改名 + 改描述（$cat 为空 = 新建）。共用视图里改的是所有包的这个分类
function Show-MmCatDialog([string]$cat) {
    $mm = $script:MM
    $shared = Test-MmShared
    $p = Get-MmPack
    $isNew = -not $cat
    $row = if ($isNew) { $null } else { @($mm.Rows | Where-Object { $_.Key -eq $cat })[0] }
    $oldDesc = if ($row) { [string]$row.Desc } else { '' }
    $existing = @(Get-MmCheckKeys)

    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = if ($isNew) { '新建分类' } else { '改分类' }
    $dlg.AutoScaleMode = 'None'
    $dlg.ClientSize = Sz 440 320
    $dlg.FormBorderStyle = 'FixedDialog'
    $dlg.MaximizeBox = $false; $dlg.MinimizeBox = $false; $dlg.ShowInTaskbar = $false
    $dlg.StartPosition = 'CenterParent'
    $dlg.BackColor = $Pal.Card
    $dlg.Font = Fnt 9
    $dlg.KeyPreview = $true
    $head = if ($isNew -and $shared) { '新建一个共用分类' } elseif ($isNew) { "在「$(Get-MmShortName ([string]$p['name']))」里新建分类" } elseif ($shared) { "改共用分类「$cat」" } else { "改「$cat」" }
    $t = New-Label $head 24 16 392 26 (Fnt 11 'Bold') $Pal.Text
    $l1 = New-Label '分类名（她在回复里写 &&分类名&& 来发这类图）' 24 52 392 20 (Fnt 9) $Pal.Sub
    $name = New-Object System.Windows.Forms.TextBox
    $name.Location = Pt 24 74; $name.Width = Px 392; $name.Font = Fnt 10; $name.MaxLength = 40; $name.Text = $cat
    $l2 = New-Label '什么时候用这类表情（写给佳树看的说明）' 24 112 392 20 (Fnt 9) $Pal.Sub
    $desc = New-Object System.Windows.Forms.TextBox
    $desc.Location = Pt 24 134; $desc.Size = Sz 392 70; $desc.Font = Fnt 10; $desc.Multiline = $true; $desc.ScrollBars = 'Vertical'; $desc.MaxLength = 200
    $desc.Text = $oldDesc
    $note = if ($isNew -and $shared) { '建在「佳树表情包」里；别的包往这个分类加图时会自动建上，用同一句说明。' }
            elseif ($shared) { '改名、改说明会同时作用到所有包里的这个分类；同义的小分类（比如 food）会跟着指向新名字。' }
            elseif ($isNew) { '' } else { '只改这一个包。想所有包一起改，在表情包下拉框里选「全部表情包」再改。' }
    $warn = New-Label $note 24 210 392 36 (Fnt 8.5) $Pal.Muted 'TopLeft'
    $err = New-Label '' 24 246 392 22 (Fnt 9) $Pal.RedText
    $ok = New-Button $(if ($isNew) { '新建' } else { '保存' }) 326 270 90 38 'primary' 9.5
    $cancel = New-Button '取消' 228 270 90 38 'ghost' 9.5
    $dlg.Controls.AddRange(@($t, $l1, $name, $l2, $desc, $warn, $err, $ok, $cancel))
    $script:MmCatChoice = $null
    $accept = {
        $n = $name.Text
        $bad = Test-CategoryName $n
        if ($bad) { $err.Text = $bad; return }
        if ($n -ne $cat -and $existing -contains $n) { $err.Text = "已经有「$n」这个分类了。"; return }
        $d = ($desc.Text -replace '\s*[\r\n]+\s*', ' ').Trim()
        if (-not $d) { $err.Text = '写一句说明吧，佳树靠它判断什么时候发这类表情。'; return }
        $script:MmCatChoice = @{ Name = $n; Desc = $d }
        $dlg.Close()
    }
    $ok.Add_Click($accept)
    $cancel.Add_Click({ $dlg.Close() })
    $dlg.Add_KeyDown({ param($s, $e) if ($e.KeyCode -eq 'Escape') { $dlg.Close() } })
    $dlg.Add_Shown({ $name.Focus(); $name.SelectAll() })
    [void]$dlg.ShowDialog($mm.Form)
    $dlg.Dispose()
    $ch = $script:MmCatChoice
    if (-not $ch) { return }
    $mm.Cat = $ch.Name
    if ($isNew) {
        $mm.Note = "已新建「$($ch.Name)」。"
        $op = if ($shared) { @{ op = 'shared_create'; cat = $ch.Name; desc = $ch.Desc } } else { @{ op = 'cat_create'; pack = $mm.PackId; cat = $ch.Name; desc = $ch.Desc } }
        Invoke-MmOps @($op) '正在新建分类' $MmOkDone
        return
    }
    $ops = @()
    if ($ch.Name -ne $cat) { $ops += $(if ($shared) { @{ op = 'shared_rename'; cat = $cat; new = $ch.Name } } else { @{ op = 'cat_rename'; pack = $mm.PackId; cat = $cat; new = $ch.Name } }) }
    if ($ch.Desc -ne $oldDesc.Trim()) { $ops += $(if ($shared) { @{ op = 'shared_desc'; cat = $ch.Name; desc = $ch.Desc } } else { @{ op = 'cat_desc'; pack = $mm.PackId; cat = $ch.Name; desc = $ch.Desc } }) }
    if (-not $ops.Count) { return }
    $mm.Note = "已保存「$($ch.Name)」" + $(if ($shared) { '（所有包一起改了）' } else { '' }) + '。'
    Invoke-MmOps $ops '正在保存分类' { param($results) if (-not @($results | Where-Object { -not $_['ok'] }).Count) { Set-MmStatus $script:MM.Note 'ok'; $script:MM.KeepStatus = $true } }
}

function Remove-MmCat {
    $mm = $script:MM
    $cat = $mm.Cat
    if (-not $cat) { return }
    $shared = Test-MmShared
    $inCat = @(@(Get-MmItems) | Where-Object { @(Get-MmItemKeys $_) -contains $cat })
    $only = @($inCat | Where-Object { @(Get-MmItemKeys $_).Count -eq 1 }).Count
    $kept = $inCat.Count - $only
    $msg = if ($shared) { "删除共用分类「$cat」？所有包里的这个分类（包括并进来的同义分类）都会删掉。" } else { "删除分类「$cat」？" }
    if ($inCat.Count) {
        $msg += "`r`n`r`n· $only 张只在这个分类里 → 进回收站（能恢复，恢复时会把分类建回来）"
        if ($kept) { $msg += "`r`n· $kept 张在别的分类里也有 → 保留，只是不再属于「$cat」" }
    } else { $msg += '（里面没有图）' }
    $ans = [System.Windows.Forms.MessageBox]::Show($mm.Form, $msg, '删除分类', 'YesNo', 'Warning', 'Button2')
    if ($ans -ne 'Yes') { return }
    $mm.Cat = ''
    $mm.Note = "已删除分类「$cat」" + $(if ($only) { "，$only 张进了回收站" } else { '' }) + '。'
    $op = if ($shared) { @{ op = 'shared_delete'; cat = $cat } } else { @{ op = 'cat_delete'; pack = $mm.PackId; cat = $cat } }
    Invoke-MmOps @($op) '正在删除分类' $MmOkDone
}

function Open-MmSelected([bool]$reveal) {
    $it = @($script:MM.Sel)[0]
    if (-not $it) { return }
    $path = [string]$it['path']
    try {
        if ($reveal) { Start-Process explorer.exe -ArgumentList "/select,`"$path`"" } else { Start-Process -FilePath $path }
    } catch { }
}

function Set-MmTrashMode([bool]$on) {
    $mm = $script:MM
    $mm.TrashMode = $on
    $mm.Thumbs.SelectedItems.Clear()
    $mm.Search.Text = ''
    Fill-MmThumbs
}

# =====================================================================
#  窗口
# =====================================================================
function Show-MemeManager {
    $mm = @{ Cbs = @{}; Seq = [int]$script:MM.Seq; Busy = 0; Queue = (New-Object System.Collections.Queue); Syncing = $false
             Packs = @(); Trash = @(); Sel = @(); Cat = ''; PackId = ''; TrashMode = $false; Online = $false; Total = 0
             CheckBase = @{}; KeepStatus = $false; Changed = $false; Rows = @(); Shared = @(); SharedMap = @{}; PackNames = @{}; Primary = 'kaju_memes'; Tips = (New-Object System.Windows.Forms.ToolTip) }
    $script:MM = $mm

    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = '表情包管理'
    $dlg.AutoScaleMode = 'None'
    $dlg.ClientSize = Sz 1040 690
    $dlg.FormBorderStyle = 'FixedDialog'
    $dlg.MaximizeBox = $false
    $dlg.MinimizeBox = $true
    $dlg.ShowInTaskbar = $true
    $dlg.StartPosition = 'CenterParent'
    $dlg.BackColor = $Pal.Bg
    $dlg.Font = Fnt 9
    $dlg.KeyPreview = $true
    $dlg.AllowDrop = $true
    if ($form.Icon) { $dlg.Icon = $form.Icon }
    $mm.Form = $dlg

    $title = New-Label '表情包管理' 24 14 300 32 (Fnt 15 'Bold') $Pal.Text
    $mm.Sub = New-Label '读取中…' 25 46 990 20 (Fnt 9) $Pal.Muted
    $mm.Sub.AutoEllipsis = $true
    $l1 = New-Label '表情包' 24 80 52 30 (Fnt 9.5) $Pal.Sub
    $mm.Pack = New-Object System.Windows.Forms.ComboBox
    $mm.Pack.Location = Pt 78 82
    $mm.Pack.Width = Px 300
    $mm.Pack.DropDownStyle = 'DropDownList'
    $mm.Pack.Font = Fnt 9.5
    $mm.Pack.MaxDropDownItems = 16
    $l2 = New-Label '搜索' 396 80 38 30 (Fnt 9.5) $Pal.Sub
    $mm.Search = New-Object System.Windows.Forms.TextBox
    $mm.Search.Location = Pt 436 84
    $mm.Search.Width = Px 200
    $mm.Search.Font = Fnt 9.5
    $mm.BtnTrash = New-Button '回收站（0）' 780 78 128 34 'ghost' 9.5
    $mm.BtnReload = New-Button '刷新' 916 78 100 34 'ghost' 9.5
    $dlg.Controls.AddRange(@($title, $mm.Sub, $l1, $mm.Pack, $l2, $mm.Search, $mm.BtnTrash, $mm.BtnReload))
    $mm.Tips.SetToolTip($mm.Search, '按分类名、文件名筛选')

    # ----- 左：分类 -----
    $left = New-Card 24 124 240 520
    $mm.Cats = New-Object System.Windows.Forms.ListView
    $mm.Cats.Location = Pt 10 10
    $mm.Cats.Size = Sz 220 452
    $mm.Cats.View = 'Details'
    $mm.Cats.FullRowSelect = $true
    $mm.Cats.MultiSelect = $false
    $mm.Cats.HideSelection = $false
    $mm.Cats.HeaderStyle = 'Nonclickable'
    $mm.Cats.BorderStyle = 'None'
    $mm.Cats.ShowItemToolTips = $true
    $mm.Cats.Font = Fnt 9
    $mm.Cats.BackColor = $Pal.Card
    [void]$mm.Cats.Columns.Add('分类', (Px 92))
    [void]$mm.Cats.Columns.Add('意思', (Px 62))
    [void]$mm.Cats.Columns.Add('张', (Px 36), 'Right')
    $mm.BtnCatNew = New-Button '＋ 新建' 10 470 70 36 'ghost' 9
    $mm.BtnCatEdit = New-Button '改名 / 描述' 84 470 84 36 'ghost' 8.5
    $mm.BtnCatDel = New-Button '删除' 172 470 58 36 'ghost' 9
    $left.Controls.AddRange(@($mm.Cats, $mm.BtnCatNew, $mm.BtnCatEdit, $mm.BtnCatDel))
    $mm.Tips.SetToolTip($mm.BtnCatDel, '删除选中的分类：只在这个分类里的图进回收站')

    # ----- 中：缩略图 -----
    $mid = New-Card 276 124 480 520
    $mm.CatTitle = New-Label '' 16 10 448 26 (Fnt 11.5 'Bold') $Pal.Text
    $mm.CatTitle.AutoEllipsis = $true
    $mm.CatDesc = New-Label '' 16 36 448 20 (Fnt 8.5) $Pal.Sub
    $mm.CatDesc.AutoEllipsis = $true
    $box = New-Object JiashuUi.Card
    $box.Location = Pt 12 62
    $box.Size = Sz 456 398
    $box.Radius = Px 12
    $box.Fill = $Pal.DropFill
    $box.Border = $Pal.Line
    $mm.Images = New-Object System.Windows.Forms.ImageList
    $mm.Images.ColorDepth = 'Depth32Bit'
    $mm.Images.ImageSize = New-Object System.Drawing.Size((Px 72), (Px 72))
    $mm.Thumbs = New-Object JiashuUi.ThumbList
    $mm.Thumbs.Location = Pt 8 8
    $mm.Thumbs.Size = Sz 440 382
    $mm.Thumbs.View = 'LargeIcon'
    $mm.Thumbs.LargeImageList = $mm.Images
    $mm.Thumbs.BorderStyle = 'None'
    $mm.Thumbs.BackColor = $Pal.DropFill
    $mm.Thumbs.ForeColor = $Pal.Sub
    $mm.Thumbs.Font = Fnt 8
    $mm.Thumbs.MultiSelect = $true
    $mm.Thumbs.HideSelection = $false
    $mm.Thumbs.ShowItemToolTips = $true
    $mm.Thumbs.AllowDrop = $true
    $mm.Thumbs.SetSpacing((Px 104), (Px 104))
    $mm.Empty = New-Label '' 0 170 456 40 (Fnt 10) $Pal.Muted 'MiddleCenter'
    $mm.Empty.Visible = $false
    $box.Controls.AddRange(@($mm.Empty, $mm.Thumbs))
    $mm.Empty.BringToFront()
    $mm.Count = New-Label '' 16 468 220 36 (Fnt 9) $Pal.Sub
    $mm.BtnSelAll = New-Button '全选' 240 468 76 36 'ghost' 9
    $mm.BtnAdd = New-Button '＋ 添加图片…' 322 468 146 36 'primary' 9.5
    $mid.Controls.AddRange(@($mm.CatTitle, $mm.CatDesc, $box, $mm.Count, $mm.BtnSelAll, $mm.BtnAdd))

    $menu = New-Object System.Windows.Forms.ContextMenuStrip
    $miOpen = $menu.Items.Add('打开大图')
    $miReveal = $menu.Items.Add('在文件夹中显示')
    $miSep = $menu.Items.Add('-')
    $miMove = New-Object System.Windows.Forms.ToolStripMenuItem('移动到（只留这一个分类）')
    $miAlso = New-Object System.Windows.Forms.ToolStripMenuItem('也加到')
    [void]$menu.Items.Add($miMove)
    [void]$menu.Items.Add($miAlso)
    [void]$menu.Items.Add('-')
    $miDel = $menu.Items.Add('删除（进回收站）')
    $mm.Thumbs.ContextMenuStrip = $menu

    # ----- 右：预览 + 所在分类 -----
    $right = New-Card 768 124 248 520
    $pv = New-Object JiashuUi.Card
    $pv.Location = Pt 14 12
    $pv.Size = Sz 220 160
    $pv.Radius = Px 12
    $pv.Fill = $Pal.DropFill
    $pv.Border = $Pal.Line
    $mm.Preview = New-Object System.Windows.Forms.PictureBox
    $mm.Preview.Location = Pt 6 6
    $mm.Preview.Size = Sz 208 148
    $mm.Preview.SizeMode = 'Zoom'
    $mm.Preview.BackColor = $Pal.DropFill
    $mm.Preview.Cursor = [System.Windows.Forms.Cursors]::Hand
    $pv.Controls.Add($mm.Preview)
    $mm.Info = New-Label '' 14 178 220 58 (Fnt 8.5) $Pal.Sub 'TopLeft'
    $mm.ChecksLabel = New-Label '所在分类（勾几个就在几个分类里）' 14 238 220 20 (Fnt 8.5 'Bold') $Pal.Sub
    $mm.Checks = New-Object System.Windows.Forms.CheckedListBox
    $mm.Checks.Location = Pt 14 260
    $mm.Checks.Size = Sz 220 152
    $mm.Checks.IntegralHeight = $false
    $mm.Checks.CheckOnClick = $true
    $mm.Checks.Font = Fnt 9
    $mm.Checks.BorderStyle = 'FixedSingle'
    $mm.BtnSave = New-Button '保存分类' 14 418 220 36 'primary' 9.5
    $mm.BtnDelete = New-Button '删除' 14 462 104 40 'red' 9.5
    $mm.BtnOpen = New-Button '看大图' 130 462 104 40 'ghost' 9.5
    $right.Controls.AddRange(@($pv, $mm.Info, $mm.ChecksLabel, $mm.Checks, $mm.BtnSave, $mm.BtnDelete, $mm.BtnOpen))
    $mm.Tips.SetToolTip($mm.BtnDelete, '整张图删掉（所有分类里都没了），放进回收站。Delete 键也行')

    $mm.Status = New-Label '' 24 652 992 28 (Fnt 9) $Pal.Sub
    $mm.Status.AutoEllipsis = $true
    $dlg.Controls.AddRange(@($left, $mid, $right, $mm.Status))

    # ----- 事件 -----
    $mm.Pack.Add_SelectedIndexChanged({ $m = $script:MM; if (-not $m.Syncing) { $m.Cat = ''; $m.Thumbs.SelectedItems.Clear(); Fill-MmCats } })
    $mm.Cats.Add_SelectedIndexChanged({
        $m = $script:MM
        if ($m.Syncing -or -not $m.Cats.SelectedItems.Count) { return }
        $m.Cat = [string]$m.Cats.SelectedItems[0].Tag
        if ($m.TrashMode) { $m.TrashMode = $false }
        Fill-MmThumbs
    })
    $mm.Search.Add_TextChanged({ $script:MM.SearchAt = Get-Date; $script:MM.SearchDirty = $true })
    $mm.Thumbs.Add_SelectedIndexChanged({ $script:MM.SelDirty = $true })
    $mm.Thumbs.Add_DoubleClick({ Open-MmSelected $false })
    $mm.Thumbs.Add_KeyDown({
        param($s, $e)
        if ($e.KeyCode -eq 'Delete') { Remove-MmSelected; $e.Handled = $true }
        elseif ($e.Control -and $e.KeyCode -eq 'A') { foreach ($it in $script:MM.Thumbs.Items) { $it.Selected = $true }; $e.Handled = $true }
    })
    $mm.Checks.Add_ItemCheck({ if (-not $script:MM.Syncing) { $script:MM.CheckDirty = $true } })
    $mm.Preview.Add_Click({ Open-MmSelected $false })
    $mm.BtnOpen.Add_Click({ Open-MmSelected $false })
    $mm.BtnSave.Add_Click({ if ($script:MM.TrashMode) { Restore-MmSelected } else { Save-MmChecks } })
    $mm.BtnDelete.Add_Click({ Remove-MmSelected })
    $mm.BtnAdd.Add_Click({
        if ($script:MM.TrashMode) { Clear-MmTrash; return }
        $ofd = New-Object System.Windows.Forms.OpenFileDialog
        $ofd.Filter = '图片 (*.png;*.jpg;*.jpeg;*.gif;*.webp)|*.png;*.jpg;*.jpeg;*.gif;*.webp'
        $ofd.Multiselect = $true
        if ($ofd.ShowDialog($script:MM.Form) -eq 'OK') { Add-MmFiles $ofd.FileNames }
    })
    $mm.BtnSelAll.Add_Click({
        $m = $script:MM
        $all = ($m.Thumbs.SelectedItems.Count -lt $m.Thumbs.Items.Count)
        $m.Thumbs.BeginUpdate()
        foreach ($it in $m.Thumbs.Items) { $it.Selected = $all }
        $m.Thumbs.EndUpdate()
        $m.Thumbs.Focus()
    })
    $mm.BtnTrash.Add_Click({ Set-MmTrashMode (-not $script:MM.TrashMode) })
    $mm.BtnReload.Add_Click({ Start-MmLoad })
    $mm.BtnCatNew.Add_Click({ Show-MmCatDialog '' })
    $mm.BtnCatEdit.Add_Click({ Show-MmCatDialog $script:MM.Cat })
    $mm.BtnCatDel.Add_Click({ Remove-MmCat })
    $mm.Cats.Add_DoubleClick({ if ($script:MM.Cat -and $script:MM.Online) { Show-MmCatDialog $script:MM.Cat } })

    $miOpen.Add_Click({ Open-MmSelected $false })
    $miReveal.Add_Click({ Open-MmSelected $true })
    $miDel.Add_Click({ Remove-MmSelected })
    $menu.Add_Opening({
        param($s, $e)
        $m = $script:MM
        if (-not $m.Sel.Count) { $e.Cancel = $true; return }
        $writable = $m.Online -and $m.Busy -le 0 -and -not $m.TrashMode
        $m.MiMove.Visible = -not $m.TrashMode; $m.MiAlso.Visible = -not $m.TrashMode; $m.MiReveal.Visible = -not $m.TrashMode
        $m.MiMove.Enabled = $writable; $m.MiAlso.Enabled = $writable; $m.MiDel.Enabled = ($m.Busy -le 0) -and ($m.Online -or $m.TrashMode)
        $m.MiDel.Text = if ($m.TrashMode) { '彻底删除' } else { '删除（进回收站）' }
        foreach ($sub in @($m.MiMove, $m.MiAlso)) {
            $sub.DropDownItems.Clear()
            foreach ($k in (Get-MmCheckKeys)) {
                $cn = $MmCn[$k]
                $x = New-Object System.Windows.Forms.ToolStripMenuItem($(if ($cn) { "$k  $cn" } else { $k }))
                $x.Tag = $k
                if ($sub -eq $m.MiMove) { $x.Add_Click({ param($s2, $e2) Move-MmTo ([string]$s2.Tag) $false }) }
                else { $x.Add_Click({ param($s2, $e2) Move-MmTo ([string]$s2.Tag) $true }) }
                [void]$sub.DropDownItems.Add($x)
            }
        }
    })
    $mm.MiMove = $miMove; $mm.MiAlso = $miAlso; $mm.MiDel = $miDel; $mm.MiReveal = $miReveal

    # 拖图片进窗口 = 加到当前分类
    $dEnter = {
        param($s, $e)
        if ($e.Data.GetDataPresent([System.Windows.Forms.DataFormats]::FileDrop)) { $e.Effect = [System.Windows.Forms.DragDropEffects]::Copy }
        else { $e.Effect = [System.Windows.Forms.DragDropEffects]::None }
    }
    $dDrop = { param($s, $e) Add-MmFiles @($e.Data.GetData([System.Windows.Forms.DataFormats]::FileDrop)) }
    foreach ($c in @($dlg, $mm.Thumbs)) { $c.Add_DragEnter($dEnter); $c.Add_DragDrop($dDrop) }

    # 定时器：缩略图分批生成、选择变化和搜索稍等一下再刷新（不卡）
    $tick = New-Object System.Windows.Forms.Timer
    $tick.Interval = 40
    $tick.Add_Tick({
        $m = $script:MM
        if ($m.SelDirty) { $m.SelDirty = $false; Show-MmSelection }
        if ($m.CheckDirty) { $m.CheckDirty = $false; Update-MmButtons }
        if ($m.SearchDirty -and ((Get-Date) - $m.SearchAt).TotalMilliseconds -gt 300) { $m.SearchDirty = $false; Fill-MmThumbs }
        $k = 0
        while ($m.Queue.Count -gt 0 -and $k -lt 10) {
            $it = $m.Queue.Dequeue()
            $k++
            if (-not $it.ListView) { continue }
            $path = [string]$it.Tag['path']
            try {
                if (-not $m.Images.Images.ContainsKey($path)) {
                    $m.Images.Images.Add($path, [JiashuUi.Gfx]::Thumb((Get-MmViewable $path), $m.Images.ImageSize.Width, $Pal.White, $Pal.Muted, (Fnt 10 'Bold')))
                }
                $it.ImageKey = $path
            } catch { }
        }
    })
    $mm.Tick = $tick
    $dlg.Add_Shown({ $script:MM.Tick.Start(); Start-MmLoad })
    $dlg.Add_FormClosing({
        param($s, $e)
        if ($script:MM.Busy -gt 0) {
            [void][System.Windows.Forms.MessageBox]::Show($script:MM.Form, '还在处理上一个操作，等它做完再关。', '表情包管理', 'OK', 'Information')
            $e.Cancel = $true
        }
    })

    Update-MmButtons
    [void]$dlg.ShowDialog($form)
    $tick.Stop(); $tick.Dispose()
    if ($mm.Preview.Image) { $mm.Preview.Image.Dispose() }
    $mm.Images.Dispose()
    $dlg.Dispose()
    $script:MM.Form = $null
    return $mm.Changed
}
