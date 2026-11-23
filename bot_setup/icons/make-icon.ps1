# 画佳树控制台的图标：一个樱花粉的小蝴蝶结（2026-11-23，兄长选的“蝴蝶结、不带开关记号”）
# 在 256×256 上用矢量画好，再缩成各个尺寸，打成一个 PNG 压缩的 .ico。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File make-icon.ps1                 生成 panel.ico（覆盖）
#   powershell -NoProfile -ExecutionPolicy Bypass -File make-icon.ps1 -Preview x.png  另外存一张各尺寸并排的预览图
# 改颜色 / 形状改下面的 $C 和 Draw-Bow 就行。

param(
    [string]$Out = (Join-Path $PSScriptRoot 'panel.ico'),
    [string]$Preview = ''
)

Add-Type -AssemblyName System.Drawing

function C([int]$r, [int]$g, [int]$b, [int]$a = 255) { [System.Drawing.Color]::FromArgb($a, $r, $g, $b) }

# 和控制台 $Pal 一个色系
$C = @{
    Loop      = C 232 120 146     # 蝴蝶结主体
    LoopDeep  = C 205 92 120      # 圈里折进去的那一面
    Tail      = C 214 100 128     # 两条飘带
    Knot      = C 196 82 110      # 中间的结
    Line      = C 150 56 82       # 描边
    Shine     = C 255 255 255 150 # 高光
}

function New-Path { New-Object System.Drawing.Drawing2D.GraphicsPath }

function Add-Mirror($path) {
    # 以 x = 128 左右翻过来
    $m = New-Object System.Drawing.Drawing2D.Matrix(-1, 0, 0, 1, 256, 0)
    $p2 = $path.Clone()
    $p2.Transform($m)
    return $p2
}

function Draw-Bow([System.Drawing.Graphics]$g) {
    $g.SmoothingMode = 'AntiAlias'
    $g.PixelOffsetMode = 'HighQuality'
    $lineW = 7
    $pen = New-Object System.Drawing.Pen($C.Line, $lineW)
    $pen.LineJoin = 'Round'
    $pen.StartCap = 'Round'; $pen.EndCap = 'Round'

    # 飘带（在后面）：从结下面斜着垂下去，末端剪成燕尾
    $tail = New-Path
    $tail.AddPolygon([System.Drawing.PointF[]]@(
        (New-Object System.Drawing.PointF(116, 132)),
        (New-Object System.Drawing.PointF(72, 214)),
        (New-Object System.Drawing.PointF(94, 206)),
        (New-Object System.Drawing.PointF(104, 230)),
        (New-Object System.Drawing.PointF(140, 142))))
    foreach ($p in @($tail, (Add-Mirror $tail))) {
        $g.FillPath((New-Object System.Drawing.SolidBrush($C.Tail)), $p)
        $g.DrawPath($pen, $p)
    }

    # 两个圈
    $loop = New-Path
    $loop.AddBezier(118, 102, 84, 46, 18, 40, 14, 100)
    $loop.AddBezier(14, 100, 10, 156, 72, 174, 118, 138)
    $loop.CloseFigure()
    $fold = New-Path
    $fold.AddBezier(116, 112, 92, 88, 56, 90, 50, 118)
    $fold.AddBezier(50, 118, 66, 132, 96, 134, 116, 128)
    $fold.CloseFigure()
    $shine = New-Path
    $shine.AddBezier(36, 90, 44, 76, 60, 70, 76, 72)
    foreach ($pair in @(@($loop, $fold, $shine), @((Add-Mirror $loop), (Add-Mirror $fold), (Add-Mirror $shine)))) {
        $g.FillPath((New-Object System.Drawing.SolidBrush($C.Loop)), $pair[0])
        $g.FillPath((New-Object System.Drawing.SolidBrush($C.LoopDeep)), $pair[1])
        $g.DrawPath($pen, $pair[0])
        $sp = New-Object System.Drawing.Pen($C.Shine, 9)
        $sp.StartCap = 'Round'; $sp.EndCap = 'Round'
        $g.DrawPath($sp, $pair[2])
    }

    # 中间的结：圆角小方块
    $knot = New-Path
    $x = 106; $y = 96; $w = 44; $h = 50; $r = 16
    $knot.AddArc($x, $y, $r, $r, 180, 90)
    $knot.AddArc($x + $w - $r, $y, $r, $r, 270, 90)
    $knot.AddArc($x + $w - $r, $y + $h - $r, $r, $r, 0, 90)
    $knot.AddArc($x, $y + $h - $r, $r, $r, 90, 90)
    $knot.CloseFigure()
    $g.FillPath((New-Object System.Drawing.SolidBrush($C.Knot)), $knot)
    $g.DrawPath($pen, $knot)
    $ks = New-Object System.Drawing.Pen($C.Shine, 6)
    $ks.StartCap = 'Round'; $ks.EndCap = 'Round'
    $g.DrawLine($ks, 116, 108, 128, 106)
}

