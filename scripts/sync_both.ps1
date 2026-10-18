$ErrorActionPreference = 'Continue'
Set-Location 'D:\DeepSeekWorkSpace\hackathlon\hongjian'

Write-Output '=== 1. 暂存 kb_snapshot 的强制添加状态解开，避免推到 GitHub ==='
git reset -q kb_snapshot 2>$null
git ls-files --error-unmatch kb_snapshot/README.md 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { git rm -r -q --cached kb_snapshot 2>$null }

Write-Output '=== 2. 提交到 GitHub main（不含 kb_snapshot / .env） ==='
git add -A
git -c user.name="cyhkbl" -c user.email="cyhkbl@hotmail.com" commit -m 'ima client: real-KB calibration (root wrapper folder, 220021 quota, throttle), docs and production screenshots' 2>&1 | Out-String
git push origin main 2>&1 | Out-String

Write-Output '=== 3. 提交到魔搭 master（含 kb_snapshot） ==='
git add -f kb_snapshot
git -c user.name="cyhkbl" -c user.email="cyhkbl@hotmail.com" commit -m 'Refresh kb_snapshot + ima client calibration' 2>&1 | Out-String
git push modelscope master 2>&1 | Out-String

Write-Output '=== 4. 触发重新部署 ==='
$tok = 'ms-3a46b6f3-c73d-41a2-9873-535d0ac55fef'
Invoke-RestMethod -Method POST -Uri 'https://modelscope.cn/openapi/v1/studios/cyhkbl/hongjian/deploy' -Headers @{ Authorization = "Bearer $tok" } -UseBasicParsing | ConvertTo-Json -Compress | Select-Object -First 1

Write-Output '=== 5. 确认 GitHub 上没有 kb_snapshot ==='
"tracked kb_snapshot files on origin/main: $((git ls-tree -r origin/main --name-only | Select-String 'kb_snapshot').Count)"
