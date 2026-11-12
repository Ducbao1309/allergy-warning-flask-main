import json
import logging
import re
import time
import unicodedata
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
from flask import has_app_context
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import app
from extensions import db
from models import Product, ProductIngredient


# Open Food Facts public API. This is live data retrieved from the website,
# not an imported JSONL/CSV dump.
API_URL = "https://world.openfoodfacts.org/api/v2/search"

PAGE_SIZE = 50
MAX_CRAWL_PAGES = 10
MAX_CRAWL_PRODUCTS = 100
MAX_DISPLAYED_ERRORS = 10
MAX_REQUEST_ATTEMPTS = 4
REQUEST_TIMEOUT = 30
PAGE_DELAY_SECONDS = 2

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
FIELDS = (
    "code,product_name,brands,ingredients_text,allergens,"
    "allergens_tags,image_url,image_front_url,url,ingredients"
)

HEADERS = {
    "User-Agent": "AllergyWarning/1.0 (educational project; Open Food Facts data crawler)"
}

logger = logging.getLogger(__name__)


def normalize_product_text(value):
    """Chuẩn hóa văn bản để so sánh sản phẩm."""
    if not value:
        return ""

    value = unicodedata.normalize("NFKD", str(value).casefold())
    value = "".join(
        char for char in value if not unicodedata.combining(char)
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
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (str, int)):
        return None

    value = str(value).strip()
    if not value or len(value) > 50:
        return None
    return value


def _valid_url(value):
    value = _text(value)
    return value if value and value.startswith(("https://", "http://")) else None


def _extract_product(data):
    """Chuẩn hóa các trường được trả về từ Open Food Facts."""
    if not isinstance(data, dict):
        return None

    barcode = _get_barcode(data)
    name = _text(data.get("product_name") or data.get("name"))
    if not barcode or not name:
        return None

    raw_tags = data.get("allergens_tags")
    tags = []
    if isinstance(raw_tags, list):
        tags = sorted({
            tag.strip()
            for tag in raw_tags
            if isinstance(tag, str) and tag.strip()
        })

    ingredients = data.get("ingredients")
    if not isinstance(ingredients, list):
        ingredients = []

    product = {
        "barcode": barcode,
        "name": name[:255],
        "brand": (_text(data.get("brands") or data.get("brand")) or None),
        "ingredients_text": _text(data.get("ingredients_text")),
        "allergens_text": _text(data.get("allergens")),
        "allergens_tags": tags,
        "image_url": (
            _valid_url(data.get("image_url"))
            or _valid_url(data.get("image_front_url"))
        ),
        "source_url": (
            _valid_url(data.get("url"))
            or f"https://world.openfoodfacts.org/product/{barcode}"
        ),
        "ingredients": ingredients,
    }

    if product["brand"]:
        product["brand"] = product["brand"][:255]

    # Không bắt buộc phải có ảnh, thương hiệu hoặc allergen_tags.
    # Một sản phẩm vẫn hữu ích nếu có thành phần hoặc thông tin dị ứng.
    if not (
        product["ingredients_text"]
        or product["allergens_text"]
        or product["allergens_tags"]
    ):
        return None

    if len(product["image_url"] or "") > 1000:
        product["image_url"] = None
    if len(product["source_url"] or "") > 1000:
        product["source_url"] = (
            f"https://world.openfoodfacts.org/product/{barcode}"
        )

    return product


def _retry_delay(response, attempt):
    """Ưu tiên Retry-After của máy chủ, nếu không thì dùng exponential backoff."""
    retry_after = response.headers.get("Retry-After") if response is not None else None

    if retry_after:
        try:
            return min(max(float(retry_after), 1), 120)
        except (TypeError, ValueError):
            try:
                retry_date = parsedate_to_datetime(retry_after)
                seconds = (retry_date - datetime.now(retry_date.tzinfo)).total_seconds()
                return min(max(seconds, 1), 120)
            except (TypeError, ValueError, OverflowError):
                pass

    # Đợi lâu hơn khi bị giới hạn request (429).
    if response is not None and response.status_code == 429:
        return min(15 * attempt, 60)

    return min(5 * (2 ** (attempt - 1)), 60)


def _request_json(url, params=None):
    """
    Gửi request có retry và tôn trọng giới hạn của Open Food Facts.
    Trả về (payload, error, request_count).
    """
    request_count = 0
    last_error = None

    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        response = None
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
            status_code = getattr(response, "status_code", None)

            if status_code not in RETRYABLE_STATUS_CODES and status_code is not None:
                break
            if attempt >= MAX_REQUEST_ATTEMPTS:
                break

            wait_seconds = _retry_delay(response, attempt)
            logger.warning(
                "Open Food Facts request failed (%s). Retry %s/%s after %s seconds.",
                status_code or "network error",
                attempt,
                MAX_REQUEST_ATTEMPTS,
                wait_seconds,
            )
            time.sleep(wait_seconds)

        except (ValueError, TypeError) as error:
            last_error = error
            break

    logger.error("Open Food Facts request failed after retries: %s", last_error)
    return None, str(last_error or "Unknown API error"), request_count


def fetch_products(page=1, page_size=PAGE_SIZE):
    """Lấy một trang sản phẩm trực tiếp từ Open Food Facts."""
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
        "fields": FIELDS,
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


def _load_complete_product(raw_data):
    """
    Không gọi API chi tiết theo từng barcode nữa.
    Chỉ xử lý dữ liệu đã có trong kết quả tìm kiếm để giảm request và tránh 429.
    """
    product = _extract_product(raw_data)
    if not product:
        return None, ["barcode/name/ingredients_or_allergen_data"], 0
    return product, [], 0


