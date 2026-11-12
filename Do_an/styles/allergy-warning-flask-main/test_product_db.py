from app import app
from models import Product
import json


def find_product_by_name(text):

    text_lower = text.lower()

    products = Product.query.all()

    for product in products:

        if not product.name:
            continue

        product_name = product.name.lower()

        # Ví dụ:
        # OCR có "nutella"
        # DB có sản phẩm "Nutella"

        if product_name in text_lower:

            return product

    return None


if __name__ == "__main__":

    with app.app_context():

        # =================================================
        # TEXT GIẢ LẬP KẾT QUẢ OCR
        # =================================================

        ocr_text = """
        Zucker, Palmöl, HASELNUSSE (13%),
        MAGERMILCHPULVER (8,7%),
        Kakao (7,4%), Emulgator Lecithine (SOJA),
        Vanilin.
        Nutella
        """

        # =================================================
        # TÌM SẢN PHẨM TRONG DATABASE
        # =================================================

        product = find_product_by_name(
            ocr_text
        )

        if not product:

            print("❌ Không tìm thấy sản phẩm trong database.")

        else:

            print()
            print("================================")
            print("TÌM THẤY SẢN PHẨM")
            print("================================")

            print("Tên:", product.name)
            print("Thương hiệu:", product.brand)
            print("Barcode:", product.barcode)

            print()
            print("THÀNH PHẦN TRONG DATABASE:")
            print(product.ingredients_text)

            print()
            print("DỊ NGUYÊN TRONG DATABASE:")

            allergens = json.loads(
                product.allergens_tags or "[]"
            )

            for allergen in allergens:

                print(
                    "-",
                    allergen
                )