# Xử lý sự cố

## Phiên trình duyệt hết hạn

Tool không có màn hình đăng nhập. Người quản trị mở profile chuyên dụng một lần, đăng nhập hợp lệ rồi đóng Chrome. Không ghi mật khẩu vào cấu hình.

## Không phát hiện được PDF

Kiểm tra artifact `page.html`, screenshot và network trace. Website có thể đã thay endpoint hoặc viewer. Sửa module `automation/pdf_detector.py`, không sửa parser.

## OCR không chạy

Chạy `python scripts/check_environment.py`. Xác nhận PaddlePaddle và PaddleOCR được cài đúng phiên bản CPU/GPU. Không cài đồng thời bản CPU và GPU.

## Tool báo NeedsReview

Tool cố ý không submit vì trường bắt buộc thiếu, trích yếu dính phần thân hoặc confidence thấp. Kiểm tra PDF và file `parsed.json`.

## Chrome không mở

Cấu hình mặc định dùng `channel: chrome`; máy phải có Google Chrome. Có thể đổi sang Chromium do Playwright quản lý trong `config/local.yaml`, nhưng bản đóng gói sẽ nặng hơn.
