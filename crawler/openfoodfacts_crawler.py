
import json
import logging
import re
import time
import unicodedata
from datetime import datetime

import requests
from flask import has_app_context
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import app
from extensions import db
from models import Product, ProductIngredient


API_URL = "https://world.openfoodfacts.org/api/v2/search"
DETAIL_URL = "https://world.openfoodfacts.org/api/v2/product"

PAGE_SIZE = 50
MAX_CRAWL_PAGES = 10
MAX_CRAWL_PRODUCTS = 100
MAX_DISPLAYED_ERRORS = 10
MAX_REQUEST_ATTEMPTS = 4
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
REQUEST_TIMEOUT = 30

HEADERS = {
    "User-Agent": "AllergyWarning/1.0 (educational project)"
}

REQUIRED_FIELDS = (
    "barcode",
    "name",
    "brand",
    "ingredients_text",
    "allergens_text",
    "allergens_tags",
    "image_url",
    "source_url",
)

logger = logging.getLogger(__name__)


def normalize_product_text(value):
    """Chuẩn hóa văn bản để so sánh sản phẩm."""
    if not value:
        return ""

    value = unicodedata.normalize("NFKD", str(value).casefold())

    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )

    value = re.sub(r"[^a-z0-9]+", " ", value)

    return " ".join(value.split())


def _text(value):
    """Chỉ nhận giá trị văn bản không rỗng."""
    if not isinstance(value, str):
        return None

    value = value.strip()

    return value or None


def _get_barcode(data):
    value = data.get("code") or data.get("barcode")

    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None

    value = str(value).strip()

    if not value or len(value) > 50:
        return None

    return value


def _has_valid_url(value):
    value = _text(value)

    if not value:
        return False

    return value.startswith(("https://", "http://"))


def _extract_product(data):
    """
    Chuẩn hóa các trường từ Open Food Facts.
    Không tự tạo tên, thương hiệu hoặc thông tin dị ứng.
    """
    if not isinstance(data, dict):
        return None

    barcode = _get_barcode(data)
    name = _text(data.get("product_name") or data.get("name"))
    brand = _text(data.get("brands") or data.get("brand"))

    ingredients_text = _text(data.get("ingredients_text"))
    allergens_text = _text(data.get("allergens"))

    image_url = (
        _text(data.get("image_url"))
        or _text(data.get("image_front_url"))
        or _text(data.get("image_front_small_url"))
    )

    source_url = (
        _text(data.get("url"))
        or _text(data.get("source_url"))
    )

    raw_tags = data.get("allergens_tags")

    if isinstance(raw_tags, list):
        tags = sorted({
            tag.strip()
            for tag in raw_tags
            if isinstance(tag, str) and tag.strip()
        })
    else:
        tags = []

    result = {
        "barcode": barcode,
        "name": name,
        "brand": brand,
        "ingredients_text": ingredients_text,
        "allergens_text": allergens_text,
        "allergens_tags": tags,
        "image_url": image_url,
        "source_url": source_url,
        "ingredients": data.get("ingredients") or [],
    }

    return result


def _missing_required_fields(product):
    """Trả về các trường bắt buộc đang thiếu hoặc không hợp lệ."""
    if not product:
        return list(REQUIRED_FIELDS)

    missing = []

    for field in REQUIRED_FIELDS:
        value = product.get(field)

        if field == "allergens_tags":
            if not isinstance(value, list) or not value:
                missing.append(field)

        elif field in ("image_url", "source_url"):
            if not _has_valid_url(value):
                missing.append(field)

        elif not _text(value):
            missing.append(field)

    if product.get("name") and len(product["name"]) > 255:
        missing.append("name exceeds 255 characters")

    if product.get("brand") and len(product["brand"]) > 255:
        missing.append("brand exceeds 255 characters")

    if product.get("barcode") and len(product["barcode"]) > 50:
        missing.append("barcode exceeds 50 characters")

    if product.get("image_url") and len(product["image_url"]) > 1000:
        missing.append("image_url exceeds 1000 characters")

    if product.get("source_url") and len(product["source_url"]) > 1000:
        missing.append("source_url exceeds 1000 characters")

    return missing


