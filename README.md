# Allergy Warning Flask

Ứng dụng Flask đọc nhãn thực phẩm bằng Gemini, đối chiếu thành phần với hồ sơ dị ứng của người dùng và lưu sản phẩm/lịch sử vào MySQL. Open Food Facts được dùng làm nguồn dữ liệu sản phẩm bổ sung.

## Yêu cầu

- Python 3.10 trở lên
- MySQL hoặc MariaDB
- Giá trị `GEMINI_API_KEY` được cấu hình trong `.env` để dùng phân tích ảnh

## Cài đặt trên Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Mở `.env` và điền cấu hình riêng của máy. Không commit `.env` hoặc đưa API key vào source code:

```dotenv
SECRET_KEY=replace-with-a-long-random-secret
DATABASE_URL=mysql+pymysql://root:password@localhost:3306/food_allergen_system
GEMINI_API_KEY=your-gemini-api-key
```

## Database

Tạo database `food_allergen_system`, sau đó chạy script tạo các bảng còn thiếu:

```powershell
python create_product_tables.py
```

Script dùng `db.create_all()` và không thay đổi cấu trúc bảng hiện có. Model `ScanHistory` bổ sung bảng `scan_history`; với database đã được tạo trước khi có lịch sử quét, chạy script trên một lần để tạo bảng mới. Không cần xóa/reset database. Trên database đã kiểm tra, `user.id` và `user_allergens.user_id` là `CHAR(32)`, vì vậy các model dùng cùng kiểu để khóa ngoại khớp; script vẫn kiểm tra các cột bắt buộc và độ dài ID trước khi tạo bảng.

Các bảng chính:

- `user`, `allergens`, `user_allergens`: tài khoản và hồ sơ dị ứng.
- `products`, `product_ingredients`: catalog sản phẩm và thành phần.
- `scan_history`: snapshot kết quả từng lần quét theo người dùng; dữ liệu thành phần, dị nguyên, cảnh báo và trạng thái được lưu để xem lại mà không gọi Gemini lần nữa.

## Chạy ứng dụng

```powershell
python app.py
```

Mở <http://127.0.0.1:5000>.

## Lịch sử quét

- Trang danh sách: `GET /history/`.
- Chi tiết: `GET /history/<id>`.
- Cần đăng nhập. Truy vấn luôn giới hạn theo `user_id` trong session; một tài khoản không thể xem lịch sử của tài khoản khác.
- Lịch sử được tạo sau khi phân tích và đối chiếu hoàn tất. Nếu sản phẩm chưa có trong catalog, lịch sử vẫn được lưu; khi người dùng bấm “Lưu sản phẩm”, hàng lịch sử được liên kết tới sản phẩm vừa lưu.
- Danh sách hỗ trợ tìm kiếm tên/thương hiệu, lọc trạng thái, sắp xếp thời gian và phân trang.

## Nạp dữ liệu sản phẩm/dị nguyên

- `python seed_allergens.py` tải taxonomy dị nguyên từ Open Food Facts.
- `python crawler/openfoodfacts_crawler.py` nạp catalog sản phẩm và thành phần.
- Các script này cần database và kết nối Internet.

## Ghi chú

Kết quả là thông tin hỗ trợ tham khảo, không thay thế tư vấn y tế. Hãy xác minh trực tiếp nhãn sản phẩm.
