import json
import logging
from datetime import timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import ScanHistory


logger = logging.getLogger(__name__)
history_bp = Blueprint("history", __name__, url_prefix="/history")
PER_PAGE = 10


def _decode_list(value):
    try:
        decoded = json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return decoded if isinstance(decoded, list) else []



def _to_vietnam_time(value):
    """
    MySQL server_default=NOW() is treated as UTC in this project.
    MySQL returns a naive datetime, so attach UTC before converting to UTC+7.
    """
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))


@history_bp.route("/")
def scan_history():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    search = request.args.get("q", "").strip()[:120]
    status = request.args.get("status", "all")
    if status not in {"all", "warning", "clear", "unknown", "no_profile"}:
        status = "all"
    sort = request.args.get("sort", "newest")
    if sort not in {"newest", "oldest"}:
        sort = "newest"
    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        page = 1

    try:
        query = ScanHistory.query.filter_by(user_id=session["user_id"])
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                or_(
                    ScanHistory.product_name.ilike(pattern),
                    ScanHistory.brand.ilike(pattern),
                )
            )
        if status != "all":
            query = query.filter_by(comparison_status=status)
        order = (
            ScanHistory.scanned_at.asc()
            if sort == "oldest"
            else ScanHistory.scanned_at.desc()
        )
        pagination = query.order_by(order, ScanHistory.id.desc()).paginate(
            page=page,
            per_page=PER_PAGE,
            error_out=False,
        )
        history_local_times = {
            item.id: _to_vietnam_time(item.scanned_at)
            for item in pagination.items
        }
        history_statuses = {}
        for item in pagination.items:
            saved_status = getattr(item, "comparison_status", None)
            if saved_status in {"warning", "clear", "unknown", "no_profile"}:
                history_statuses[item.id] = saved_status
            else:
                # Tương thích dữ liệu lịch sử cũ trước khi thêm comparison_status.
                old_warnings = _decode_list(item.warnings_json)
                if item.warning_status == "unknown":
                    history_statuses[item.id] = "unknown"
                else:
                    history_statuses[item.id] = (
                        "warning" if old_warnings else "clear"
                    )

        return render_template(
            "history.html",
            history=pagination.items,
            history_local_times=history_local_times,
            history_statuses=history_statuses,
            pagination=pagination,
            search=search,
            status=status,
            sort=sort,
            database_error=False,
        )
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Could not load scan history for current user.")
        return render_template(
            "history.html",
            history=[],
            history_local_times={},
            history_statuses={},
            pagination=None,
            search=search,
            status=status,
            sort=sort,
            database_error=True,
        ), 503


@history_bp.route("/<int:history_id>")
def scan_history_detail(history_id):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    try:
        history = ScanHistory.query.filter_by(
            id=history_id,
            user_id=session["user_id"],
        ).first()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Could not load scan history detail.")
        return render_template("history_detail.html", database_error=True), 503

    if history is None:
        abort(404)

    return render_template(
        "history_detail.html",
        history=history,
        ingredients=_decode_list(history.ingredients_json),
        allergens=_decode_list(history.allergens_json),
        warnings=_decode_list(history.warnings_json),
        comparison_status=(
            history.comparison_status
            or ("warning" if _decode_list(history.warnings_json) else
                "unknown" if history.warning_status == "unknown" else "clear")
        ),
        previous_warnings=_decode_list(
            getattr(history, "previous_warnings_json", None)
        ),
        previous_comparison_status=getattr(
            history, "previous_comparison_status", None
        ),
        database_error=False,
    )
