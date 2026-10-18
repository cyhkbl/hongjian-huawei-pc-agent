$ErrorActionPreference = 'Continue'
$payload = '{"name":"hongjian-huawei-pc-agent","private":false,"description":"Hongjian: self-built agent for Huawei PC marketing copy. ima serves only as the knowledge source."}'
$tmp = Join-Path $env:TEMP 'repo_payload.json'
[IO.File]::WriteAllText($tmp, $payload)
gh api -X POST /user/repos --input $tmp 2>&1 | Out-String
Write-Output "--- verify:"
gh api /user/repos --jq '.[] | select(.name=="hongjian-huawei-pc-agent") | .full_name + " private=" + (.private|tostring)' 2>&1 | Out-String
