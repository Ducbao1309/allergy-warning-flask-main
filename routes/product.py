from flask import Blueprint, render_template, request, redirect, url_for, session

from models import User, Product, UserAllergen
import json


product_bp = Blueprint(
    "product",
    __name__,
    url_prefix="/product"
)


# =========================================================
# TRANG KIỂM TRA SẢN PHẨM
# =========================================================

@product_bp.route("/check", methods=["GET", "POST"])
def check_product():

    # -----------------------------------------------------
    # KIỂM TRA ĐĂNG NHẬP
    # -----------------------------------------------------

    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]

    user = User.query.filter_by(
        id=user_id
    ).first()

    if not user:
        session.clear()
        return redirect(url_for("auth.login"))

    product = None
    warnings = []

    # -----------------------------------------------------
    # KHI USER NHẬP BARCODE
    # -----------------------------------------------------

    if request.method == "POST":

        barcode = request.form.get(
            "barcode",
            ""
        ).strip()

        if barcode:

            product = Product.query.filter_by(
                barcode=barcode
            ).first()

            if product:

                # =========================================
                # DỊ NGUYÊN CỦA SẢN PHẨM
                # =========================================

                product_allergens = json.loads(
                    product.allergens_tags or "[]"
                )

                # =========================================
                # DỊ ỨNG USER
                # =========================================

                user_allergens = UserAllergen.query.filter_by(
                    user_id=user.id
                ).all()

                # =========================================
                # SO SÁNH
                # =========================================

                for item in user_allergens:

                    user_tag = item.allergen.off_tag

                    if user_tag in product_allergens:

                        warnings.append({
                            "name": item.allergen.name,
                            "off_tag": user_tag
                        })

    # -----------------------------------------------------
    # HIỂN THỊ
    # -----------------------------------------------------

    return render_template(
        "product_check.html",
        user=user,
        product=product,
        warnings=warnings
    )