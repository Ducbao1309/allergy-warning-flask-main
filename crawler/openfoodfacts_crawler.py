import json
import time

import requests

from app import app
from extensions import db
from models import Product, ProductIngredient


# =========================================================
# CẤU HÌNH
# =========================================================

API_URL = "https://world.openfoodfacts.org/api/v2/search"

# Số sản phẩm mỗi trang (Open Food Facts cho tối đa 100)
PAGE_SIZE = 50

# Số trang cần cào: 50 x 2 = 100 sản phẩm
# (muốn lấy gần hết ~1600 sản phẩm Việt Nam
# thì tăng PAGES lên khoảng 33)
PAGES = 2


# =========================================================
# USER-AGENT
# =========================================================

HEADERS = {
    "User-Agent": (
        "AllergyWarning/1.0 "
        "(student-project; "
        "contact: allergy-warning@example.com)"
    )
}


# =========================================================
# LẤY DỮ LIỆU TỪ OPEN FOOD FACTS
# =========================================================

def fetch_products():

    all_products = []

    print()
    print("========================================")
    print(" BẮT ĐẦU CÀO OPEN FOOD FACTS")
    print(f" {PAGES} trang x {PAGE_SIZE} sản phẩm/trang")
    print("========================================")

    # =====================================================
    # DUYỆT TỪNG TRANG
    # =====================================================

    for page in range(1, PAGES + 1):

        params = {
            "page_size": PAGE_SIZE,
            "page": page,

            # Chỉ lấy sản phẩm bán tại Việt Nam
            # (OFF hiện có khoảng 1600 sản phẩm)
            "countries_tags": "en:vietnam",

            "fields": (
                "code,"
                "product_name,"
                "brands,"
                "ingredients_text,"
                "allergens,"
                "allergens_tags,"
                "image_url,"
                "url,"
                "ingredients"
            )
        }

        print()
        print(f"→ Trang {page}/{PAGES} ...")

        try:

            response = requests.get(
                API_URL,
                params=params,
                headers=HEADERS,
                timeout=30
            )

            print(
                "HTTP STATUS:",
                response.status_code
            )

            response.raise_for_status()

        except requests.exceptions.RequestException as e:

            print()
            print("========================================")
            print("❌ LỖI KHI KẾT NỐI OPEN FOOD FACTS")
            print("========================================")
            print(e)

            break


        # =================================================
        # CHUYỂN RESPONSE SANG JSON
        # =================================================

        try:

            data = response.json()

        except ValueError:

            print()
            print("❌ Open Food Facts trả về dữ liệu không hợp lệ.")

            break


        products = data.get(
            "products",
            []
        )


        print(
            f"Trang {page}: {len(products)} sản phẩm."
        )

        all_products.extend(products)


        # Hết dữ liệu thì dừng sớm
        if len(products) < PAGE_SIZE:
            break

        # Nghỉ 1 giây giữa 2 trang
        # (tôn trọng server Open Food Facts)
        time.sleep(1)


    print(
        f"Tổng cộng lấy được {len(all_products)} sản phẩm."
    )

    return all_products


# =========================================================
# LƯU MỘT SẢN PHẨM
# =========================================================

def save_product(product_data):

    # =====================================================
    # LẤY THÔNG TIN
    # =====================================================

    barcode = product_data.get(
        "code"
    )

    name = product_data.get(
        "product_name"
    )


    # =====================================================
    # KIỂM TRA DỮ LIỆU
    # =====================================================

    if not barcode:

        print(
            "⚠ Bỏ qua sản phẩm không có barcode."
        )

        return False


    if not name:

        print(
            f"⚠ Bỏ qua sản phẩm {barcode}: không có tên."
        )

        return False


    # =====================================================
    # TÌM SẢN PHẨM TRONG DATABASE
    # =====================================================

    product = Product.query.filter_by(
        barcode=str(barcode)
    ).first()


    # =====================================================
    # NẾU CHƯA CÓ → TẠO MỚI
    # =====================================================

    if not product:

        product = Product(

            barcode=str(barcode),

            name=name,

            brand=product_data.get(
                "brands"
            ),

            ingredients_text=product_data.get(
                "ingredients_text"
            ),

            allergens_text=product_data.get(
                "allergens"
            ),

            allergens_tags=json.dumps(
                product_data.get(
                    "allergens_tags",
                    []
                ),
                ensure_ascii=False
            ),

            image_url=product_data.get(
                "image_url"
            ),

            source_url=product_data.get(
                "url"
            )
        )

        db.session.add(
            product
        )

        db.session.flush()

        print(
            f"✓ Thêm sản phẩm: {name}"
        )

    else:

        print(
            f"→ Đã tồn tại: {name}"
        )


    # =====================================================
    # LẤY DANH SÁCH THÀNH PHẦN
    # =====================================================

    ingredients = product_data.get(
        "ingredients",
        []
    )


    # =====================================================
    # XÓA THÀNH PHẦN CŨ
    # =====================================================

    ProductIngredient.query.filter_by(
        product_id=product.id
    ).delete(
        synchronize_session=False
    )


    # =====================================================
    # LƯU THÀNH PHẦN MỚI
    # =====================================================

    ingredient_count = 0


    for ingredient in ingredients:

        ingredient_name = ingredient.get(
            "text"
        )

        ingredient_id = ingredient.get(
            "id"
        )


        if not ingredient_name:

            continue


        product_ingredient = ProductIngredient(

            product_id=product.id,

            name=ingredient_name,

            name_en=ingredient_name,

            off_tag=ingredient_id

        )


        db.session.add(
            product_ingredient
        )

        ingredient_count += 1


    print(
        f"  └─ Thành phần: {ingredient_count}"
    )


    return True


# =========================================================
# CHẠY CRAWLER
# =========================================================

def run_crawler():

    # =====================================================
    # LẤY DỮ LIỆU
    # =====================================================

    products = fetch_products()


    if not products:

        print()
        print(
            "❌ Không có dữ liệu để lưu."
        )

        return


    saved_count = 0

    skipped_count = 0


    # =====================================================
    # KẾT NỐI APP CONTEXT
    # =====================================================

    with app.app_context():


        # =================================================
        # DUYỆT TỪNG SẢN PHẨM
        # =================================================

        for index, product_data in enumerate(
            products,
            start=1
        ):

            print()
            print(
                f"[{index}/{len(products)}]"
            )


            try:

                saved = save_product(
                    product_data
                )


                if saved:

                    saved_count += 1

                else:

                    skipped_count += 1


            except Exception as e:

                skipped_count += 1

                print(
                    "❌ Lỗi khi lưu sản phẩm:"
                )

                print(
                    type(e).__name__
                )

                print(
                    e
                )

                db.session.rollback()


        # =================================================
        # COMMIT DATABASE
        # =================================================

        try:

            db.session.commit()

            print()
            print("========================================")
            print(" CRAWLER HOÀN TẤT")
            print("========================================")

            print(
                f"✓ Đã lưu: {saved_count} sản phẩm"
            )

            print(
                f"⚠ Đã bỏ qua/lỗi: {skipped_count} sản phẩm"
            )

            print("========================================")


        except Exception as e:

            db.session.rollback()

            print()
            print("========================================")
            print("❌ LỖI COMMIT DATABASE")
            print("========================================")

            print(
                type(e).__name__
            )

            print(
                e
            )


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    run_crawler()