def _request_json(url, params=None):
    """
    Gửi request có retry khi lỗi mạng, timeout hoặc HTTP tạm thời.
    Trả về (payload, error, request_count).
    """
    request_count = 0
    last_error = None

    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        try:
            request_count += 1

            response = requests.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            payload = response.json()

            if not isinstance(payload, dict):
                raise ValueError("API returned invalid JSON structure")

            return payload, None, request_count

        except requests.exceptions.RequestException as error:
            last_error = error
            status_code = getattr(error.response, "status_code", None)

            retryable = (
                status_code is None
                or status_code in RETRYABLE_STATUS_CODES
            )

            if not retryable or attempt >= MAX_REQUEST_ATTEMPTS:
                break

            wait_seconds = min(2 ** (attempt - 1), 16)

            logger.warning(
                "Request failed. Attempt %s/%s; retry in %s seconds: %s",
                attempt,
                MAX_REQUEST_ATTEMPTS,
                wait_seconds,
                error,
            )

            time.sleep(wait_seconds)

        except (ValueError, TypeError) as error:
            last_error = error
            break

    logger.error("Request failed after retries: %s", last_error)

    return None, str(last_error or "Unknown API error"), request_count


def fetch_products(page=1, page_size=PAGE_SIZE):
    """Lấy một trang danh sách sản phẩm."""
    if (
        isinstance(page, bool)
        or not isinstance(page, int)
        or not 1 <= page <= MAX_CRAWL_PAGES
    ):
        raise ValueError("Invalid page number")

    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= PAGE_SIZE
    ):
        raise ValueError("Invalid page size")

    params = {
        "page_size": page_size,
        "page": page,
        "countries_tags": "en:vietnam",
        "fields": (
            "code,product_name,brands,ingredients_text,allergens,"
            "allergens_tags,image_url,image_front_url,url,ingredients"
        ),
    }

    payload, error, request_count = _request_json(API_URL, params)

    if error:
        return {
            "products": [],
            "errors": [f"Page {page}: {error}"],
            "requests_made": request_count,
            "page_fetched": False,
        }

    products = payload.get("products")

    if not isinstance(products, list):
        return {
            "products": [],
            "errors": [f"Page {page}: API response has no product list."],
            "requests_made": request_count,
            "page_fetched": False,
        }

    return {
        "products": products[:page_size],
        "errors": [],
        "requests_made": request_count,
        "page_fetched": True,
    }


def fetch_product_detail(barcode):
    """Lấy dữ liệu chi tiết của sản phẩm theo barcode."""
    if not barcode:
        return None, "Missing barcode", 0

    url = f"{DETAIL_URL}/{barcode}.json"

    params = {
        "fields": (
            "code,product_name,brands,ingredients_text,allergens,"
            "allergens_tags,image_url,image_front_url,url,ingredients"
        )
    }

    payload, error, request_count = _request_json(url, params)

    if error:
        return None, error, request_count

    if payload.get("status") != 1:
        return None, "Product detail not found", request_count

    data = payload.get("product")

    if not isinstance(data, dict):
        return None, "Invalid product detail", request_count

    return data, None, request_count


def _load_complete_product(raw_data):
    """
    Nếu kết quả tìm kiếm thiếu trường, tải lại chi tiết theo barcode.
    Chỉ trả về sản phẩm nếu đủ tất cả trường bắt buộc.
    """
    product = _extract_product(raw_data)

    if not product or not product.get("barcode"):
        return None, ["barcode"], 0

    missing = _missing_required_fields(product)

    if missing:
        detail, error, request_count = fetch_product_detail(
            product["barcode"]
        )

        if detail:
            # Dữ liệu chi tiết được ưu tiên hơn dữ liệu tìm kiếm.
            detail_product = _extract_product(detail)

            if detail_product:
                product = detail_product

        elif error:
            logger.info(
                "Cannot complete product %s: %s",
                product["barcode"],
                error,
            )

        missing = _missing_required_fields(product)

        if missing:
            return None, missing, request_count

    return product, [], 0


def is_duplicate_product(barcode, name, brand):
    """Kiểm tra trùng barcode hoặc trùng tên + thương hiệu."""
    if barcode and Product.query.filter_by(barcode=barcode).first():
        return True

    normalized_name = normalize_product_text(name)
    normalized_brand = normalize_product_text(brand)

    if not normalized_name:
        return False

    # Tìm theo tên trước để tránh quét toàn bộ bảng không cần thiết.
    candidates = Product.query.all()

    for existing in candidates:
        if normalize_product_text(existing.name) != normalized_name:
            continue

        existing_brand = normalize_product_text(existing.brand)

        if normalized_brand and existing_brand:
            if normalized_brand == existing_brand:
                return True

        elif not normalized_brand and not existing_brand:
            return True

    return False


