# Quyết định kiến trúc

- ADR-001: Dùng Python vì OCR/PDF là phần phức tạp nhất và hệ sinh thái phù hợp hơn.
- ADR-002: Dùng Playwright thay Selenium để tận dụng locator auto-wait và trace.
- ADR-003: Dùng persistent profile riêng; không dùng profile Chrome cá nhân.
- ADR-004: Ưu tiên PDF bytes từ network, iframe hoặc download; screenshot chỉ là fallback cuối.
- ADR-005: Đọc text layer trước; PaddleOCR chỉ khởi tạo khi thật sự cần.
- ADR-006: SQLite dùng `sqlite3` chuẩn nhằm giảm kích thước và dependency.
- ADR-007: UI chỉ gửi lệnh và nhận sự kiện, không chứa logic OCR/browser.
- ADR-008: Bản ghi không chắc chắn được đánh dấu cần kiểm tra, không tự submit.
- ADR-009: Mọi lỗi thực tế sau này phải trở thành test hồi quy.
- ADR-010: Bản phát hành đầu dùng PyInstaller onedir, không onefile.
