import json
import logging
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
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
PRODUCT_API_URL = "https://world.openfoodfacts.org/api/v2/product"

PAGE_SIZE = 20
MAX_CRAWL_PAGES = 10  # số trang tối đa mỗi lần bấm cào
CRAWLER_STATE_FILE = Path(__file__).with_name('.openfoodfacts_crawler_state.json')
MAX_CRAWL_PRODUCTS = 100
MAX_DISPLAYED_ERRORS = 10
MAX_REQUEST_ATTEMPTS = 4
REQUEST_TIMEOUT = 25
PAGE_DELAY_SECONDS = 3
# Giãn cách mọi request (kể cả API chi tiết) để hạn chế HTTP 429.
MIN_REQUEST_INTERVAL_SECONDS = 6.5
_LAST_REQUEST_AT = 0.0

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
FIELDS = (
    "code,product_name,brands,ingredients_text,allergens,"
    "allergens_tags,image_url,image_front_url,url,ingredients"
)

HEADERS = {
    "User-Agent": "AllergyWarning/1.0 (nnanhs22@gmai.com)"
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



def _ingredient_key(value):
    """Khóa so sánh thành phần: bỏ khác biệt hoa/thường, dấu và khoảng trắng."""
    return normalize_product_text(value)


def _ingredient_identity(name, off_tag=None):
    tag_key = _ingredient_key(off_tag)
    return f"tag:{tag_key}" if tag_key else f"name:{_ingredient_key(name)}"


def _normalized_text_with_positions(value):
    """Chuẩn hóa chuỗi nhưng vẫn giữ vị trí ký tự gốc để cắt đúng văn bản."""
    chars = []
    positions = []
    for index, char in enumerate(str(value)):
        normalized = unicodedata.normalize("NFKD", char.casefold())
        for item in normalized:
            if unicodedata.combining(item):
                continue
            output = item if item.isalnum() else " "
            if output == " " and (not chars or chars[-1] == " "):
                continue
            chars.append(output)
            positions.append(index)

    while chars and chars[0] == " ":
        chars.pop(0)
        positions.pop(0)
    while chars and chars[-1] == " ":
        chars.pop()
        positions.pop()
    return "".join(chars), positions


def _clean_ingredients_text(value):
    """
    Lấy phần danh sách thành phần, loại phần hướng dẫn/quảng cáo/nhà sản xuất
    khi nhận diện được tiêu đề. Không tự suy đoán hoặc dịch tên thành phần.
    """
    text_value = _text(value)
    if not text_value:
        return ""

    normalized, positions = _normalized_text_with_positions(text_value)
    start_markers = ("thanh phan", "ingredients", "ingredient")
    start = None
    for marker in start_markers:
        match = re.search(r"\b" + re.escape(marker) + r"\b\s*[:：-]?", normalized)
        if match:
            original_index = positions[min(match.end() - 1, len(positions) - 1)]
            start = original_index + 1
            break
    if start is not None:
        text_value = text_value[start:].lstrip(" \\t:：-")

    normalized, positions = _normalized_text_with_positions(text_value)
    end_markers = (
        "huong dan bao quan",
        "huong dan su dung",
        "so t ncb",
        "msd nsx",
        "san pham cua",
        "dia chi",
        "uong bia co trach nhiem",
        "drink responsibly",
        "bao quan noi sach",
    )
    cut_positions = []
    for marker in end_markers:
        match = re.search(r"\b" + re.escape(marker) + r"\b\s*[:：-]?", normalized)
        if match and match.start() < len(positions):
            cut_positions.append(positions[match.start()])
    if cut_positions:
        text_value = text_value[:min(cut_positions)]

    return text_value.strip(" \\t\\r\\n.;,:-")


def _extract_ingredient_rows(product_data):
    """Tách thành phần từ ingredients_text, sau đó chuẩn hóa bằng từ điển.

    Ưu tiên text gốc vì một số bản ghi ingredients dạng cấu trúc của nguồn có
    thể chứa nhãn con/chuỗi bị lỗi. Nếu không có text, dùng mảng ingredients.
    """
    from services.ingredient_normalizer import normalize_ingredient, split_ingredient_text

    rows = []
    seen = set()

    raw_text = _text(product_data.get("ingredients_text"))
    if raw_text:
        for name in split_ingredient_text(raw_text):
            normalized = normalize_ingredient(name)
            key = normalized.get("standard_key") or _ingredient_key(name)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append((name[:255], normalized["normalized_name_en"], None,
                         normalized["normalized_name"], normalized["normalized_name_en"],
                         normalized["standard_key"], normalized["normalization_status"]))
        if rows:
            return rows

    raw_items = product_data.get("ingredients")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("text") or item.get("name"))
            if not name:
                continue
            off_tag = _text(item.get("id") or item.get("tag"))
            name_en = _text(item.get("text_en") or item.get("name_en"))
            normalized = normalize_ingredient(name, off_tag)
            key = normalized.get("standard_key") or _ingredient_key(name)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append((name[:255], name_en[:255] if name_en else None, off_tag,
                         normalized["normalized_name"], normalized["normalized_name_en"],
                         normalized["standard_key"], normalized["normalization_status"]))
    return rows


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
    if raw_tags is not None and not isinstance(raw_tags, list):
        return None
    tags = sorted({
        tag.strip()
        for tag in (raw_tags or [])
        if isinstance(tag, str) and tag.strip()
    })

    ingredients = data.get("ingredients")
    if not isinstance(ingredients, list):
        ingredients = []

    product = {
        "barcode": barcode,
        "code": barcode,
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

    # Barcode and name are enough for a catalog record. Missing allergy data
    # must remain unknown during matching, not cause the product to be discarded.
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
    """Gửi request JSON với retry đúng số lần cấu hình."""
    request_count = 0
    last_error = None

    global _LAST_REQUEST_AT

    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        response = None
        try:
            # Giới hạn tốc độ trên toàn crawler, không chỉ giữa các trang.
            elapsed = time.monotonic() - _LAST_REQUEST_AT
            wait_time = MIN_REQUEST_INTERVAL_SECONDS - elapsed
            if wait_time > 0:
                time.sleep(wait_time)

            request_count += 1
            response = requests.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            _LAST_REQUEST_AT = time.monotonic()
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Open Food Facts trả về JSON không hợp lệ.")
            return payload, None, request_count

        except requests.exceptions.Timeout as error:
            last_error = error
            # Timeout cũng có thể là lỗi mạng tạm thời.
            if attempt >= MAX_REQUEST_ATTEMPTS:
                break

        except requests.exceptions.HTTPError as error:
            last_error = error
            error_response = getattr(error, "response", None)
            # requests.Response có thể falsy với status >= 400, nên dùng is not None.
            failed_response = (
                error_response if error_response is not None else response
            )
            status_code = getattr(failed_response, "status_code", None)
            if status_code not in RETRYABLE_STATUS_CODES or attempt >= MAX_REQUEST_ATTEMPTS:
                break

        except requests.exceptions.RequestException as error:
            last_error = error
            if attempt >= MAX_REQUEST_ATTEMPTS:
                break

        except (ValueError, TypeError) as error:
            last_error = error
            break

        delay = _retry_delay(response, attempt)
        logger.warning(
            "Open Food Facts request lỗi (lần %s/%s): %s. Thử lại sau %s giây.",
            attempt, MAX_REQUEST_ATTEMPTS, last_error, delay
        )
        time.sleep(delay)

    logger.error("Open Food Facts request failed after %s attempts: %s",
                 request_count, last_error)
    if isinstance(last_error, requests.exceptions.RequestException):
        message = (
            f"Open Food Facts không phản hồi sau {request_count} lần thử "
            f"({getattr(getattr(last_error, 'response', None), 'status_code', 'lỗi kết nối')})."
        )
    else:
        message = str(last_error or "Invalid API response")
    return None, message, request_count


def fetch_products(page=1, page_size=PAGE_SIZE):
    """Lấy một trang sản phẩm trực tiếp từ Open Food Facts."""
    if (
        isinstance(page, bool)
        or not isinstance(page, int)
        or page < 1
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
            "page_count": 0,
            "count": 0,
        }

    products = payload.get("products")
    if not isinstance(products, list):
        return {
            "products": [],
            "errors": [f"Page {page}: API response has no product list."],
            "requests_made": request_count,
            "page_fetched": False,
            "page_count": 0,
            "count": 0,
        }

    # Open Food Facts v2: page_count là số sản phẩm trong trang hiện tại,
    # KHÔNG phải tổng số trang. Tổng số trang phải tính từ count/page_size.
    total_count = payload.get("count") or 0
    if isinstance(total_count, bool) or not isinstance(total_count, int) or total_count < 0:
        total_count = 0
    total_pages = (total_count + page_size - 1) // page_size if total_count else 0

    return {
        "products": products[:page_size],
        "errors": [],
        "requests_made": request_count,
        "page_fetched": True,
        "page_count": total_pages,
        "count": total_count,
    }


def _has_ingredient_data(product):
    """Chỉ coi sản phẩm đủ dữ liệu khi tách được ít nhất một thành phần hợp lệ."""
    if not isinstance(product, dict):
        return False
    return bool(_extract_ingredient_rows(product))


def _load_complete_product(raw_data):
    """
    Nếu trang tìm kiếm thiếu thành phần, gọi API chi tiết theo barcode.
    Không tự tạo thành phần/dị ứng khi nguồn không có dữ liệu.
    """
    product = _extract_product(raw_data)
    if not product:
        return None, ["barcode/name"], 0

    if _has_ingredient_data(product):
        return product, [], 0

    barcode = product["barcode"]
    detail_url = f"{PRODUCT_API_URL}/{barcode}"
    payload, error, request_count = _request_json(
        detail_url,
        params={"fields": FIELDS},
    )
    if error:
        return None, ["ingredients (detail API unavailable)"], request_count

    detail = payload.get("product")
    if not isinstance(detail, dict):
        return None, ["ingredients (not available at source)"], request_count

    # Ghép dữ liệu chi tiết lên kết quả tìm kiếm; ưu tiên giá trị có thật.
    merged = dict(raw_data)
    for key, value in detail.items():
        if value not in (None, "", [], {}):
            merged[key] = value

    complete = _extract_product(merged)
    if not complete or not _has_ingredient_data(complete):
        return None, ["ingredients (not provided by Open Food Facts)"], request_count

    return complete, [], request_count


def is_duplicate_product(barcode, name=None, brand=None):
    """
    Barcode là định danh ổn định của sản phẩm trên Open Food Facts.
    Không dùng riêng tên + thương hiệu để loại bản ghi vì các quy cách/
    hương vị khác nhau có thể cùng tên nhưng có barcode khác nhau.
    """
    if not barcode:
        return False
    return Product.query.filter_by(barcode=str(barcode).strip()).first() is not None


def _missing_required_fields(product):
    """Validate minimum identity fields; allergy information can be unknown."""
    if not product:
        return ["product"]
    missing = []
    if not product.get("barcode"):
        missing.append("barcode")
    if not _text(product.get("name")):
        missing.append("name")
    return missing


def save_product(product_data):
    """
    Lưu sản phẩm mới hoặc bổ sung dữ liệu cho barcode đã có.
    Trả về False nếu là bản ghi trùng theo khóa tên + thương hiệu.
    """
    if not isinstance(product_data, dict):
        raise ValueError("Product data must be an object")

    if "barcode" not in product_data or "name" not in product_data:
        product_data = _extract_product(product_data)

    missing = _missing_required_fields(product_data)
    if missing:
        raise ValueError("missing " + " and ".join(missing))

    barcode = product_data["barcode"]
    existing = Product.query.filter_by(barcode=barcode).first()
    ingredient_rows = _extract_ingredient_rows(product_data)

    if existing:
        # Chỉ cập nhật khi nguồn có giá trị; không ghi đè dữ liệu tốt bằng rỗng.
        existing.name = product_data.get("name") or existing.name
        existing.brand = product_data.get("brand") or existing.brand
        existing.ingredients_text = product_data.get("ingredients_text") or existing.ingredients_text
        existing.allergens_text = product_data.get("allergens_text") or existing.allergens_text
        existing.image_url = product_data.get("image_url") or existing.image_url
        existing.source_url = product_data.get("source_url") or existing.source_url

        incoming_tags = product_data.get("allergens_tags") or []
        if incoming_tags:
            try:
                old_tags = json.loads(existing.allergens_tags or "[]")
            except (TypeError, ValueError):
                old_tags = []
            old_tags = old_tags if isinstance(old_tags, list) else []
            existing.allergens_tags = json.dumps(
                sorted(set(old_tags) | set(incoming_tags)),
                ensure_ascii=False,
            )

        old_keys = {
            _ingredient_identity(row.name, row.off_tag)
            for row in existing.ingredients
            if _ingredient_key(row.name)
        }
        for (ingredient_name, name_en, off_tag, normalized_name,
             normalized_name_en, standard_key, normalization_status) in ingredient_rows:
            key = _ingredient_identity(ingredient_name, off_tag)
            if not _ingredient_key(ingredient_name) or key in old_keys:
                continue
            db.session.add(ProductIngredient(
                product_id=existing.id,
                name=ingredient_name,
                name_en=name_en,
                off_tag=off_tag,
                normalized_name=normalized_name,
                normalized_name_en=normalized_name_en,
                standard_key=standard_key,
                normalization_status=normalization_status,
            ))
            old_keys.add(key)

        db.session.flush()
        return True

    # Barcode là khóa chống trùng chính; mỗi barcode chỉ có một sản phẩm.
    if is_duplicate_product(barcode, product_data["name"], product_data.get("brand")):
        return False

    product = Product(
        barcode=barcode,
        name=product_data["name"][:255],
        brand=product_data.get("brand")[:255] if product_data.get("brand") else None,
        ingredients_text=product_data.get("ingredients_text"),
        allergens_text=product_data.get("allergens_text"),
        allergens_tags=json.dumps(product_data.get("allergens_tags") or [], ensure_ascii=False),
        image_url=product_data.get("image_url"),
        source_url=product_data.get("source_url"),
    )
    db.session.add(product)
    db.session.flush()

    for (ingredient_name, name_en, off_tag, normalized_name,
         normalized_name_en, standard_key, normalization_status) in ingredient_rows:
        db.session.add(ProductIngredient(
            product_id=product.id,
            name=ingredient_name,
            name_en=name_en,
            off_tag=off_tag,
            normalized_name=normalized_name,
            normalized_name_en=normalized_name_en,
            standard_key=standard_key,
            normalization_status=normalization_status,
        ))

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
    updated_count=0,
):
    if inserted_count >= requested_count:
        status = "success"
    elif inserted_count > 0:
        status = "partial"
    elif updated_count > 0:
        status = "updated"
    elif errors:
        status = "error"
    else:
        status = "no_new"

    return {
        "requested_count": requested_count,
        "fetched_count": fetched_count,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
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


def _load_crawler_state():
    """Đọc trang tiếp theo để các lần cào không lặp mãi từ trang 1."""
    try:
        if CRAWLER_STATE_FILE.exists():
            state = json.loads(CRAWLER_STATE_FILE.read_text(encoding="utf-8"))
            page = state.get("next_page", 1)
            if isinstance(page, int) and not isinstance(page, bool) and page >= 1:
                return page
    except (OSError, ValueError, TypeError):
        logger.warning("Không đọc được crawler state; bắt đầu lại từ trang 1.")
    return 1


def _save_crawler_state(next_page):
    """Lưu trang tiếp theo sau mỗi trang đã tải thành công."""
    try:
        CRAWLER_STATE_FILE.write_text(
            json.dumps({"next_page": max(1, int(next_page))}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        logger.exception("Không thể lưu vị trí trang crawler.")


def _run_crawler_in_context(requested_count):
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")

    fetched_count = 0
    inserted_count = 0
    updated_count = 0
    duplicate_count = 0
    incomplete_count = 0
    pages_fetched = 0
    requests_made = 0

    errors = []
    warnings = []
    inserted_products = []
    seen_barcodes = set()

    start_page = _load_crawler_state()
    current_page = start_page

    for page_offset in range(MAX_CRAWL_PAGES):
        if inserted_count >= requested_count:
            break

        page_number = current_page
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

        api_page_count = fetch_result.get("page_count") or 0
        if isinstance(api_page_count, int) and api_page_count > 0:
            next_page = 1 if page_number >= api_page_count else page_number + 1
        else:
            next_page = page_number + 1
        current_page = next_page
        page_completed = True

        for item_index, raw_data in enumerate(products, start=1):
            if inserted_count >= requested_count:
                page_completed = False
                break

            product_number = (page_number - 1) * PAGE_SIZE + item_index
            if not isinstance(raw_data, dict):
                incomplete_count += 1
                warnings.append(f"Product {product_number}: dữ liệu sản phẩm không hợp lệ, đã bỏ qua.")
                continue

            raw_barcode = raw_data.get("code", raw_data.get("barcode"))
            raw_name = raw_data.get("product_name", raw_data.get("name"))
            barcode = _get_barcode(raw_data)
            if raw_barcode is not None and not barcode:
                incomplete_count += 1
                warnings.append(f"Product {product_number}: mã vạch không hợp lệ, đã bỏ qua.")
                continue
            if not barcode or not _text(raw_name):
                incomplete_count += 1
                missing_fields = []
                if not barcode:
                    missing_fields.append("barcode")
                if not _text(raw_name):
                    missing_fields.append("product name")
                warnings.append(
                    f"Product {product_number}: thiếu " + " và ".join(missing_fields) + ", đã bỏ qua."
                )
                continue
            if raw_data.get("allergens_tags") is not None and not isinstance(raw_data.get("allergens_tags"), list):
                incomplete_count += 1
                warnings.append(f"Product {product_number}: dữ liệu allergens_tags không hợp lệ, đã bỏ qua.")
                continue

            # Tránh xử lý lặp cùng barcode trong một lượt cào.
            if barcode in seen_barcodes:
                duplicate_count += 1
                continue
            seen_barcodes.add(barcode)

            # Barcode đã tồn tại vẫn được kiểm tra để bổ sung trường còn thiếu.
            try:
                existed_before = Product.query.filter_by(barcode=barcode).first() is not None
                product_data, missing, detail_requests = _load_complete_product(raw_data)
                requests_made += detail_requests

                if not product_data:
                    incomplete_count += 1
                    logger.info(
                        "Skipping incomplete product %s; missing=%s",
                        barcode,
                        ", ".join(missing),
                    )
                    warnings.append(
                        f"Product {product_number}: thiếu thành phần hợp lệ, đã bỏ qua."
                    )
                    continue

                # save_product tự phân biệt barcode đã tồn tại (bổ sung dữ liệu)
                # với sản phẩm mới trùng tên/thương hiệu.
                with db.session.begin_nested():
                    inserted = save_product(product_data)

                db.session.commit()

                if not inserted:
                    duplicate_count += 1
                    continue

                saved = Product.query.filter_by(barcode=product_data["barcode"]).first()
                if existed_before:
                    updated_count += 1
                    continue

                inserted_count += 1
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
                        # Template crawler.html đọc trường này để hiển thị
                        # danh sách ProductIngredient ở cột "Thành phần đã chuẩn hóa".
                        "normalized_ingredients": [
                            {
                                "name": ingredient.name,
                                "name_en": ingredient.name_en,
                                "off_tag": ingredient.off_tag,
                            }
                            for ingredient in saved.ingredients
                        ],
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
                errors.append(
                    f"Product {product_number}: database error: "
                    + _safe_database_error_detail(error)
                )

            except Exception as error:
                db.session.rollback()
                logger.exception("Unexpected crawler error for barcode %s", barcode)
                errors.append(f"Product {product_number}: " + _safe_database_error_detail(error))

        # Chỉ chuyển sang trang kế tiếp sau khi xử lý hết trang.
        # Nếu đã đủ số sản phẩm giữa trang, lần sau đọc lại trang này;
        # barcode đã lưu sẽ tự được nhận diện và bỏ qua, không mất các mục phía sau.
        _save_crawler_state(next_page if page_completed else page_number)

        # Chỉ dừng khi API xác nhận không còn trang tiếp theo hoặc trang rỗng.
        if not products:
            break
        if api_page_count and page_number >= api_page_count:
            current_page = 1
            _save_crawler_state(1)
            break
        if not api_page_count and len(products) < PAGE_SIZE:
            break

        # Nghỉ giữa các trang để hạn chế bị máy chủ giới hạn.
        time.sleep(PAGE_DELAY_SECONDS)

    if (
        inserted_count < requested_count
        and pages_fetched >= MAX_CRAWL_PAGES
        and pages_fetched > 0
    ):
        warnings.append("Crawler stopped at the safe limit of pages.")

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
        updated_count=updated_count,
    )

    logger.info(
        "Crawler finished: requested=%s fetched=%s inserted=%s "
        "updated=%s duplicates=%s incomplete=%s errors=%s requests=%s",
        requested_count,
        fetched_count,
        inserted_count,
        updated_count,
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
