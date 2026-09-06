# Triển khai Windows

1. Cài Python 3.11 x64 chính thức từ python.org trên máy build.
2. Chạy `scripts/install_windows.ps1`.
3. Chạy toàn bộ test.
4. Chạy `scripts/freeze_dependencies.ps1` để khóa dependency của release.
5. Chạy `scripts/build_windows.ps1`.
6. Test thư mục trong `release/` trên máy Windows sạch.
7. Chỉ sau khi kiểm thử live site thành công mới tạo installer Inno Setup/MSI.

Bản đầu sử dụng PyInstaller `onedir` để dễ chẩn đoán và khởi động nhanh hơn `onefile`.
