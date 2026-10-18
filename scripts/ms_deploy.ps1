param([string]$Token = "ms-3a46b6f3-c73d-41a2-9873-535d0ac55fef")
$ErrorActionPreference = 'Continue'
$base = 'https://modelscope.cn/openapi/v1'
$owner = 'cyhkbl'
$repo = 'hongjian'
$auth = "Bearer $Token"

function Api($m, $u, $b) {
    $tmp = Join-Path $env:TEMP ('ms_' + [guid]::NewGuid().ToString('N') + '.json')
    try {
        if ($null -ne $b) {
            [IO.File]::WriteAllText($tmp, ($b | ConvertTo-Json -Depth 6 -Compress), [Text.UTF8Encoding]::new($false))
            return Invoke-RestMethod -Method $m -Uri "$base/$u" -Headers @{ Authorization = $auth } -Body ([IO.File]::ReadAllText($tmp)) -ContentType 'application/json' -UseBasicParsing
        }
        return Invoke-RestMethod -Method $m -Uri "$base/$u" -Headers @{ Authorization = $auth } -UseBasicParsing
    } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
}

Write-Output '=== 部署'
$r = Api POST "studios/$owner/$repo/deploy" $null
Write-Output ($r | ConvertTo-Json -Compress)

Start-Sleep -Seconds 20
for ($i = 0; $i -lt 6; $i++) {
    Write-Output "=== 日志 第 $($i+1) 次 ==="
    try {
        $logs = Api GET "studios/$owner/$repo/logs/run"
        $txt = $logs.data | ConvertTo-Json -Depth 5 -Compress
        if ($txt.Length -gt 1200) { $txt.Substring($txt.Length - 1200) } else { $txt }
    } catch {
        "读取运行日志失败: $_"
    }
    Start-Sleep -Seconds 15
}

Write-Output '=== 构建日志（Docker 首次构建 3-5 分钟） ==='
try {
    $bl = Api GET "studios/$owner/$repo/logs/build"
    $t2 = $bl.data | ConvertTo-Json -Depth 5 -Compress
    if ($t2.Length -gt 1500) { $t2.Substring($t2.Length - 1500) } else { $t2 }
} catch {
    "读取构建日志失败: $_"
}

Write-Output '=== 公网地址 ==='
"https://modelscope.cn/studios/$owner/$repo"
