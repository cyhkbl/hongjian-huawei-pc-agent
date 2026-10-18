param([string]$Token = "ms-3a46b6f3-c73d-41a2-9873-535d0ac55fef")

$ErrorActionPreference = 'Continue'
$env:MODELSCOPE_API_KEY = $Token
$env:MODELSCOPE_ENDPOINT = 'https://modelscope.cn'
$dir = 'D:\DeepSeekWorkSpace\hackathlon\hongjian'
$owner = 'cyhkbl'
$repo = 'hongjian'
$base = 'https://modelscope.cn/openapi/v1'
$auth = "Bearer $Token"

function Api($m, $u, $b) {
    $tmp = Join-Path $env:TEMP ('ms_' + [guid]::NewGuid().ToString('N') + '.json')
    if ($b) { [IO.File]::WriteAllText($tmp, ($b | ConvertTo-Json -Depth 6 -Compress), [Text.UTF8Encoding]::new($false)) }
    $out = if ($b) {
        Invoke-RestMethod -Method $m -Uri "$base/$u" -Headers @{ Authorization = $auth } -Body ([IO.File]::ReadAllText($tmp)) -ContentType 'application/json' -UseBasicParsing
    } else {
        Invoke-RestMethod -Method $m -Uri "$base/$u" -Headers @{ Authorization = $auth } -UseBasicParsing
    }
    Remove-Item $tmp -ErrorAction SilentlyContinue
    return $out
}

Set-Location $dir

Write-Output '=== 1. 身份'
$me = Api GET 'users/me'
"user = $($me.data.username) ($($me.data.name)) id=$($me.data.id)"
$owner = $me.data.username

Write-Output '=== 2. 是否已有创空间'
$exists = $null
try { $exists = Api GET "studios/$owner/$repo" } catch { $exists = $null }
if ($exists -and $exists.data) {
    Write-Output '已存在，改用现有空间'
} else {
    Write-Output '=== 3. 创建创空间（Docker，公开）'
    $created = Api POST 'studios' @{ owner = $owner; repo_name = $repo; sdk_type = 'docker'; visibility = 'public'; display_name = '鸿笺 · 华为 PC 营销软文智能体' }
    $created | ConvertTo-Json -Depth 4 -Compress | Select-Object -First 1
}

Write-Output '=== 4. 拉取远端并合并'
git remote remove modelscope 2>$null
git remote add modelscope "https://oauth2:$Token@www.modelscope.cn/studios/$owner/$repo.git"
git fetch modelscope master 2>&1 | Out-String
$hasRemote = git rev-parse --verify modelscope/master 2>$null
if ($hasRemote) {
    git merge modelscope/master --allow-unrelated-histories -m 'Merge from ModelScope' 2>&1 | Out-String
    git checkout --ours . 2>$null
    git add -A 2>$null
}

Write-Output '=== 5. 提交并推送'
git add -A
git -c user.name="cyhkbl" -c user.email="cyhkbl@hotmail.com" commit -m 'Deploy Hongjian: Huawei PC marketing-copy agent (Docker, port 7860)' 2>&1 | Out-String
git branch -M master 2>&1 | Out-String
git push -u modelscope master 2>&1 | Out-String

Write-Output '=== 6. 触发部署'
Api POST "studios/$owner/$repo/deploy" $null | ConvertTo-Json -Compress | Select-Object -First 1

Write-Output '=== 7. 公网地址'
"https://modelscope.cn/studios/$owner/$repo"
