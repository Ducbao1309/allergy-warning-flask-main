# Các chỉnh sửa trong bản rà soát

1. Trang tra cứu barcode dùng chung bộ đối chiếu dị ứng với luồng quét ảnh.
2. Trang tra cứu barcode hiển thị rõ trạng thái cảnh báo, chưa đủ dữ liệu và chưa phát hiện dị nguyên.
3. Khi lấy thành phần sản phẩm, ưu tiên các dòng đã chuẩn hóa trong `product_ingredients`, sắp xếp theo ID tăng dần; chỉ fallback sang `ingredients_text` với sản phẩm cũ chưa có dòng chi tiết.
4. Cập nhật `.env.example` cho đúng các biến cấu hình database, Gemini và Cloudinary.
5. `config.py` hỗ trợ `DATABASE_URL` khi triển khai hosting, đồng thời vẫn hỗ trợ cấu hình DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME.
6. Thêm `pytest.ini` để pytest chỉ thu thập bộ test trong thư mục `tests/`, tránh tự chạy các script kiểm tra kết nối/API ở thư mục gốc.

Không thay đổi cấu trúc bảng hoặc đánh lại ID sản phẩm. ID sản phẩm và ID thành phần vẫn dùng AUTO_INCREMENT.
