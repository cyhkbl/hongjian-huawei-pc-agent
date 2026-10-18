$ErrorActionPreference = 'Continue'
$base = 'https://modelscope.cn/openapi/v1'
$tok = 'ms-3a46b6f3-c73d-41a2-9873-535d0ac55fef'
$url = 'https://cyhkbl-hongjian.ms.show'

for ($i = 1; $i -le 20; $i++) {
    try {
        $st = (Invoke-RestMethod -Method GET -Uri "$base/studios/cyhkbl/hongjian" -Headers @{ Authorization = "Bearer $tok" } -UseBasicParsing).data.runtime.status
    } catch { $st = "unknown" }
    Write-Output "[$i] runtime=$st"
    if ($st -eq 'Running') { break }
    Start-Sleep -Seconds 15
}

Write-Output '=== 冒烟 ==='
foreach ($p in @('/api/health', '/', '/api/kb/status')) {
    try {
        $r = Invoke-WebRequest "$url$p" -UseBasicParsing -TimeoutSec 30
        "$p -> $($r.StatusCode)"
    } catch {
        "$p -> FAIL $_"
    }
}

Write-Output '=== run logs ==='
$r = Invoke-RestMethod -Method GET -Uri "$base/studios/cyhkbl/hongjian/logs/run" -Headers @{ Authorization = "Bearer $tok" } -UseBasicParsing
$r.data.logs | ForEach-Object { $_.content }
