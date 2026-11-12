import hmac
import logging
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import db
from models import Product, User


logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
PRODUCTS_PER_PAGE = 20


def _csrf_token():
    token = session.get("admin_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["admin_csrf_token"] = token
    return token


@admin_bp.app_context_processor
def inject_admin_template_values():
    if request.blueprint == "admin":
        return {"admin_csrf_token": _csrf_token()}
    return {}


def _require_csrf():
    expected = session.get("admin_csrf_token", "")
    supplied = request.form.get("csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400)


def admin_required(view_function):
    """Authorize each admin request against the current database user record."""

    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("auth.login"))

        try:
            user = User.query.filter_by(id=user_id).first()
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Could not verify admin access.")
            return render_template(
                "admin/error.html",
                error_title="Không thể xác minh quyền truy cập",
                error_message="Vui lòng thử lại sau.",
            ), 503

        if user is None:
            session.clear()
            return redirect(url_for("auth.login"))

        if not user.is_active or not user.is_superuser:
            abort(403)

        g.admin_user = user
        return view_function(*args, **kwargs)

    return wrapped_view


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    """Keep the legacy URL working while sending everyone to the shared login."""
    return redirect(url_for("auth.login"))


@admin_bp.route("/logout", methods=["POST"])
@admin_required
def logout():
    _require_csrf()
    session.clear()
    flash("Bạn đã đăng xuất.", "success")
    return redirect(url_for("auth.login"))


@admin_bp.route("/")
@admin_required
def dashboard():
    seven_days_ago = datetime.now() - timedelta(days=7)
    try:
        total_products = Product.query.count()
        new_products = Product.query.filter(Product.created_at >= seven_days_ago).count()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Could not load admin dashboard statistics.")
        return render_template(
            "admin/error.html",
            error_title="Không thể tải dashboard",
            error_message="Vui lòng thử lại sau.",
        ), 503

    return render_template(
        "admin/dashboard.html",
        total_products=total_products,
        new_products=new_products,
        crawl_count=None,
        last_crawl=None,
    )


@admin_bp.route("/crawler")
@admin_required
def crawler_placeholder():
    return render_template("admin/crawler.html", selected_count=10, result=None)


@admin_bp.route("/crawler/start", methods=["POST"])
@admin_required
def crawler_start():
    _require_csrf()
    raw_count = request.form.get("count", "")
    try:
        requested_count = int(raw_count)
    except (TypeError, ValueError):
        return render_template(
            "admin/crawler.html",
            selected_count=10,
            result=None,
            error_message="Số lượng sản phẩm phải là một số nguyên hợp lệ.",
        ), 400

    from crawler.openfoodfacts_crawler import MAX_CRAWL_PRODUCTS, run_crawler

    if not 1 <= requested_count <= MAX_CRAWL_PRODUCTS:
        return render_template(
            "admin/crawler.html",
            selected_count=10,
            result=None,
            error_message=(
                f"S\u1ed1 l\u01b0\u1ee3ng ph\u1ea3i n\u1eb1m trong kho\u1ea3ng 1-{MAX_CRAWL_PRODUCTS}."
            ),
        ), 400

    # End the read-only transaction opened while admin_required checked the account.
    db.session.rollback()
    try:
        result = run_crawler(requested_count)
    except Exception:
        db.session.rollback()
        logger.exception("Admin-triggered Open Food Facts crawl failed.")
        result = {
            "requested_count": requested_count,
            "fetched_count": 0,
            "pages_fetched": 0,
            "requests_made": 0,
            "warnings": [],
            "inserted_count": 0,
            "duplicate_count": 0,
            "error_count": 1,
            "status": "error",
            "errors": ["Không thể hoàn tất yêu cầu crawl. Vui lòng thử lại sau."],
            "started_at": None,
            "finished_at": None,
        }

    return render_template(
        "admin/crawler.html",
        selected_count=requested_count,
        result=result,
    )


@admin_bp.route("/products")
@admin_required
def products():
    search = request.args.get("q", "").strip()[:120]
    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        page = 1

    query = Product.query
    if search:
        escaped_search = (
            search.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped_search}%"
        query = query.filter(
            or_(
                Product.name.ilike(pattern, escape="\\"),
                Product.brand.ilike(pattern, escape="\\"),
                Product.barcode.ilike(pattern, escape="\\"),
            )
        )

    try:
        pagination = query.order_by(Product.id.desc()).paginate(
            page=page,
            per_page=PRODUCTS_PER_PAGE,
            error_out=False,
        )
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Could not load admin product list.")
        return render_template(
            "admin/error.html",
            error_title="Không thể tải danh sách sản phẩm",
            error_message="Vui lòng thử lại sau.",
        ), 503

    return render_template(
        "admin/products.html",
        pagination=pagination,
        products=pagination.items,
        search=search,
    )


@admin_bp.route("/products/<int:product_id>")
@admin_required
def product_detail(product_id):
    try:
        product = db.session.get(Product, product_id)
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Could not load admin product detail.")
        return render_template(
            "admin/error.html",
            error_title="Không thể tải sản phẩm",
            error_message="Vui lòng thử lại sau.",
        ), 503
    if product is None:
        abort(404)
    return render_template("admin/product_detail.html", product=product)


def _product_form_values(product):
    values = {
        "name": request.form.get("name", "").strip(),
        "brand": request.form.get("brand", "").strip() or None,
        "barcode": request.form.get("barcode", "").strip() or None,
        "ingredients_text": request.form.get("ingredients_text", "").strip() or None,
        "allergens_text": request.form.get("allergens_text", "").strip() or None,
        "allergens_tags": request.form.get("allergens_tags", "").strip() or None,
        "image_url": request.form.get("image_url", "").strip() or None,
        "source_url": request.form.get("source_url", "").strip() or None,
    }
    limits = {"name": 255, "brand": 255, "barcode": 50, "image_url": 1000, "source_url": 1000}
    errors = []
    if not values["name"]:
        errors.append("Tên sản phẩm không được để trống.")
    for field, limit in limits.items():
        value = values[field]
        if value is not None and len(value) > limit:
            errors.append(f"Trường {field} vượt quá {limit} ký tự.")
    return values, errors


@admin_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(product_id):
    try:
        product = db.session.get(Product, product_id)
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Could not load product for editing.")
        return render_template(
            "admin/error.html",
            error_title="Không thể tải sản phẩm",
            error_message="Vui lòng thử lại sau.",
        ), 503
    if product is None:
        abort(404)

    form_values = None
    if request.method == "POST":
        _require_csrf()
        form_values, errors = _product_form_values(product)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "admin/product_edit.html", product=product, form_values=form_values
            ), 400

        for field, value in form_values.items():
            setattr(product, field, value)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Barcode này đã được dùng cho một sản phẩm khác.", "error")
            return render_template(
                "admin/product_edit.html", product=product, form_values=form_values
            ), 400
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Could not save admin product changes.")
            return render_template(
                "admin/error.html",
                error_title="Không thể lưu sản phẩm",
                error_message="Vui lòng thử lại sau.",
            ), 503

        flash("Sản phẩm đã được cập nhật.", "success")
        return redirect(url_for("admin.product_detail", product_id=product.id))

    return render_template(
        "admin/product_edit.html", product=product, form_values=form_values
    )


@admin_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def product_delete(product_id):
    _require_csrf()
    try:
        product = db.session.get(Product, product_id)
        if product is None:
            abort(404)
        db.session.delete(product)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Could not delete admin product.")
        return render_template(
            "admin/error.html",
            error_title="Không thể xóa sản phẩm",
            error_message="Vui lòng thử lại sau.",
        ), 503
    flash("Sản phẩm đã được xóa.", "success")
    return redirect(url_for("admin.products"))
