import json

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import User, Allergen, UserAllergen, ScanHistory
from services.product_service import (
    check_product_ingredients,
)


profile_bp = Blueprint(
    "profile",
    __name__,
    url_prefix="/profile"
)


def _decode_json_list(value):
    """Đọc JSON list an toàn từ dữ liệu lịch sử."""
    try:
        decoded = json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _recalculate_user_scan_history(user_id, selected_allergen_tags):
    """
    Chỉ cập nhật kết quả đối chiếu cá nhân.
    Không thay đổi ingredients_json, allergens_json, warning_status
    hoặc thông tin nhận diện sản phẩm.
    """
    histories = ScanHistory.query.filter_by(user_id=user_id).all()

    for history in histories:
        ingredients = _decode_json_list(history.ingredients_json)
        declared_allergens = _decode_json_list(history.allergens_json)
        may_contain_allergens = _decode_json_list(
            getattr(history, "may_contain_json", None)
        )

        has_product_data = any(
            isinstance(value, str) and value.strip()
            for group in (
                ingredients,
                declared_allergens,
                may_contain_allergens,
            )
            for value in group
        )

        has_catalog_product = history.product_id is not None

        if not selected_allergen_tags:
            comparison_status = "no_profile"
            matches = []
        else:
            matches = check_product_ingredients(
                ingredients,
                selected_allergen_tags,
                declared_allergens,
                may_contain_allergens,
            )

            # Cảnh báo contains/may_contain luôn được ưu tiên.
            if matches:
                comparison_status = "warning"
            elif has_catalog_product and has_product_data:
                comparison_status = "clear"
            else:
                comparison_status = "unknown"

        # Lưu kết quả đối chiếu hiện tại thành kết quả trước đây
        # trước khi ghi kết quả tính lại theo hồ sơ mới.
        current_warnings = _decode_json_list(history.warnings_json)
        current_status = getattr(history, "comparison_status", None)

        # Tương thích các bản ghi lịch sử cũ chưa có comparison_status.
        # warnings_json là kết quả đối chiếu cá nhân đã lưu ở phiên bản trước.
        if current_status not in {"warning", "clear", "unknown", "no_profile"}:
            if history.warning_status == "unknown":
                current_status = "unknown"
            else:
                current_status = "warning" if current_warnings else "clear"

        # Lưu kết quả ngay trước lần thay đổi hồ sơ này để hiển thị bên dưới
        # kết quả mới. Không đụng tới dữ liệu nhận diện sản phẩm.
        history.previous_warnings_json = json.dumps(
            current_warnings,
            ensure_ascii=False,
        )
        history.previous_comparison_status = current_status

        history.warnings_json = json.dumps(
            matches,
            ensure_ascii=False,
        )
        history.comparison_status = comparison_status


@profile_bp.route("/", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(id=session["user_id"]).first()

    if not user:
        session.clear()
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        # Đọc và xác thực ID checkbox trước khi thay đổi dữ liệu.
        submitted_ids = set()
        for value in request.form.getlist("allergens"):
            try:
                submitted_ids.add(int(value))
            except (TypeError, ValueError):
                continue

        valid_allergens = Allergen.query.filter(
            Allergen.id.in_(submitted_ids)
        ).all() if submitted_ids else []

        new_allergen_ids = {item.id for item in valid_allergens}

        current_rows = UserAllergen.query.filter_by(
            user_id=user.id
        ).all()
        old_allergen_ids = {item.allergen_id for item in current_rows}

        # Chỉ cập nhật lịch sử khi hồ sơ thực sự thay đổi.
        profile_changed = old_allergen_ids != new_allergen_ids

        try:
            if profile_changed:
                UserAllergen.query.filter_by(
                    user_id=user.id
                ).delete(synchronize_session=False)

                for allergen in valid_allergens:
                    db.session.add(
                        UserAllergen(
                            user_id=user.id,
                            allergen_id=allergen.id,
                        )
                    )

                db.session.flush()

                selected_allergen_tags = {
                    allergen.off_tag
                    for allergen in valid_allergens
                    if allergen.off_tag
                }

                _recalculate_user_scan_history(
                    user.id,
                    selected_allergen_tags,
                )

            db.session.commit()

        except SQLAlchemyError:
            db.session.rollback()
            flash(
                "Không thể lưu hồ sơ hoặc cập nhật lịch sử. Vui lòng thử lại.",
                "error",
            )
            return redirect(url_for("profile.profile"))

        if profile_changed:
            flash(
                "Đã cập nhật hồ sơ dị ứng và tính lại kết quả đối chiếu trong lịch sử quét.",
                "success",
            )
        else:
            flash(
                "Hồ sơ dị ứng không thay đổi. Kết quả các lần quét được giữ nguyên.",
                "info",
            )

        return redirect(url_for("profile.profile"))

    allergens = Allergen.query.order_by(Allergen.name.asc()).all()

    user_allergens = UserAllergen.query.filter_by(
        user_id=user.id
    ).all()

    selected_allergen_ids = {
        item.allergen_id for item in user_allergens
    }

    return render_template(
        "profile.html",
        user=user,
        allergens=allergens,
        selected_allergen_ids=selected_allergen_ids,
    )
