$ErrorActionPreference = 'Continue'
$payload = '{"names":["huawei-pc","ima","marketing-agent","hackathon","fastapi","content-generation","rag","langgraph-free"]}'
$tmp = Join-Path $env:TEMP 'topics.json'
[IO.File]::WriteAllText($tmp, $payload)
gh api -X PUT /repos/cyhkbl/hongjian-huawei-pc-agent/topics --input $tmp 2>&1 | Out-String
gh api /repos/cyhkbl/hongjian-huawei-pc-agent/topics --jq '.names | join(", ")' 2>&1 | Out-String
