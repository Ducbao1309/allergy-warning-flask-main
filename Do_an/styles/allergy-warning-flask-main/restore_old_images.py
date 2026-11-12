
import os
from pathlib import Path
from urllib.parse import urlparse

import pymysql
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv


# =====================================================
# 1. ĐỌC CẤU HÌNH
# =====================================================

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

UPLOAD_DIR = BASE_DIR / "static" / "uploads"

# ID trong TiDB và tên file ảnh trên máy tính
RESTORE_IMAGES = {
    1: "ca4d7c29-c819-42a3-adc7-8a455544889e.webp",
    2: "ef0447ad-a84f-4711-9f7e-5163bc0ebfef.webp",
    3: "9b48b599-dab4-443b-80a7-d4d154f7dfa9.webp",
    4: "80ebb26a-2f94-4484-a821-e197b1efed94.jpg",
    5: "02f46b72-06b5-4709-9543-491cf7e881e7.jpg",
    6: "006db7cf-2cd1-4c40-82ff-eecd338088c7.webp",
    7: "33d6c19b-4919-49a4-8b40-6d06313e6e85.webp",
}


def get_required_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Thiếu biến môi trường: {name}")
    return value


# =====================================================
# 2. KIỂM TRA CẤU HÌNH
# =====================================================

def configure_cloudinary():
    cloudinary.config(
        cloud_name=get_required_env("CLOUDINARY_CLOUD_NAME"),
        api_key=get_required_env("CLOUDINARY_API_KEY"),
        api_secret=get_required_env("CLOUDINARY_API_SECRET"),
        secure=True,
    )


def connect_database():
    host = get_required_env("DB_HOST")
    port = int(get_required_env("DB_PORT"))
    user = get_required_env("DB_USER")
    password = get_required_env("DB_PASSWORD")
    database = get_required_env("DB_NAME")

    ca_value = get_required_env("DB_SSL_CA")
    ca_path = Path(ca_value)

    if not ca_path.is_absolute():
        ca_path = BASE_DIR / ca_path

    if not ca_path.is_file():
        raise FileNotFoundError(
            f"Không tìm thấy chứng chỉ SSL: {ca_path}"
        )

    connection = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        ssl={"ca": str(ca_path)},
        connect_timeout=20,
        read_timeout=30,
        write_timeout=30,
        autocommit=False,
    )

    return connection


# =====================================================
# 3. UPLOAD VÀ KHÔI PHỤC
# =====================================================

def restore_images():
    configure_cloudinary()
    connection = connect_database()

    success = 0
    skipped = 0
    failed = 0

    try:
        with connection.cursor() as cursor:

            cursor.execute("SELECT DATABASE() AS db_name")
            db_info = cursor.fetchone()

            print("\nDatabase đang kết nối:", db_info["db_name"])
            print("Bắt đầu khôi phục ảnh...\n")

            for record_id, filename in RESTORE_IMAGES.items():

                image_path = UPLOAD_DIR / filename

                print(f"\nID {record_id}: {filename}")

                # Kiểm tra file ảnh
                if not image_path.is_file():
                    print("  [THIEU] Không tìm thấy ảnh trên máy.")
                    failed += 1
                    continue

                # Lấy bản ghi từ TiDB
                cursor.execute(
                    """
                    SELECT id, image_url
                    FROM scan_history
                    WHERE id = %s
                    """,
                    (record_id,),
                )

                record = cursor.fetchone()

                if not record:
                    print("  [BO QUA] Không tìm thấy ID trong database.")
                    skipped += 1
                    continue

                old_url = record["image_url"] or ""

                # Kiểm tra nếu ảnh đã được khôi phục
                if old_url.startswith("https://res.cloudinary.com/"):
                    print("  [BO QUA] Ảnh đã có URL Cloudinary.")
                    skipped += 1
                    continue

                # Kiểm tra tên ảnh trong database có khớp không
                old_filename = Path(
                    urlparse(old_url).path
                ).name

                if old_filename != filename:
                    print("  [CANH BAO] Tên ảnh không khớp database.")
                    print("  Database:", old_filename)
                    print("  Máy tính:", filename)
                    failed += 1
                    continue

                try:
                    # Upload lên Cloudinary
                    result = cloudinary.uploader.upload(
                        str(image_path),
                        folder="allergy-warning/scans",
                        public_id=f"restored_scan_{record_id}",
                        resource_type="image",
                        overwrite=True,
                    )

                    new_url = result.get("secure_url")

                    if not new_url:
                        raise RuntimeError(
                            "Cloudinary không trả về secure_url."
                        )

                    # Chỉ cập nhật đúng bản ghi và URL cũ
                    cursor.execute(
                        """
                        UPDATE scan_history
                        SET image_url = %s
                        WHERE id = %s
                          AND image_url = %s
                        """,
                        (new_url, record_id, old_url),
                    )

                    if cursor.rowcount != 1:
                        connection.rollback()
                        print(
                            "  [CANH BAO] Bản ghi đã thay đổi, "
                            "không cập nhật."
                        )
                        failed += 1
                        continue

                    connection.commit()

                    print("  [THANH CONG] Đã upload và cập nhật URL.")
                    success += 1

                except Exception as error:
                    connection.rollback()
                    print(
                        "  [LOI] Không khôi phục được:",
                        type(error).__name__,
                        str(error),
                    )
                    failed += 1

    finally:
        connection.close()

    print("\n" + "=" * 45)
    print("KẾT QUẢ KHÔI PHỤC")
    print("=" * 45)
    print("Thành công:", success)
    print("Bỏ qua:", skipped)
    print("Thất bại:", failed)
    print("=" * 45)


if __name__ == "__main__":
    try:
        restore_images()
    except Exception as error:
        print("\nCHƯƠNG TRÌNH DỪNG:")
        print(type(error).__name__, str(error))
