# Quy tắc code

1. Không `time.sleep()` để chờ web; dùng locator hoặc điều kiện Playwright.
2. Không `except: pass`.
3. Mọi public function phải có type hint.
4. Parser là hàm thuần, không truy cập trình duyệt hoặc database.
5. Page Object không chứa OCR hoặc business rule.
6. Workflow không chứa selector CSS/XPath trực tiếp.
7. Mọi file tạm phải nằm dưới `runtime/`.
8. Không ghi cookie, token hoặc mật khẩu vào log.
9. Submit phải được xác minh độc lập trước khi đánh dấu Completed.
10. Dependency OCR/UI/browser phải có import trì hoãn để phần lõi vẫn chạy được khi chưa cài extras.
