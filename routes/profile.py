from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from extensions import db
from models import User, Allergen, UserAllergen


# =========================================================
# PROFILE BLUEPRINT
# =========================================================

profile_bp = Blueprint(
    "profile",
    __name__,
    url_prefix="/profile"
)


# =========================================================
# HỒ SƠ CÁ NHÂN
# =========================================================

@profile_bp.route("/", methods=["GET", "POST"])
def profile():

    # -----------------------------------------------------
    # KIỂM TRA ĐĂNG NHẬP
    # -----------------------------------------------------

    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    # -----------------------------------------------------
    # LẤY USER ĐANG ĐĂNG NHẬP
    # -----------------------------------------------------

    user_id = session["user_id"]

    user = User.query.filter_by(id=user_id).first()

    if not user:
        session.clear()
        return redirect(url_for("auth.login"))

    # -----------------------------------------------------
    # XỬ LÝ KHI NHẤN "LƯU THÔNG TIN DỊ ỨNG"
    # -----------------------------------------------------

    if request.method == "POST":

        # Danh sách ID dị ứng được checkbox gửi lên
        selected_allergen_ids = request.form.getlist("allergens")

        # -------------------------------------------------
        # XÓA DANH SÁCH DỊ ỨNG CŨ CỦA USER NÀY
        # -------------------------------------------------

        UserAllergen.query.filter_by(
            user_id=user.id
        ).delete(
            synchronize_session=False
        )

        # -------------------------------------------------
        # THÊM LẠI DANH SÁCH DỊ ỨNG MỚI
        # -------------------------------------------------

        for allergen_id in selected_allergen_ids:

            allergen = Allergen.query.filter_by(
                id=allergen_id
            ).first()

            if allergen:

                user_allergen = UserAllergen(
                    user_id=user.id,
                    allergen_id=allergen.id
                )

                db.session.add(user_allergen)

        # -------------------------------------------------
        # LƯU DATABASE
        # -------------------------------------------------

        db.session.commit()

        flash(
            "Đã lưu thông tin dị ứng của bạn.",
            "success"
        )

        return redirect(
            url_for("profile.profile")
        )

    # =====================================================
    # GET - HIỂN THỊ HỒ SƠ
    # =====================================================

    # Lấy toàn bộ danh sách chất dị ứng
    allergens = Allergen.query.order_by(
        Allergen.name.asc()
    ).all()

    # -----------------------------------------------------
    # LẤY DỊ ỨNG ĐÃ CHỌN CỦA USER HIỆN TẠI
    # -----------------------------------------------------

    user_allergens = UserAllergen.query.filter_by(
        user_id=user.id
    ).all()

    # Chuyển thành set để template kiểm tra checkbox
    selected_allergen_ids = {
        item.allergen_id
        for item in user_allergens
    }

    # -----------------------------------------------------
    # TRẢ VỀ PROFILE.HTML
    # -----------------------------------------------------

    return render_template(
        "profile.html",
        user=user,
        allergens=allergens,
        selected_allergen_ids=selected_allergen_ids
    )