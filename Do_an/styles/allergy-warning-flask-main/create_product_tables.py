from app import app
from extensions import db
from sqlalchemy import inspect

# Quan trọng:
# import models để SQLAlchemy biết các model
from models import (
    User,
    Allergen,
    UserAllergen,
    Product,
    ProductIngredient,
    ScanHistory,
)


with app.app_context():

    inspector = inspect(db.engine)
    if inspector.has_table("user"):
        columns = {
            column["name"]: column
            for column in inspector.get_columns("user")
        }
        required_columns = {
            "id",
            "email",
            "full_name",
            "hashed_password",
            "is_active",
            "is_superuser",
            "created_at",
        }
        missing_columns = sorted(required_columns - columns.keys())
        if missing_columns:
            raise SystemExit(
                "Bảng user hiện có thiếu các cột mà ứng dụng cần: "
                + ", ".join(missing_columns)
                + ". Hãy sao lưu database và ánh xạ schema cũ theo README.md; "
                + "db.create_all() không sửa bảng đã tồn tại."
            )

        id_length = getattr(columns["id"]["type"], "length", None)
        if id_length != 32:
            raise SystemExit(
                f"user.id hiện có độ dài {id_length}, ứng dụng yêu cầu VARCHAR(32). "
                "Hãy xác nhận kiểu ID và khóa ngoại trước khi migration; "
                "không tự động rút ngắn ID để tránh mất dữ liệu."
            )

    if inspector.has_table("user_allergens"):
        user_allergen_columns = {
            column["name"]: column
            for column in inspector.get_columns("user_allergens")
        }
        if "user_id" not in user_allergen_columns:
            raise SystemExit(
                "Bảng user_allergens hiện có thiếu cột user_id; "
                "hãy sao lưu và migration schema cũ trước khi tiếp tục."
            )
        user_id_length = getattr(
            user_allergen_columns["user_id"]["type"], "length", None
        )
        if user_id_length != 32:
            raise SystemExit(
                f"user_allergens.user_id hiện có độ dài {user_id_length}, "
                "ứng dụng yêu cầu VARCHAR(32). Hãy migration đồng bộ với "
                "user.id trước khi tiếp tục."
            )

    db.create_all()

    print("================================")
    print("ĐÃ TẠO/CẬP NHẬT DATABASE TABLE")
    print("================================")

    print("✓ products")
    print("✓ product_ingredients")
    print("✓ scan_history")
