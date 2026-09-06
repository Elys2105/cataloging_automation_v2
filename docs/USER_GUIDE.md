# Hướng dẫn sử dụng

## Chạy toàn bộ hồ sơ

1. Mở `CatalogingAutomation.exe`.
2. Nhập số/ký hiệu hồ sơ.
3. Bấm **Chạy toàn bộ**.
4. Tool tự mở Chrome bằng profile riêng, tìm hồ sơ, phát hiện PDF, đọc/OCR và xử lý từng bản ghi.
5. Theo dõi trạng thái trong bảng.

## Chạy một bản ghi

1. Nhập hồ sơ.
2. Nhập số hoặc ký hiệu văn bản.
3. Bấm **Chạy 1 bản ghi**.

## Tiếp tục từ một bản ghi

1. Nhập hồ sơ.
2. Nhập bản ghi bắt đầu.
3. Bấm **Tiếp tục từ bản ghi**.

## Tiếp tục job đang dở

Bấm **Tiếp tục job đang dở**. Tool đọc SQLite và chỉ xử lý phần chưa hoàn thành.

## Dừng

Bấm **Dừng an toàn**. Tool không bắt đầu bước mới, lưu trạng thái hiện tại rồi đóng browser.

## Khi có bản ghi lỗi

Tool chuyển sang bản ghi tiếp theo. Những trạng thái cần chú ý:

- `needs_review`: OCR/parser chưa đủ chắc chắn, tool không submit.
- `failed`: lỗi đã retry đủ số lần.
- `submission_uncertain`: đã click Hoàn thành nhưng chưa xác định kết quả; không được click lại thủ công trước khi kiểm tra trạng thái trên web.

Dữ liệu chẩn đoán nằm trong `runtime/artifacts/`.