def save_product(product_data):
    """Chỉ lưu sản phẩm đầy đủ; trả False nếu trùng hoặc thiếu dữ liệu."""
    if not isinstance(product_data, dict):
        raise ValueError("Product data must be an object")

    missing = _missing_required_fields(product_data)

    if missing:
        logger.info(
            "Skipping incomplete product. Missing: %s",
            ", ".join(missing),
        )
        return False

    barcode = product_data["barcode"]
    name = product_data["name"]
    brand = product_data["brand"]

    if is_duplicate_product(barcode, name, brand):
        return False

    ingredients_text = product_data["ingredients_text"]
    allergens_text = product_data["allergens_text"]
    allergens_tags = product_data["allergens_tags"]
    image_url = product_data["image_url"]
    source_url = product_data["source_url"]

    # Chuẩn hóa danh sách thành phần, loại bỏ mục trùng.
    raw_ingredients = product_data.get("ingredients") or []

    if not isinstance(raw_ingredients, list):
        raw_ingredients = []

    normalized_ingredients = []
    seen_ingredients = set()

    for item in raw_ingredients:
        if not isinstance(item, dict):
            continue

        ingredient_name = _text(item.get("text"))

        if not ingredient_name:
            continue

        off_tag = _text(item.get("id"))

        key = (
            normalize_product_text(ingredient_name),
            normalize_product_text(off_tag),
        )

        if key in seen_ingredients:
            continue

        seen_ingredients.add(key)

        normalized_ingredients.append((ingredient_name, off_tag))

    product = Product(
        barcode=barcode,
        name=name,
        brand=brand,
        ingredients_text=ingredients_text,
        allergens_text=allergens_text,
        allergens_tags=json.dumps(
            allergens_tags,
            ensure_ascii=False,
        ),
        image_url=image_url,
        source_url=source_url,
    )

    db.session.add(product)
    db.session.flush()

    for ingredient_name, off_tag in normalized_ingredients:
        db.session.add(
            ProductIngredient(
                product_id=product.id,
                name=ingredient_name,
                name_en=ingredient_name,
                off_tag=off_tag,
            )
        )

    db.session.flush()

    return True


def _build_result(
    requested_count,
    fetched_count,
    inserted_count,
    duplicate_count,
    incomplete_count,
    errors,
    started_at,
    pages_fetched,
    requests_made,
    warnings,
    inserted_products,
):
    if inserted_count >= requested_count:
        status = "success"
    elif inserted_count > 0:
        status = "partial"
    elif errors:
        status = "error"
    else:
        status = "no_new"

    return {
        "requested_count": requested_count,
        "fetched_count": fetched_count,
        "inserted_count": inserted_count,
        "duplicate_count": duplicate_count,
        "incomplete_count": incomplete_count,
        "error_count": len(errors),
        "status": status,
        "pages_fetched": pages_fetched,
        "requests_made": requests_made,
        "warnings": warnings[:MAX_DISPLAYED_ERRORS],
        "errors": errors[:MAX_DISPLAYED_ERRORS],
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "new_products": inserted_products,
    }


def _safe_database_error_detail(error):
    original_error = getattr(error, "orig", None)
    detail = str(original_error or error).strip()

    detail = re.sub(
        r"(?i)(password|passwd|secret|api[_-]?key|token)"
        r"(\s*[=:]\s*)([^\s,;]+)",
        r"\1\2[redacted]",
        detail,
    )

    detail = re.sub(
        r"(://[^:/@\s]+:)[^@\s]+@",
        r"\1[redacted]@",
        detail,
    )

    return detail or error.__class__.__name__


