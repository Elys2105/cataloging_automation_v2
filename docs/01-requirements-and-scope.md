# Bước 1 — Phạm vi và yêu cầu đã chốt

## Trải nghiệm người dùng

1. Mở ứng dụng và dùng ngay với profile trình duyệt chuyên dụng đã giữ phiên.
2. Không có màn hình đăng nhập trong luồng sử dụng hằng ngày.
3. Không yêu cầu chọn, tải hoặc lưu PDF thủ công.
4. Người dùng chỉ nhập hồ sơ, tùy chọn văn bản và bấm chạy.
5. Tool tự tìm bản ghi, phát hiện PDF, đọc text hoặc OCR, phân tích, điền form và xác minh.
6. Một bản ghi lỗi không được làm dừng toàn bộ hồ sơ.
7. Có thể dừng an toàn và tiếp tục sau khi mở lại.
8. Cấu hình kỹ thuật không xuất hiện trên màn hình chính.

## Ràng buộc an toàn

- Không vượt qua cơ chế xác thực của hệ thống. Persistent profile chỉ tái sử dụng phiên hợp lệ.
- Không lưu mật khẩu trong source code hoặc file cấu hình dạng rõ.
- Không tự bấm Hoàn thành khi dữ liệu không đạt điều kiện xác minh.
- Không retry thao tác submit khi chưa xác định lần trước thành công hay thất bại.

## Stack

- Python 3.11 trở lên.
- Playwright Python với persistent browser context.
- PaddleOCR được nạp lười khi PDF scan cần OCR.
- PyMuPDF để đọc text layer và render PDF.
- PySide6 cho giao diện Windows tối giản.
- SQLite chuẩn thư viện Python để giảm dependency.
- PyInstaller onedir để đóng gói.

## 12 bước triển khai

1. Đóng băng và kiểm kê tool cũ.
2. Dựng project, cấu hình và kiểm tra môi trường.
3. Tạo domain model, logging và SQLite.
4. Tạo cơ chế tự phát hiện và lấy PDF.
5. Tạo pipeline đọc PDF, render và tiền xử lý ảnh.
6. Tích hợp OCR PaddleOCR dạng lazy-load.
7. Tạo normalize, parser, validator và rule ngoài code.
8. Tạo Playwright session và Page Objects.
9. Tạo workflow chạy, dừng, retry và resume.
10. Tạo giao diện PySide6 tối giản.
11. Tạo test, kiểm tra chất lượng và dữ liệu hồi quy mẫu.
12. Tạo cấu hình đóng gói, hướng dẫn cài đặt và gói bàn giao.
