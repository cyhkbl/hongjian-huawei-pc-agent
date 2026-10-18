$ErrorActionPreference = 'Continue'
Set-Location 'D:\DeepSeekWorkSpace\hackathlon\hongjian'
$env:KB_MODE = 'local'
$env:KB_LOCAL_DIR = 'D:\DeepSeekWorkSpace\hackathlon\kb_raw\华为PC全板块深度知识库_v7'
Remove-Item docs\samples\*.md -ErrorAction SilentlyContinue
& .\.venv\Scripts\python.exe scripts\gen_samples.py
