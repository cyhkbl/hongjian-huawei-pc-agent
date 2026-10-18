$ErrorActionPreference = 'Continue'
Set-Location 'D:\DeepSeekWorkSpace\hackathlon\hongjian'
$env:KB_MODE = 'local'
$env:KB_LOCAL_DIR = 'D:\DeepSeekWorkSpace\hackathlon\kb_raw\华为PC全板块深度知识库_v7'

Write-Output '=== 1. pytest'
& .\.venv\Scripts\python.exe -m pytest -q 2>&1 | Select-Object -Last 3

Write-Output '=== 2. selftest'
& .\.venv\Scripts\python.exe scripts\run_all.py 2>&1 | Select-Object -Last 2

Write-Output '=== 3. server'
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Process -FilePath (Resolve-Path .\.venv\Scripts\python.exe) -ArgumentList '-m','app.main' -RedirectStandardOutput ..\server.log -RedirectStandardError ..\server.err -WindowStyle Hidden
Start-Sleep 8
(Invoke-WebRequest http://127.0.0.1:7860/api/health -UseBasicParsing).Content
(Invoke-WebRequest http://127.0.0.1:7860/ -UseBasicParsing).StatusCode

Write-Output '=== 4. index.html title + static asset count'
$idx = (Invoke-WebRequest http://127.0.0.1:7860/ -UseBasicParsing).Content
($idx -split "`n" | Select-String -Pattern '<title>' | Select-Object -First 1)
(Get-ChildItem app\web\static -Recurse -File).Count

Write-Output '=== 5. prompt + options'
$p = Invoke-RestMethod http://127.0.0.1:7860/api/prompt
"prompt version=$($p.version) chars=$($p.chars) sections=$($p.sections.Count)"
$o = Invoke-RestMethod http://127.0.0.1:7860/api/options
"models=$($o.models.Count)"

Write-Output '=== 6. clarify flow'
$b1 = @{text='想买轻薄本'} | ConvertTo-Json
$r1 = (Invoke-WebRequest -Uri http://127.0.0.1:7860/api/run -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($b1)) -ContentType 'application/json; charset=utf-8' -UseBasicParsing).Content | ConvertFrom-Json
"status=$($r1.status) clarifications=$($r1.clarifications.Count)"

Write-Output '=== 7. refuse flow'
$b2 = @{text='MateBook Pro S 门店到访朋友圈，写个国补立减2000和全网最低价'} | ConvertTo-Json
$r2 = (Invoke-WebRequest -Uri http://127.0.0.1:7860/api/run -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($b2)) -ContentType 'application/json; charset=utf-8' -UseBasicParsing).Content | ConvertFrom-Json
"status=$($r2.status) refusal_len=$($r2.refusal.Length) verdict=$($r2.verification.verdict) blocks=$($r2.verification.stats.compliance_blocks)"
"body_has_subsidy=$([bool]($r2.article.blocks.text -join '' -match '国补|立减'))"

Write-Output '=== 8. revise flow'
$b3 = @{run_id=$r2.run_id; instruction='换成小红书'} | ConvertTo-Json
$r3 = (Invoke-WebRequest -Uri http://127.0.0.1:7860/api/revise -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($b3)) -ContentType 'application/json; charset=utf-8' -UseBasicParsing).Content | ConvertFrom-Json
"platform=$($r3.article.platform) v2_imgs=$($r3.article.image_refs.Count) parent=$($r3.parent_run_id)"

Write-Output '=== 9. image endpoint'
$img = $r2.article.image_refs[0].image_id
$resp = Invoke-WebRequest "http://127.0.0.1:7860/api/image/$img" -UseBasicParsing
"image=$img status=$($resp.StatusCode) bytes=$($resp.RawContentLength) mime=$($resp.Headers['Content-Type'])"
$bad = Invoke-WebRequest http://127.0.0.1:7860/api/image/__nope__ -UseBasicParsing -SkipHttpErrorCheck
"bad_image_status=$($bad.StatusCode)"

Write-Output '=== 10. export'
foreach ($fmt in @('md','html','json')) {
    $eb = @{run_id=$r2.run_id; format=$fmt} | ConvertTo-Json
    $er = Invoke-WebRequest -Uri http://127.0.0.1:7860/api/export -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($eb)) -ContentType 'application/json; charset=utf-8' -UseBasicParsing
    "$fmt bytes=$($er.RawContentLength) mime=$($er.Headers['Content-Type'])"
}

Write-Output '=== 11. kb drawer (no secret in body)'
$st = Invoke-WebRequest http://127.0.0.1:7860/api/kb/status -UseBasicParsing
$body = [Text.Encoding]::UTF8.GetString($st.Content)
"leaks_fake_key=$($body -match 'fake-api-key-SECRET')  api_key_hint_present=$($body -match 'api_key_hint')"
$stobj = $body | ConvertFrom-Json
"mode=$($stobj.mode) connected=$($stobj.connected) models=$($stobj.models) facts=$($stobj.facts) images=$($stobj.images) prices=$($stobj.prices)"
