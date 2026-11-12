# pyrefly: ignore [missing-import]
import json
import logging

from flask import Blueprint, render_template, session, redirect, url_for
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import User, ScanHistory


main_bp = Blueprint("main", __name__)
logger = logging.getLogger(__name__)


def _decode_warnings(value):
    """Đọc danh sách cảnh báo đã lưu trong warnings_json."""
    try:
        decoded = json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _get_saved_comparison_status(item):
    """
    Dùng cùng quy tắc xác định trạng thái với routes/history.py:
    ưu tiên comparison_status đã lưu; dữ liệu cũ thì dùng warnings_json.
    """
    saved_status = getattr(item, "comparison_status", None)

    if saved_status in {"warning", "clear", "unknown", "no_profile"}:
        return saved_status

    if getattr(item, "warning_status", None) == "unknown":
        return "unknown"

    return "warning" if _decode_warnings(
        getattr(item, "warnings_json", None)
    ) else "clear"


# =========================
# TRANG CHỦ
# =========================
@main_bp.route("/")
def index():

    user = None

    # Nếu đã đăng nhập
    if "user_id" in session:
        user = User.query.get(session["user_id"])

    return render_template(
        "index.html",
        user=user
    )


# =========================
# DASHBOARD
# =========================
@main_bp.route("/dashboard")
def dashboard():

    # Chưa đăng nhập thì bắt đăng nhập
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    user = User.query.get(session["user_id"])
    recent_history = []
    history_error = False
    recent_statuses = {}
    try:
        recent_history = (
            ScanHistory.query
            .filter_by(user_id=session["user_id"])
            .order_by(ScanHistory.scanned_at.desc(), ScanHistory.id.desc())
            .limit(5)
            .all()
        )
        recent_statuses = {
            item.id: _get_saved_comparison_status(item)
            for item in recent_history
        }
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Could not load recent scan history for dashboard.")
        history_error = True

    return render_template(
        "dashboard.html",
        user=user,
        recent_history=recent_history,
        recent_statuses=recent_statuses,
        history_error=history_error,
    )
