param([string]$Token = "ms-3a46b6f3-c73d-41a2-9873-535d0ac55fef")
$ErrorActionPreference = 'Continue'
$env:MODELSCOPE_API_KEY = $Token
$base = 'https://modelscope.cn/openapi/v1'
$owner = 'cyhkbl'
$repo = 'hongjian'

function Api($m, $u, $b) {
    $tmp = Join-Path $env:TEMP ('ms_' + [guid]::NewGuid().ToString('N') + '.json')
    if ($null -ne $b) { [IO.File]::WriteAllText($tmp, ($b | ConvertTo-Json -Depth 6 -Compress), [Text.UTF8Encoding]::new($false)) }
    try {
        if ($null -ne $b) {
            return Invoke-RestMethod -Method $m -Uri "$base/$u" -Headers @{ Authorization = "Bearer $Token" } -Body ([IO.File]::ReadAllText($tmp)) -ContentType 'application/json' -UseBasicParsing
        }
        return Invoke-RestMethod -Method $m -Uri "$base/$u" -Headers @{ Authorization = "Bearer $Token" } -UseBasicParsing
    } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
}

$me = Api GET 'users/me'
$owner = $me.data.username
Write-Output "user=$owner name=$($me.data.name)"

$exists = $null
try { $exists = Api GET "studios/$owner/$repo" } catch {}
if ($exists -and $exists.success) {
    Write-Output 'studio already exists'
    Write-Output ($exists.data | ConvertTo-Json -Depth 3 -Compress)
} else {
    Write-Output '=== create studio ==='
    $r = Api POST 'studios' @{ owner = $owner; repo_name = $repo; sdk_type = 'docker'; visibility = 'public'; display_name = '鸿笺 · 华为 PC 营销软文智能体' }
    Write-Output ($r | ConvertTo-Json -Depth 4 -Compress)
}
