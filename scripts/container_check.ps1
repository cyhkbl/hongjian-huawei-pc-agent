$ErrorActionPreference = 'Continue'
Set-Location 'D:\DeepSeekWorkSpace\hackathlon\hongjian'
Write-Output "=== 1. git 不会收 kb_snapshot / .env"
git check-ignore kb_snapshot .env
git status --short kb_snapshot .env
if (git status --short kb_snapshot .env) { throw "kb_snapshot 或 .env 被 git 跟踪了" }
Write-Output "clean"

Write-Output '=== 2. pytest'
$env:KB_MODE = 'local'
$env:KB_LOCAL_DIR = "$PWD\kb_snapshot"
& .\.venv\Scripts\python.exe -m pytest -q 2>&1 | Select-Object -Last 3

Write-Output '=== 3. 用 kb_snapshot 起服务（模拟容器内路径）'
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
$env:PORT = '7860'
Start-Process -FilePath (Resolve-Path .\.venv\Scripts\python.exe) -ArgumentList '-m','app.main' -RedirectStandardOutput ..\server.log -RedirectStandardError ..\server.err -WindowStyle Hidden
Start-Sleep 8
(Invoke-WebRequest http://127.0.0.1:7860/api/health -UseBasicParsing).Content

$st = (Invoke-WebRequest http://127.0.0.1:7860/api/kb/status -UseBasicParsing).Content | ConvertFrom-Json
"mode=$($st.mode) connected=$($st.connected) models=$($st.models) facts=$($st.facts) images=$($st.images) prices=$($st.prices)"
if ($st.models -ne 10) { throw "知识库型号数不是 10" }

Write-Output '=== 4. 端到端跑一次'
$b = @{ text = '给 MateBook Pro 写一篇开学季小红书，面向大学新生' } | ConvertTo-Json
$r = (Invoke-WebRequest -Uri http://127.0.0.1:7860/api/run -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($b)) -ContentType 'application/json; charset=utf-8' -UseBasicParsing).Content | ConvertFrom-Json
"status=$($r.status) verdict=$($r.verification.verdict) imgs=$($r.article.image_refs.Count)"
"title=$($r.article.title)"
$img = $r.article.image_refs[0].image_id
$ir = Invoke-WebRequest "http://127.0.0.1:7860/api/image/$img" -UseBasicParsing
"image bytes=$($ir.RawContentLength) mime=$($ir.Headers['Content-Type'])"

Write-Output '=== 5. 图片文件是否真的在 kb_snapshot 里'
$found = Get-ChildItem kb_snapshot -Recurse -File -Filter $img -ErrorAction SilentlyContinue
if ($found) { "found: $($found.FullName)" } else { "WARN: 未找到 $img" }
