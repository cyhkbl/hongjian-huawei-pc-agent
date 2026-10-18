# 秘钥与敏感内容自检 + git 首次推送
$ErrorActionPreference = 'Stop'
Set-Location 'D:\DeepSeekWorkSpace\hackathlon\hongjian'

# 1) 扫描仓库里可能硬编码的凭证
$files = Get-ChildItem -Recurse -File | Where-Object {
    $_.FullName -notmatch '\\.venv\\|\\.git\\|__pycache__|\\.kb_cache\\|\\runs\\|\\.history\\' -and
    $_.Extension -in '.py','.js','.html','.css','.md','.json','.txt','.yml','.yaml','.ps1','.sh','.cfg','.toml','.example'
}
$hits = @()
foreach ($f in $files) {
    $txt = Get-Content $f.FullName -Raw -ErrorAction SilentlyContinue
    if (-not $txt) { continue }
    if ($txt -match '(gho_|ghp_|github_pat_)[A-Za-z0-9]{12,}') { $hits += "GH_TOKEN $($f.FullName)" }
    if ($txt -match 'sk-[A-Za-z0-9]{24,}') { $hits += "OPENAI_LIKE $($f.FullName)" }
    # ima 凭证：逐行查，允许空值与尖括号占位（.env.example）
    foreach ($line in ($txt -split "`r?`n")) {
        if ($line -match '^\s*IMA_OPENAPI_(?:CLIENTID|APIKEY)\s*=\s*(.*)$') {
            $v = $Matches[1].Trim().Trim('"').Trim("'")
            if ($v -and $v -notlike '<*>' -and $v -notlike 'your*' -and $v -notlike '*your_*') {
                $hits += "IMA_KEY $($f.FullName)"
            }
        }
    }
    if ($txt -match 'api[_-]?key["'']?\s*[:=]\s*["''][A-Za-z0-9\-_]{12,}') {
        # 测试夹具用的假 key 不在拦截范围（web-dev 的响应泄露扫描依赖它）
        if ($f.FullName -notmatch '\\tests\\|\\test_') { $hits += "APIKEY $($f.FullName)" }
    }
}
if ($hits) {
    Write-Output "发现疑似硬编码凭证："
    $hits | Sort-Object -Unique | ForEach-Object { Write-Output "  $_" }
    exit 1
}
Write-Output "secret scan: clean"

# 2) 确认知识库原文、缓存与运行档案都没有进入版本控制（目录本身可以在本地存在）
$forbidden = @()
$tracked = git ls-files
foreach ($p in @('P1-产品参数库','华为PC全板块深度知识库','产品事实.md','08-官方公开价格快照','图片索引.csv')) {
    $n = ($tracked | Where-Object { $_ -like "*$p*" }).Count
    if ($n -gt 0) { $forbidden += "tracked:$p($n)" }
}
foreach ($p in @('.kb_cache/','runs/','kb_local/')) {
    $n = ($tracked | Where-Object { $_ -like "$p*" }).Count
    if ($n -gt 0) { $forbidden += "tracked:$p($n)" }
}
if ($forbidden) { Write-Output "发现不应入库的内容：$($forbidden -join ', ')"; exit 1 }
Write-Output "kb leakage scan: clean"

# 3) 提交并推送
$repo = 'hongjian-huawei-pc-agent'
$exists = gh repo view $repo --json name 2>$null
if (-not $exists) {
    gh repo create $repo --public --source=. --remote=origin --description '鸿笺 · 华为 PC 营销软文智能体：场景解析 → ima 检索取证 → 图文软文生成 → 事实/图片/合规核验 → 导出' 2>&1 | Out-String | Write-Output
} else {
    git remote add origin "https://github.com/cyhkbl/$repo.git" 2>$null
}
git add -A
git -c user.name='cyhkbl' -c user.email='cyhkbl@hotmail.com' commit -m 'Hongjian: self-built agent for Huawei PC marketing copy (ima as fact/image source)' 2>&1 | Out-String | Write-Output
git branch -M main 2>$null
git push -u origin main --force 2>&1 | Out-String | Write-Output
gh repo view $repo --json url,visibility,defaultBranchRef | ConvertFrom-Json | Format-List
