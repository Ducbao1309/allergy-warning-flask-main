# pyrefly: ignore [missing-import]
import logging

from flask import Blueprint, render_template, session, redirect, url_for
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import User, ScanHistory


main_bp = Blueprint("main", __name__)
logger = logging.getLogger(__name__)


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
    try:
        recent_history = (
            ScanHistory.query
            .filter_by(user_id=session["user_id"])
            .order_by(ScanHistory.scanned_at.desc(), ScanHistory.id.desc())
            .limit(5)
            .all()
        )
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Could not load recent scan history for dashboard.")
        history_error = True

    return render_template(
        "dashboard.html",
        user=user,
        recent_history=recent_history,
        history_error=history_error,
    )
