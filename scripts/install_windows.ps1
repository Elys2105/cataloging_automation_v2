$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Chưa cài Python chính thức từ python.org. Yêu cầu Python 3.11-3.13 x64."
}

if (-not (Test-Path ".venv")) {
    py -3.11 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
& .\.venv\Scripts\pip.exe install -e ".[full,dev]"
& .\.venv\Scripts\python.exe scripts\check_environment.py
Write-Host "Cài đặt môi trường hoàn tất." -ForegroundColor Green
