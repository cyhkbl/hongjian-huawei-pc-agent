$ErrorActionPreference = 'Continue'
$u = 'https://cyhkbl-hongjian.ms.show'

Write-Output '=== 1. 生成一篇小红书 ==='
$b = @{ text = '给 MateBook Pro 写一篇开学季小红书，面向大学新生' } | ConvertTo-Json
$r = (Invoke-WebRequest -Uri "$u/api/run" -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($b)) -ContentType 'application/json; charset=utf-8' -UseBasicParsing -TimeoutSec 120).Content | ConvertFrom-Json
"status=$($r.status)  verdict=$($r.verification.verdict)  imgs=$($r.article.image_refs.Count)"
"title=$($r.article.title)"
"stats=$($r.verification.stats | ConvertTo-Json -Compress)"

Write-Output '=== 2. 追问 ==='
$b1 = @{ text = '想买轻薄本' } | ConvertTo-Json
$r1 = (Invoke-WebRequest -Uri "$u/api/run" -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($b1)) -ContentType 'application/json; charset=utf-8' -UseBasicParsing -TimeoutSec 120).Content | ConvertFrom-Json
"status=$($r1.status) clarifications=$($r1.clarifications.Count)"
$r1.clarifications | ForEach-Object { "  - $($_.field): $($_.question)" }

Write-Output '=== 3. 图片下载（知识库是否真的进镜像） ==='
foreach ($img in $r.article.image_refs) {
    try {
        $ir = Invoke-WebRequest "$u/api/image/$([uri]::EscapeDataString($img.image_id))" -UseBasicParsing -TimeoutSec 60
        "  $($img.image_id.Substring(0, [Math]::Min(34, $img.image_id.Length))) -> $($ir.StatusCode) $($ir.RawContentLength)B $($ir.Headers['Content-Type'])"
    } catch {
        "  $($img.image_id) -> FAIL $_"
    }
}

Write-Output '=== 4. 导出 ==='
foreach ($fmt in @('md', 'json')) {
    try {
        $eb = @{ run_id = $r.run_id; format = $fmt } | ConvertTo-Json
        $er = Invoke-WebRequest -Uri "$u/api/export" -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($eb)) -ContentType 'application/json; charset=utf-8' -UseBasicParsing -TimeoutSec 120
        "  $fmt -> $($er.RawContentLength)B"
    } catch {
        "  $fmt -> FAIL $_"
    }
}

Write-Output '=== 5. 系统提示词 ==='
$p = Invoke-RestMethod "$u/api/prompt"
"version=$($p.version) chars=$($p.chars)"

Write-Output '=== 6. 前端资源 ==='
foreach ($f in @('/', '/index.html')) {
    try { $ir = Invoke-WebRequest "$u$f" -UseBasicParsing -TimeoutSec 30; "  $f -> $($ir.StatusCode) $($ir.RawContentLength)B" } catch { "  $f -> FAIL $_" }
}
try {
    $j = Invoke-WebRequest "$u/js/main.js" -UseBasicParsing -TimeoutSec 30
    "  /js/main.js -> $($j.StatusCode)"
} catch { "  /js/main.js -> FAIL $_" }

Write-Output '=== 7. 自测集（首页可点，服务端跑全部） ==='
$c = (Invoke-WebRequest "$u/api/selftest/cases" -UseBasicParsing -TimeoutSec 60).Content | ConvertFrom-Json
"cases=$($c.cases.Count)"
