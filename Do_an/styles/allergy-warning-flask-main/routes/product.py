import json

from flask import Blueprint, render_template, request, redirect, url_for, session

from models import User, Product, UserAllergen
from services.product_service import (
    check_product_ingredients,
    get_product_allergens,
    get_product_ingredients,
    should_mark_allergen_result_unknown,
)


product_bp = Blueprint(
    "product",
    __name__,
    url_prefix="/product"
)


@product_bp.route("/check", methods=["GET", "POST"])
def check_product():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(id=session["user_id"]).first()
    if not user:
        session.clear()
        return redirect(url_for("auth.login"))

    product = None
    warnings = []
    match_unknown = True
    warning_status = "unknown"
    ingredients = []

    if request.method == "POST":
        barcode = request.form.get("barcode", "").strip()

        if barcode:
            product = Product.query.filter_by(barcode=barcode).first()

        if product:
            # Dùng cùng bộ đối chiếu dị ứng với chức năng quét ảnh.
            user_allergens = (
                UserAllergen.query
                .filter_by(user_id=user.id)
                .all()
            )
            user_allergen_tags = {
                item.allergen.off_tag
                for item in user_allergens
                if item.allergen and item.allergen.off_tag
            }
            profile_names = {
                item.allergen.off_tag: item.allergen.name
                for item in user_allergens
                if item.allergen and item.allergen.off_tag
            }

            ingredients = get_product_ingredients(product)
            product_allergens = get_product_allergens(product)

            warnings = check_product_ingredients(
                ingredients,
                user_allergen_tags,
                product_allergens,
                [],
            )
            from services.product_service import normalize_allergen_tag

            canonical_profile_names = {
                normalize_allergen_tag(tag): name
                for tag, name in profile_names.items()
                if normalize_allergen_tag(tag)
            }
            for warning in warnings:
                warning["profile_name"] = canonical_profile_names.get(
                    warning["tag"], warning["allergen"]
                )

            match_unknown = should_mark_allergen_result_unknown(
                user_allergen_tags=user_allergen_tags,
                product_ingredients=ingredients,
                product_allergen_tags=product_allergens,
                gemini_allergens=[],
                may_contain_allergens=[],
                matches=warnings,
            )

            warning_status = (
                "unknown"
                if match_unknown
                else "warning"
                if warnings
                else "clear"
            )

    return render_template(
        "product_check.html",
        user=user,
        product=product,
        warnings=warnings,
        ingredients=ingredients,
        match_unknown=match_unknown,
        warning_status=warning_status,
    )
