# Cataloging Automation V2

Tool biên mục tự động theo luồng: mở hồ sơ → phát hiện PDF → đọc text/OCR → phân tích → điền form → xác minh.

## Cài phần lõi

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Cài đầy đủ trên Windows

```powershell
pip install -e ".[full,dev]"
playwright install chromium
```

PaddlePaddle CPU/GPU cần được cài theo hướng dẫn chính thức phù hợp phần cứng trước khi chạy OCR.

## Kiểm tra môi trường

```powershell
python scripts/check_environment.py
```


## Chạy nền và nhiều hồ sơ

Từ 0.1.28, có thể thêm nhiều hồ sơ vào hàng đợi. Mặc định hai hồ sơ chạy song song bằng hai Chrome profile độc lập; OCR được khóa tuần tự để bảo vệ RAM và độ ổn định. Đóng cửa sổ khi còn job sẽ thu nhỏ tool xuống khay hệ thống.

## Chạy

```powershell
cataloging-tool
```
