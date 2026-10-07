import requests
import json
import sys

from app import app
from extensions import db
from models import Product, ProductIngredient


# =========================================================
# LẤY SẢN PHẨM TỪ OPEN FOOD FACTS
# =========================================================

def get_product_from_openfoodfacts(barcode):

    url = f"https://world.openfoodfacts.org/api/v2/product/{barcode}"

    headers = {
        "User-Agent": "AllergyWarning/1.0"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    if data.get("status") != 1:
        return None

    return data["product"]


# =========================================================
# LƯU SẢN PHẨM
# =========================================================

def save_product(barcode):

    product_data = get_product_from_openfoodfacts(barcode)

    if not product_data:
        print("❌ Không tìm thấy sản phẩm.")
        return

    # -----------------------------------------------------
    # THÔNG TIN SẢN PHẨM
    # -----------------------------------------------------

    name = product_data.get("product_name")
    brand = product_data.get("brands")
    ingredients_text = product_data.get("ingredients_text")
    allergens_text = product_data.get("allergens")

    allergens_tags = product_data.get(
        "allergens_tags",
        []
    )

    image_url = product_data.get("image_url")

    source_url = (
        f"https://world.openfoodfacts.org/product/{barcode}"
    )

    # -----------------------------------------------------
    # KIỂM TRA SẢN PHẨM ĐÃ CÓ CHƯA
    # -----------------------------------------------------

    product = Product.query.filter_by(
        barcode=barcode
    ).first()

    if product:

        print("⚠️ Sản phẩm đã tồn tại → cập nhật dữ liệu.")

        product.name = name
        product.brand = brand
        product.ingredients_text = ingredients_text
        product.allergens_text = allergens_text

        product.allergens_tags = json.dumps(
            allergens_tags,
            ensure_ascii=False
        )

        product.image_url = image_url
        product.source_url = source_url

    else:

        product = Product(
            barcode=barcode,
            name=name,
            brand=brand,
            ingredients_text=ingredients_text,
            allergens_text=allergens_text,
            allergens_tags=json.dumps(
                allergens_tags,
                ensure_ascii=False
            ),
            image_url=image_url,
            source_url=source_url
        )

        db.session.add(product)

    db.session.commit()

    # =====================================================
    # LƯU TỪNG THÀNH PHẦN
    # =====================================================

    # Xóa thành phần cũ nếu sản phẩm đã tồn tại
    ProductIngredient.query.filter_by(
        product_id=product.id
    ).delete(
        synchronize_session=False
    )

    # Open Food Facts có danh sách ingredients dạng cấu trúc
    ingredients = product_data.get(
        "ingredients",
        []
    )

    for ingredient in ingredients:

        ingredient_name = ingredient.get("text")

        if not ingredient_name:
            continue

        ingredient_tag = ingredient.get("id")

        product_ingredient = ProductIngredient(
            product_id=product.id,
            name=ingredient_name,
            name_en=None,
            off_tag=ingredient_tag
        )

        db.session.add(product_ingredient)

    db.session.commit()

    # =====================================================
    # HIỂN THỊ KẾT QUẢ
    # =====================================================

    print()
    print("================================")
    print("ĐÃ LƯU SẢN PHẨM")
    print("================================")

    print("Tên:", product.name)
    print("Barcode:", product.barcode)

    print()
    print("CÁC THÀNH PHẦN ĐÃ LƯU:")

    saved_ingredients = ProductIngredient.query.filter_by(
        product_id=product.id
    ).all()

    for ingredient in saved_ingredients:
        print(
            "-",
            ingredient.name,
            "|",
            ingredient.off_tag
        )


# =========================================================
# CHẠY
# =========================================================

if __name__ == "__main__":

    # Dùng:
    # python save_product.py 8934563138165
    #
    # Hoặc truyền nhiều barcode cùng lúc:
    # python save_product.py 8934563138165 8934588063053
    barcodes = sys.argv[1:]

    if not barcodes:
        barcodes = ["3017620422003"]

    with app.app_context():

        for barcode in barcodes:

            print()
            print("================================")
            print("BARCODE:", barcode)
            print("================================")

            save_product(barcode)