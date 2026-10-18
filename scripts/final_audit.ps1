<#
.SYNOPSIS
    终检：GitHub 与魔搭创空间是否可用、是否泄漏凭证或知识库原文。
#>
$ErrorActionPreference = 'Continue'
$gh = 'https://raw.githubusercontent.com/cyhkbl/hongjian-huawei-pc-agent/main'
$api = 'https://api.github.com/repos/cyhkbl/hongjian-huawei-pc-agent'
$u = 'https://cyhkbl-hongjian.ms.show'

Write-Output '=== 1. 线上免登录可用 ==='
foreach ($p in @('/api/health', '/', '/api/kb/status', '/api/prompt', '/api/options', '/api/selftest/cases')) {
    try { $r = Invoke-WebRequest "$u$p" -UseBasicParsing -TimeoutSec 30; "  $p -> $($r.StatusCode)" } catch { "  $p -> FAIL" }
}

Write-Output '=== 2. GitHub 免登录可用 ==='
foreach ($p in @('/README.md', '/requirements.txt', '/Dockerfile', '/ms_deploy.json',
                 '/docs/%E4%BD%9C%E5%93%81%E8%AF%B4%E6%98%8E%E4%B9%A6.md',
                 '/docs/samples/pro-hm_back_to_school_xiaohongshu.md')) {
    try {
        $r = Invoke-WebRequest "$gh$p" -UseBasicParsing -TimeoutSec 30
        "  $p -> $($r.StatusCode) $($r.RawContentLength)B"
    } catch { "  $p -> FAIL" }
}

Write-Output '=== 3. GitHub 当前分支状态 ==='
$t = Invoke-RestMethod "$api/git/trees/main?recursive=1"
"  files=$($t.tree.Count) truncated=$($t.truncated)"
"  kb_snapshot=$((($t.tree | ? { $_.path -like 'kb_snapshot/*' }).Count))"
"  知识库特征文件=$((($t.tree | ? { $_.path -like '*产品事实.md' -or $_.path -like '*图片索引.csv' -or $_.path -like '*官方价格快照.csv' -or $_.path -like '*卖点与限制.md' -or $_.path -like '*全库导航.md' -or $_.path -like '*型号检索卡*' }).Count))"
"  .env=$((($t.tree | ? { $_.path -eq '.env' }).Count))"

Write-Output '=== 4. 本地是否还有硬编码凭证 ==='
# 用前缀特征匹配，避免把真值写进本文件
$patterns = @{
    'modelscope token 前缀' = 'ms-[0-9a-f]{8}-'
    'ima client id 前缀'   = '5a38dbf5'
    'ima api key 前缀'     = 'Lg/q9PsY'
}
$hits = @()
Get-ChildItem -Recurse -File -Include *.py,*.ps1,*.js,*.md,*.json,*.html,*.css,*.txt,*.yml,*.sh |
  Where-Object { $_.FullName -notmatch '\\.venv\\|\\.git\\|__pycache__|\\runs\\|\\.kb_cache\\' } |
  ForEach-Object {
      $txt = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
      if (-not $txt) { return }
      foreach ($k in $patterns.Keys) {
          if ($txt -match $patterns[$k]) { $hits += "$k -> $($_.FullName)" }
      }
  }
if ($hits.Count) { $hits | ForEach-Object { "  HIT $_" } } else { "  干净" }

Write-Output '=== 5. 线上端到端 ==='
$b = @{ text = '给 MateBook Pro 写一篇开学季小红书，面向大学新生' } | ConvertTo-Json
try {
    $r = (Invoke-WebRequest -Uri "$u/api/run" -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($b)) `
            -ContentType 'application/json; charset=utf-8' -UseBasicParsing -TimeoutSec 150).Content | ConvertFrom-Json
    "  status=$($r.status) verdict=$($r.verification.verdict) imgs=$($r.article.image_refs.Count)"
} catch { "  FAIL $_" }

Write-Output '=== 6. 线上 21 条自测 ==='
try {
    $c = ((Invoke-WebRequest "$u/api/selftest/cases" -UseBasicParsing -TimeoutSec 60).Content | ConvertFrom-Json).cases
    $pass = 0; $fail = @()
    foreach ($x in $c) {
        try {
            $res = Invoke-RestMethod -Uri "$u/api/selftest/run" -Method Post `
                -Body (@{ case_id = $x.id } | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 180
            if ($res.passed) { $pass++ } else { $fail += $x.id }
        } catch { $fail += $x.id }
    }
    "  $pass/$($c.Count) 通过；失败：$($fail -join ',')"
} catch { "  FAIL $_" }
