"""Thêm cột chuẩn hóa và xử lý lại thành phần của các sản phẩm đã lưu.

Chạy từ thư mục gốc dự án:
    python scripts/normalize_existing_ingredients.py

Script không xóa products, scan_history hoặc dữ liệu hồ sơ dị ứng. Nó chỉ
làm mới các dòng product_ingredients từ ingredients_text gốc khi tách được.
"""

from sqlalchemy import inspect, text

from app import app
from extensions import db
from models import Product, ProductIngredient
from services.ingredient_normalizer import normalize_ingredient, split_ingredient_text


NEW_COLUMNS = {
    "normalized_name": "VARCHAR(255) NULL",
    "normalized_name_en": "VARCHAR(255) NULL",
    "standard_key": "VARCHAR(120) NULL",
    "normalization_status": "VARCHAR(20) NOT NULL DEFAULT 'pending'",
}


def ensure_schema():
    inspector = inspect(db.engine)
    existing = {column["name"] for column in inspector.get_columns("product_ingredients")}
    for name, definition in NEW_COLUMNS.items():
        if name not in existing:
            db.session.execute(text(
                f"ALTER TABLE product_ingredients ADD COLUMN {name} {definition}"
            ))
    db.session.commit()

    inspector = inspect(db.engine)
    indexes = {item["name"] for item in inspector.get_indexes("product_ingredients")}
    if "ix_product_ingredients_standard_key" not in indexes:
        db.session.execute(text(
            "CREATE INDEX ix_product_ingredients_standard_key "
            "ON product_ingredients (standard_key)"
        ))
        db.session.commit()


def backfill():
    products = Product.query.order_by(Product.id.asc()).all()
    total_products = 0
    total_rows = 0
    matched_rows = 0
    unmatched_rows = 0

    for product in products:
        old_rows = list(product.ingredients)
        old_tags_by_key = {}
        for old in old_rows:
            old_norm = normalize_ingredient(old.name, old.off_tag)
            if old_norm.get("standard_key") and old.off_tag:
                old_tags_by_key.setdefault(old_norm["standard_key"], old.off_tag)

        names = split_ingredient_text(product.ingredients_text)
        if names:
            # Rebuild only the child ingredient rows from the original label text.
            # Product and scan-history records remain untouched.
            for old in old_rows:
                db.session.delete(old)
            db.session.flush()
            source_rows = [
                (name, old_tags_by_key.get(normalize_ingredient(name).get("standard_key")))
                for name in names
            ]
        else:
            # If no raw text exists, preserve current rows and normalize them in place.
            source_rows = [(row.name, row.off_tag) for row in old_rows]
            if not source_rows:
                continue
            for old in old_rows:
                db.session.delete(old)
            db.session.flush()

        for name, off_tag in source_rows:
            result = normalize_ingredient(name, off_tag)
            row = ProductIngredient(
                product_id=product.id,
                name=name[:255],
                name_en=None,
                off_tag=off_tag,
                normalized_name=result["normalized_name"],
                normalized_name_en=result["normalized_name_en"],
                standard_key=result["standard_key"],
                normalization_status=result["normalization_status"],
            )
            db.session.add(row)
            total_rows += 1
            if result["normalization_status"] == "matched":
                matched_rows += 1
            else:
                unmatched_rows += 1

        total_products += 1

        # Commit từng sản phẩm để tránh transaction quá lớn.
        db.session.commit()

    return {
        "products_processed": total_products,
        "ingredient_rows": total_rows,
        "matched": matched_rows,
        "unmatched": unmatched_rows,
    }


if __name__ == "__main__":
    with app.app_context():
        ensure_schema()
        result = backfill()
        print("Normalization backfill completed:")
        for key, value in result.items():
            print(f"- {key}: {value}")
