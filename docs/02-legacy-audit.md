# Kiểm kê tool cũ

Tool cũ đã được sao chép nguyên trạng vào `legacy/source/Form1.cs.txt` và khóa bằng SHA-256 trong `legacy-audit.json`.

Các chỉ số được trích tự động:

- 7.015 dòng.
- 121 khai báo phương thức.
- 27 lần `Thread.Sleep`.
- 3 lần `Application.DoEvents`.
- 22 khối `catch {}` rỗng trên tổng 65 khối catch.
- 26 lần gọi JavaScript trực tiếp.
- 32 XPath khai báo trong code.
- 211 lần gọi Regex.
- 19 vị trí gọi cơ chế override theo trường hợp đã báo.

## Nhóm chức năng phải giữ

- Chạy toàn bộ hồ sơ.
- Chạy một bản ghi.
- Tiếp tục từ bản ghi hoặc tiếp tục job dở.
- Dừng an toàn.
- Tìm hồ sơ, phân trang và mở bản ghi.
- Tự lấy PDF, OCR và phân tích dữ liệu.
- Điền số, ký hiệu, thể loại, trích yếu, tác giả và độ mật.
- Submit và xác minh trạng thái Hoàn thành.
- Ghi log và bỏ qua bản ghi lỗi để xử lý tiếp.

## Nợ kỹ thuật phải loại bỏ

- Không gom UI, browser, OCR và parser trong một lớp.
- Không dùng sleep cố định để chờ web.
- Không nuốt lỗi bằng catch rỗng.
- Không crop PDF theo tọa độ màn hình nếu có thể lấy file gốc.
- Không hard-code trường hợp lỗi trong workflow chính.
