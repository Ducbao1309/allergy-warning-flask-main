import json

from app import app
from models import Product, User, UserAllergen
from services.product_service import normalize_allergen_tag, normalize_allergen_tags


def check_product_allergy(user_id, product_id):

    # Lấy user
    user = User.query.filter_by(id=user_id).first()

    if not user:
        print("❌ Không tìm thấy user.")
        return

    # Lấy sản phẩm
    product = Product.query.filter_by(id=product_id).first()

    if not product:
        print("❌ Không tìm thấy sản phẩm.")
        return

    # =====================================================
    # LẤY DỊ ỨNG CỦA USER
    # =====================================================

    user_allergens = UserAllergen.query.filter_by(
        user_id=user.id
    ).all()

    print()
    print("================================")
    print("DỊ ỨNG CỦA USER")
    print("================================")

    for item in user_allergens:
        print(
            "-",
            item.allergen.name,
            "|",
            item.allergen.off_tag
        )

    # =====================================================
    # LẤY DỊ NGUYÊN CỦA SẢN PHẨM
    # =====================================================

    product_allergens = normalize_allergen_tags(
        json.loads(product.allergens_tags or "[]")
    )

    print()
    print("================================")
    print("DỊ NGUYÊN CỦA SẢN PHẨM")
    print("================================")

    for allergen in product_allergens:
        print("-", allergen)

    # =====================================================
    # SO SÁNH
    # =====================================================

    warnings = []

    for item in user_allergens:

        user_allergen_tag = item.allergen.off_tag
        canonical_tag = normalize_allergen_tag(user_allergen_tag)

        if canonical_tag and canonical_tag in product_allergens:

            warnings.append({
                "name": item.allergen.name,
                "off_tag": user_allergen_tag
            })

    # =====================================================
    # KẾT QUẢ
    # =====================================================

    print()
    print("================================")
    print("⚠️ CẢNH BÁO DỊ ỨNG")
    print("================================")

    if warnings:

        for warning in warnings:

            print(
                f"❌ {warning['name']} → Có trong sản phẩm"
            )

    else:

        print("✅ Không phát hiện dị nguyên mà user đã chọn.")


# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    with app.app_context():

        # Lấy user đầu tiên trong database
        user = User.query.first()

        # Lấy sản phẩm Nutella
        product = Product.query.filter_by(
            barcode="3017620422003"
        ).first()

        if not user:
            print("❌ Database chưa có user.")

        elif not product:
            print("❌ Database chưa có sản phẩm.")

        else:

            check_product_allergy(
                user.id,
                product.id
            )