function New-Frame([int]$size, [System.Drawing.Bitmap]$master) {
    $bmp = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = 'HighQualityBicubic'
    $g.PixelOffsetMode = 'HighQuality'
    $g.SmoothingMode = 'AntiAlias'
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.DrawImage($master, (New-Object System.Drawing.Rectangle(0, 0, $size, $size)))
    $g.Dispose()
    return $bmp
}

# 先在 4 倍大小上画，再缩到 256，边缘更顺
$big = New-Object System.Drawing.Bitmap(1024, 1024, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($big)
$g.Clear([System.Drawing.Color]::Transparent)
$g.ScaleTransform(4, 4)
$g.TranslateTransform(0, -7)   # 整体往上挪一点，上下居中
Draw-Bow $g
$g.Dispose()
$master = New-Frame 256 $big

$sizes = @(16, 20, 24, 32, 40, 48, 64, 128, 256)
$pngs = @()
foreach ($s in $sizes) {
    $f = if ($s -eq 256) { $master } else { New-Frame $s $master }
    $ms = New-Object IO.MemoryStream
    $f.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $pngs += , $ms.ToArray()
}

# ICO：6 字节文件头 + 每张 16 字节目录 + PNG 数据
$ico = New-Object IO.MemoryStream
$bw = [IO.BinaryWriter]::new($ico)
$bw.Write([UInt16]0); $bw.Write([UInt16]1); $bw.Write([UInt16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $s = $sizes[$i]; $d = $pngs[$i]
    $bw.Write([byte]($s % 256)); $bw.Write([byte]($s % 256))
    $bw.Write([byte]0); $bw.Write([byte]0)
    $bw.Write([UInt16]1); $bw.Write([UInt16]32)
    $bw.Write([UInt32]$d.Length); $bw.Write([UInt32]$offset)
    $offset += $d.Length
}
foreach ($d in $pngs) { $bw.Write($d) }
$bw.Flush()
[IO.File]::WriteAllBytes($Out, $ico.ToArray())
"wrote $Out ($($ico.Length) bytes, sizes $($sizes -join ','))"

if ($Preview) {
    # 浅底和深底各一排，看任务栏 / 桌面两种背景下认不认得出
    $show = @(16, 24, 32, 48, 64, 128, 256)
    $W = 40 + ($show | Measure-Object -Sum).Sum + 24 * $show.Count
    $pv = [System.Drawing.Bitmap]::new([int]$W, 592)
    $pg = [System.Drawing.Graphics]::FromImage($pv)
    $pg.InterpolationMode = 'NearestNeighbor'
    foreach ($row in @(@(0, (C 250 245 241)), @(296, (C 32 32 36)))) {
        $pg.FillRectangle((New-Object System.Drawing.SolidBrush($row[1])), 0, $row[0], $W, 296)
        $x = 20
        foreach ($s in $show) {
            $f = New-Frame $s $master
            $pg.DrawImage($f, $x, $row[0] + 20 + (256 - $s), $s, $s)
            $x += $s + 24
        }
    }
    $pg.Dispose()
    $pv.Save($Preview, [System.Drawing.Imaging.ImageFormat]::Png)
    "preview $Preview"
}
