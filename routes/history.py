import json
import logging

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


@history_bp.route("/")
def scan_history():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    search = request.args.get("q", "").strip()[:120]
    status = request.args.get("status", "all")
    if status not in {"all", "warning", "clear", "unknown"}:
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
            query = query.filter_by(warning_status=status)
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
        return render_template(
            "history.html",
            history=pagination.items,
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
        database_error=False,
    )
