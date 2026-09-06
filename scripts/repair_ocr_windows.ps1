param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),
    [switch]$SkipRuntimeSmoke
)

$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Không tìm thấy .venv. Hãy chạy scripts\install_windows.ps1 trước."
}

Write-Host "[1/7] Sao lưu danh sách package hiện tại..." -ForegroundColor Cyan
& $python -m pip freeze | Out-File -Encoding utf8 "requirements-before-ocr-repair.txt"

Write-Host "[2/7] Gỡ bộ Paddle đang xung đột..." -ForegroundColor Cyan
& $python -m pip uninstall -y paddlepaddle-gpu paddlepaddle paddleocr paddlex

Write-Host "[3/7] Cài bộ phiên bản Windows CPU đã khóa..." -ForegroundColor Cyan
& $python -m pip install --no-cache-dir "paddlepaddle==3.2.2"
& $python -m pip install --no-cache-dir "paddlex[ocr-core]==3.3.13"
& $python -m pip install --no-cache-dir "paddleocr==3.3.2"

$modelRoot = Join-Path $env:USERPROFILE ".paddlex\official_models"
if (Test-Path $modelRoot) {
    Get-ChildItem $modelRoot -Directory -Filter "PP-OCRv6_medium*" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "[4/7] Cài lại project editable..." -ForegroundColor Cyan
& $python -m pip install -e ".[browser,ui,dev]"

Write-Host "[5/7] Kiểm tra version và CPU flags..." -ForegroundColor Cyan
$env:FLAGS_use_mkldnn = "0"
$env:FLAGS_enable_mkldnn = "0"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
& $python -c "import paddle, paddleocr; print('paddlepaddle=', paddle.__version__); print('paddleocr=', paddleocr.__version__); assert paddle.__version__ == '3.2.2'; import paddlex; print('paddlex=', paddlex.__version__)"

Write-Host "[6/7] Chạy unit tests..." -ForegroundColor Cyan
& $python -m pytest -q

if (-not $SkipRuntimeSmoke) {
    Write-Host "[7/7] Chạy OCR smoke test trên ảnh gần nhất..." -ForegroundColor Cyan
    & $python .\scripts\smoke_ocr_runtime.py
} else {
    Write-Host "[7/7] Bỏ qua OCR runtime smoke test theo tham số." -ForegroundColor Yellow
}

Write-Host "Đã sửa triệt để cấu hình PaddleOCR Windows CPU." -ForegroundColor Green
Write-Host "PaddlePaddle 3.2.2 + PaddleX 3.3.13 + PaddleOCR 3.3.2 + MKL-DNN OFF + PP-OCRv5 mobile + Tesseract fallback." -ForegroundColor Green
