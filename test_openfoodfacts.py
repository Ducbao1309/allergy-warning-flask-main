import requests


# =========================================================
# LẤY THÔNG TIN SẢN PHẨM TỪ OPEN FOOD FACTS
# =========================================================

def get_product(barcode):

    url = (
        f"https://world.openfoodfacts.org/api/v2/product/{barcode}"
    )

    headers = {
        "User-Agent": "AllergyWarning/1.0"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# TEST API
# =========================================================

barcode = "3017620422003"

data = get_product(barcode)


# =========================================================
# KIỂM TRA SẢN PHẨM
# =========================================================

if data.get("status") != 1:

    print("❌ Không tìm thấy sản phẩm.")

else:

    product = data["product"]


    # =====================================================
    # TẠO DỮ LIỆU SẢN PHẨM
    # =====================================================

    product_data = {

        "barcode": product.get("code"),

        "name": product.get(
            "product_name"
        ),

        "brand": product.get(
            "brands"
        ),

        "ingredients_text": product.get(
            "ingredients_text"
        ),

        "allergens": product.get(
            "allergens"
        ),

        "allergens_tags": product.get(
            "allergens_tags",
            []
        ),

        "image_url": product.get(
            "image_url"
        )
    }


    # =====================================================
    # HIỂN THỊ THÔNG TIN
    # =====================================================

    print("\n================================")
    print("THÔNG TIN SẢN PHẨM")
    print("================================")

    print(
        "Tên:",
        product_data["name"]
    )

    print(
        "Thương hiệu:",
        product_data["brand"]
    )

    print(
        "Barcode:",
        product_data["barcode"]
    )


    # =====================================================
    # THÀNH PHẦN
    # =====================================================

    print("\n================================")
    print("THÀNH PHẦN")
    print("================================")

    print(
        product_data["ingredients_text"]
    )


    # =====================================================
    # DỊ NGUYÊN
    # =====================================================

    print("\n================================")
    print("DỊ NGUYÊN")
    print("================================")

    print(
        product_data["allergens"]
    )


    # =====================================================
    # DỊ NGUYÊN TAG
    # =====================================================

    print("\n================================")
    print("DỊ NGUYÊN TAG")
    print("================================")

    if product_data["allergens_tags"]:

        for tag in product_data["allergens_tags"]:

            print(
                "-",
                tag
            )

    else:

        print(
            "Không có dữ liệu dị nguyên tag."
        )


    # =====================================================
    # ẢNH SẢN PHẨM
    # =====================================================

    print("\n================================")
    print("ẢNH SẢN PHẨM")
    print("================================")

    print(
        product_data["image_url"]
    )