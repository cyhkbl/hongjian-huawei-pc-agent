$ErrorActionPreference = 'Continue'
$repo = 'hongjian-huawei-pc-agent'
$user = 'cyhkbl'
$dir  = 'D:\DeepSeekWorkSpace\hackathlon\hongjian'
Set-Location $dir
git remote remove origin 2>$null
git remote add origin "https://github.com/$user/$repo.git"
git branch -M main
git push -u origin main 2>&1 | Out-String
Write-Output "--- remote:"
git remote -v
Write-Output "--- gh view:"
gh repo view "$user/$repo" --json url,visibility,defaultBranchRef,isPrivate 2>&1 | ConvertFrom-Json | Format-List
