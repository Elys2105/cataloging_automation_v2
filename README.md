# Công cụ tự động biên mục tài liệu

Ứng dụng hỗ trợ tự động hóa quy trình biên mục hồ sơ, tài liệu trên hệ thống web. Công cụ có thể phát hiện PDF, đọc nội dung bằng OCR, phân tích thông tin và hỗ trợ điền dữ liệu tự động.

## Chức năng chính

- Tự động mở và xử lý hồ sơ trên hệ thống web
- Phát hiện và đọc nội dung tài liệu PDF
- Hỗ trợ OCR với PaddleOCR và Tesseract
- Phân tích thông tin tài liệu để phục vụ biên mục
- Tự động điền và kiểm tra dữ liệu trên biểu mẫu
- Hỗ trợ xử lý nhiều hồ sơ với các profile trình duyệt độc lập
- Lưu trạng thái xử lý và hỗ trợ tiếp tục công việc khi cần

## Công nghệ sử dụng

- Python
- Playwright
- PySide6
- PaddleOCR
- Tesseract OCR
- OpenCV
- PyMuPDF
- SQLite
- Pytest
- PyInstaller

## Cài đặt

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[full,dev]"
playwright install chromium
```

## Chạy ứng dụng

```powershell
cataloging-tool
```

Có thể kiểm tra môi trường trước khi chạy bằng:

```powershell
python scripts/check_environment.py
```

## Tác giả

**Nguyễn Ngọc Bích Châu**  
Sinh viên Công nghệ Thông tin - Chuyên ngành Công nghệ Phần mềm  
GitHub: [Elys2105](https://github.com/Elys2105)
