$ErrorActionPreference = 'Continue'
Set-Location 'D:\DeepSeekWorkSpace\hackathlon\hongjian'
$env:KB_MODE = 'local'
$env:KB_LOCAL_DIR = "$PWD\kb_snapshot"
& .\.venv\Scripts\python.exe -m pytest -q 2>&1 | Select-Object -Last 2
& .\.venv\Scripts\python.exe scripts\run_all.py 2>&1 | Select-Object -Last 2
