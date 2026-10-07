from app import app
from models import Product, ProductIngredient


with app.app_context():

    products = Product.query.all()

    print()
    print("========================================")
    print(" KIỂM TRA DATABASE")
    print("========================================")

    print(
        f"Tổng số sản phẩm: {len(products)}"
    )

    print()

    for product in products:

        ingredients = ProductIngredient.query.filter_by(
            product_id=product.id
        ).all()

        print("----------------------------------------")

        print(
            f"Tên: {product.name}"
        )

        print(
            f"Barcode: {product.barcode}"
        )

        print(
            f"Brand: {product.brand}"
        )

        print(
            f"Thành phần: {len(ingredients)}"
        )

        print(
            f"Dị nguyên: {product.allergens_text}"
        )

        print(
            f"Dị nguyên tags: {product.allergens_tags}"
        )

    print("----------------------------------------")

    print()
    print("========================================")
    print(" KIỂM TRA HOÀN TẤT")
    print("========================================")