def _run_crawler_in_context(requested_count):
    started_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    fetched_count = 0
    inserted_count = 0
    duplicate_count = 0
    incomplete_count = 0
    pages_fetched = 0
    requests_made = 0

    errors = []
    warnings = []
    inserted_products = []

    for page_number in range(1, MAX_CRAWL_PAGES + 1):
        if inserted_count >= requested_count:
            break

        fetch_result = fetch_products(
            page=page_number,
            page_size=PAGE_SIZE,
        )

        products = fetch_result["products"]
        errors.extend(fetch_result["errors"])
        requests_made += fetch_result["requests_made"]

        page_succeeded = fetch_result["page_fetched"]

        if page_succeeded:
            pages_fetched += 1
        else:
            warnings.append(
                f"Không tải được trang {page_number}; "
                "crawler tiếp tục thử trang sau."
            )
            time.sleep(2)
            continue

        fetched_count += len(products)

        for product_number, raw_data in enumerate(products, start=1):
            if inserted_count >= requested_count:
                break

            if not isinstance(raw_data, dict):
                incomplete_count += 1
                continue

            # Kiểm tra sơ bộ để bỏ qua barcode đã tồn tại.
            barcode = _get_barcode(raw_data)

            if not barcode:
                incomplete_count += 1
                continue

            if Product.query.filter_by(barcode=barcode).first():
                duplicate_count += 1
                continue

            try:
                product_data, missing, detail_requests = (
                    _load_complete_product(raw_data)
                )

                requests_made += detail_requests

                if not product_data:
                    incomplete_count += 1

                    logger.info(
                        "Skipping incomplete product %s; missing=%s",
                        barcode,
                        ", ".join(missing),
                    )
                    continue

                # Kiểm tra trùng tên/thương hiệu sau khi có đủ dữ liệu.
                if is_duplicate_product(
                    product_data["barcode"],
                    product_data["name"],
                    product_data["brand"],
                ):
                    duplicate_count += 1
                    continue

                with db.session.begin_nested():
                    inserted = save_product(product_data)

                db.session.commit()

                if not inserted:
                    duplicate_count += 1
                    continue

                inserted_count += 1

                saved = Product.query.filter_by(
                    barcode=product_data["barcode"]
                ).first()

                if saved:
                    inserted_products.append({
                        "id": saved.id,
                        "barcode": saved.barcode,
                        "name": saved.name,
                        "brand": saved.brand,
                        "ingredients_text": saved.ingredients_text,
                        "allergens_text": saved.allergens_text,
                        "allergens_tags": saved.allergens_tags,
                        "image_url": saved.image_url,
                        "source_url": saved.source_url,
                        "created_at": (
                            saved.created_at.isoformat(
                                sep=" ", timespec="seconds"
                            )
                            if saved.created_at
                            else ""
                        ),
                    })

            except IntegrityError as error:
                db.session.rollback()

                # Nếu có tiến trình khác vừa thêm cùng barcode,
                # coi đó là bản ghi trùng thay vì làm hỏng toàn bộ crawl.
                try:
                    duplicate = Product.query.filter_by(
                        barcode=barcode
                    ).first() is not None
                except SQLAlchemyError:
                    db.session.rollback()
                    duplicate = False

                db.session.rollback()

                if duplicate:
                    duplicate_count += 1
                else:
                    logger.exception(
                        "Database integrity error for barcode %s",
                        barcode,
                    )
                    errors.append(
                        "Database integrity error: "
                        + _safe_database_error_detail(error)
                    )

            except SQLAlchemyError as error:
                db.session.rollback()
                logger.exception(
                    "Database error saving barcode %s", barcode
                )
                errors.append(
                    "Database error: "
                    + _safe_database_error_detail(error)
                )

            except Exception:
                db.session.rollback()
                logger.exception(
                    "Unexpected crawler error for barcode %s", barcode
                )
                errors.append(
                    f"Không thể xử lý sản phẩm có barcode {barcode}."
                )

        # Nếu API trả ít hơn PAGE_SIZE, có thể đã hết dữ liệu phù hợp.
        if len(products) < PAGE_SIZE:
            break

        time.sleep(1)

    result = _build_result(
        requested_count=requested_count,
        fetched_count=fetched_count,
        inserted_count=inserted_count,
        duplicate_count=duplicate_count,
        incomplete_count=incomplete_count,
        errors=errors,
        started_at=started_at,
        pages_fetched=pages_fetched,
        requests_made=requests_made,
        warnings=warnings,
        inserted_products=inserted_products,
    )

    logger.info(
        "Crawler finished: requested=%s fetched=%s inserted=%s "
        "duplicates=%s incomplete=%s errors=%s",
        requested_count,
        fetched_count,
        inserted_count,
        duplicate_count,
        incomplete_count,
        result["error_count"],
    )

    return result


def run_crawler(requested_count=MAX_CRAWL_PRODUCTS):
    """Chạy crawler trong Flask application context."""

    if (
        isinstance(requested_count, bool)
        or not isinstance(requested_count, int)
        or not 1 <= requested_count <= MAX_CRAWL_PRODUCTS
    ):
        raise ValueError(
            f"requested_count must be between 1 and {MAX_CRAWL_PRODUCTS}"
        )

    if has_app_context():
        return _run_crawler_in_context(requested_count)

    with app.app_context():
        return _run_crawler_in_context(requested_count)


if __name__ == "__main__":
    run_crawler()