def is_duplicate_product(barcode, name, brand):
    """Kiểm tra trùng barcode hoặc trùng tên + thương hiệu."""
    if barcode and Product.query.filter_by(barcode=barcode).first():
        return True

    normalized_name = normalize_product_text(name)
    normalized_brand = normalize_product_text(brand)
    if not normalized_name:
        return False

    # Chỉ lấy các sản phẩm có tên gần giống để không phải tải toàn bộ bảng.
    candidates = Product.query.filter(
        Product.name.ilike(f"%{name[:80]}%")
    ).all()

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


def _missing_required_fields(product):
    """Các trường tối thiểu để phục vụ chức năng cảnh báo dị ứng."""
    if not product:
        return ["product"]

    missing = []
    if not product.get("barcode"):
        missing.append("barcode")
    if not _text(product.get("name")):
        missing.append("name")

    has_allergy_data = bool(
        _text(product.get("ingredients_text"))
        or _text(product.get("allergens_text"))
        or (
            isinstance(product.get("allergens_tags"), list)
            and product.get("allergens_tags")
        )
    )
    if not has_allergy_data:
        missing.append("ingredients/allergen information")

    return missing


def save_product(product_data):
    """Lưu sản phẩm có dữ liệu thành phần/dị ứng; bỏ qua sản phẩm trùng."""
    if not isinstance(product_data, dict):
        raise ValueError("Product data must be an object")

    missing = _missing_required_fields(product_data)
    if missing:
        logger.info("Skipping incomplete product. Missing: %s", ", ".join(missing))
        return False

    barcode = product_data["barcode"]
    name = product_data["name"]
    brand = product_data.get("brand")

    if is_duplicate_product(barcode, name, brand):
        return False

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
        normalized_ingredients.append((ingredient_name[:255], off_tag))

    product = Product(
        barcode=barcode,
        name=name[:255],
        brand=brand[:255] if brand else None,
        ingredients_text=product_data.get("ingredients_text"),
        allergens_text=product_data.get("allergens_text"),
        allergens_tags=json.dumps(
            product_data.get("allergens_tags") or [],
            ensure_ascii=False,
        ),
        image_url=product_data.get("image_url"),
        source_url=product_data.get("source_url"),
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
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
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
    detail = re.sub(r"(://[^:/@\s]+:)[^@\s]+@", r"\1[redacted]@", detail)
    return detail or error.__class__.__name__


def _run_crawler_in_context(requested_count):
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")

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

        fetch_result = fetch_products(page=page_number, page_size=PAGE_SIZE)
        products = fetch_result["products"]
        errors.extend(fetch_result["errors"])
        requests_made += fetch_result["requests_made"]

        if not fetch_result["page_fetched"]:
            warnings.append(
                f"Không tải được trang {page_number}; crawler dừng để tránh "
                "gửi thêm request khi máy chủ đang lỗi."
            )
            break

        pages_fetched += 1
        fetched_count += len(products)

        for raw_data in products:
            if inserted_count >= requested_count:
                break

            if not isinstance(raw_data, dict):
                incomplete_count += 1
                continue

            barcode = _get_barcode(raw_data)
            if not barcode:
                incomplete_count += 1
                continue

            # Bỏ qua barcode đã có trước khi xử lý/lưu.
            if Product.query.filter_by(barcode=barcode).first():
                duplicate_count += 1
                continue

            try:
                product_data, missing, detail_requests = _load_complete_product(raw_data)
                requests_made += detail_requests

                if not product_data:
                    incomplete_count += 1
                    logger.info(
                        "Skipping incomplete product %s; missing=%s",
                        barcode,
                        ", ".join(missing),
                    )
                    continue

                if is_duplicate_product(
                    product_data["barcode"],
                    product_data["name"],
                    product_data.get("brand"),
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
                saved = Product.query.filter_by(barcode=product_data["barcode"]).first()

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
                            saved.created_at.isoformat(sep=" ", timespec="seconds")
                            if saved.created_at else ""
                        ),
                    })

            except IntegrityError as error:
                db.session.rollback()
                try:
                    duplicate = Product.query.filter_by(barcode=barcode).first() is not None
                except SQLAlchemyError:
                    db.session.rollback()
                    duplicate = False
                db.session.rollback()

                if duplicate:
                    duplicate_count += 1
                else:
                    logger.exception("Database integrity error for barcode %s", barcode)
                    errors.append(
                        "Database integrity error: " + _safe_database_error_detail(error)
                    )

            except SQLAlchemyError as error:
                db.session.rollback()
                logger.exception("Database error saving barcode %s", barcode)
                errors.append("Database error: " + _safe_database_error_detail(error))

            except Exception:
                db.session.rollback()
                logger.exception("Unexpected crawler error for barcode %s", barcode)
                errors.append(f"Không thể xử lý sản phẩm có barcode {barcode}.")

        # Nếu trang trả ít hơn PAGE_SIZE thì có thể đã hết dữ liệu.
        if len(products) < PAGE_SIZE:
            break

        # Nghỉ giữa các trang để hạn chế bị máy chủ giới hạn.
        time.sleep(PAGE_DELAY_SECONDS)

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
        "duplicates=%s incomplete=%s errors=%s requests=%s",
        requested_count,
        fetched_count,
        inserted_count,
        duplicate_count,
        incomplete_count,
        result["error_count"],
        requests_made,
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
    result = run_crawler()
    print(json.dumps(result, ensure_ascii=False, indent=2))
