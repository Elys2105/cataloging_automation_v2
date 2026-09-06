$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\pip.exe freeze | Out-File -Encoding utf8 requirements-lock.txt
Write-Host "Đã tạo requirements-lock.txt" -ForegroundColor Green
