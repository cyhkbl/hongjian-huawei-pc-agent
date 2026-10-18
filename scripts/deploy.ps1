<#
.SYNOPSIS
    部署到魔搭创空间（ModelScope Studio）。

.DESCRIPTION
    需要 MODELSCOPE_API_KEY 环境变量，令牌从 https://modelscope.cn/my/myaccesstoken 获取。
    本脚本不在代码里保存任何凭证，也不读取仓库外文件。

.EXAMPLE
    $env:MODELSCOPE_API_KEY = "<令牌>"
    .\scripts\deploy.ps1
#>
param(
    [string]$Owner = "cyhkbl",
    [string]$Repo = "hongjian"
)

$ErrorActionPreference = 'Stop'

$Token = $env:MODELSCOPE_API_KEY
if (-not $Token) {
    Write-Error @'
未设置 MODELSCOPE_API_KEY。

获取方式：登录 https://modelscope.cn/my/myaccesstoken 生成访问令牌，然后：

    $env:MODELSCOPE_API_KEY = "<令牌>"
    .\scripts\deploy.ps1

令牌不要写进任何文件，也不要在录屏或截图里完整露出。
'@
    exit 1
}

$base = 'https://modelscope.cn/openapi/v1'

function Api($Method, $Path, $Body) {
    $tmp = Join-Path $env:TEMP ('ms_' + [guid]::NewGuid().ToString('N') + '.json')
    try {
        if ($null -ne $Body) {
            [IO.File]::WriteAllText($tmp, ($Body | ConvertTo-Json -Depth 6 -Compress), [Text.UTF8Encoding]::new($false))
            return Invoke-RestMethod -Method $Method -Uri "$base/$Path" `
                -Headers @{ Authorization = "Bearer $Token" } `
                -Body ([IO.File]::ReadAllText($tmp)) -ContentType 'application/json' -UseBasicParsing
        }
        return Invoke-RestMethod -Method $Method -Uri "$base/$Path" `
            -Headers @{ Authorization = "Bearer $Token" } -UseBasicParsing
    } finally {
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
}

Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Output '=== 1. 验证令牌 ==='
$me = Api GET 'users/me'
Write-Output "账号：$($me.data.username)"
$Owner = $me.data.username

Write-Output '=== 2. 确认创空间存在 ==='
$exists = $null
try { $exists = Api GET "studios/$Owner/$Repo" } catch {}
if (-not $exists -or -not $exists.success) {
    Write-Output '不存在，创建（Docker 类型）'
    Api POST 'studios' @{
        owner         = $Owner
        repo_name     = $Repo
        sdk_type      = 'docker'
        visibility    = 'public'
        display_name  = '鸿笺 · 华为 PC 营销软文智能体'
    } | Out-Null
}

Write-Output '=== 3. 推代码到 master ==='
git push modelscope master 2>&1 | Out-String

Write-Output '=== 4. 触发部署并轮询 ==='
Api POST "studios/$Owner/$Repo/deploy" $null | Out-Null
for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 15
    try {
        $st = (Api GET "studios/$Owner/$Repo").data.runtime.status
    } catch { $st = 'unknown' }
    Write-Output "  [$i] $st"
    if ($st -eq 'Running') { break }
    if ($st -eq 'Failed' -or $st -eq 'Error') { Write-Error '部署失败，运行日志见创空间页面'; exit 1 }
}

Write-Output '=== 5. 冒烟 ==='
$url = (Api GET "studios/$Owner/$Repo").data.host
foreach ($p in @('/api/health', '/')) {
    try { $r = Invoke-WebRequest "$url$p" -UseBasicParsing -TimeoutSec 30; "  $p -> $($r.StatusCode)" }
    catch { "  $p -> FAIL" }
}

Write-Output ''
Write-Output "完成：https://modelscope.cn/studios/$Owner/$Repo"
