import json
import logging
import re
import time
from datetime import datetime

import requests
from flask import has_app_context
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import app
from extensions import db
from models import Product, ProductIngredient


API_URL = "https://world.openfoodfacts.org/api/v2/search"
PAGE_SIZE = 50
MAX_CRAWL_PAGES = 10
MAX_CRAWL_PRODUCTS = 100
MAX_DISPLAYED_ERRORS = 10
MAX_REQUEST_ATTEMPTS = 2
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
REQUEST_TIMEOUT = 30
HEADERS = {
    "User-Agent": "AllergyWarning/1.0 (educational project)"
}
logger = logging.getLogger(__name__)


def fetch_products(page=1, page_size=PAGE_SIZE):
    """Fetch one Open Food Facts page, preserving the existing API contract."""
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= MAX_CRAWL_PAGES:
        raise ValueError(f"page must be an integer between 1 and {MAX_CRAWL_PAGES}")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= PAGE_SIZE:
        raise ValueError(f"page_size must be an integer between 1 and {PAGE_SIZE}")

    params = {
        "page_size": page_size,
        "page": page,
        "countries_tags": "en:vietnam",
        "fields": (
            "code,product_name,brands,ingredients_text,allergens,"
            "allergens_tags,image_url,url,ingredients"
        ),
    }
    errors = []
    request_count = 0
    retry_count = 0
    response = None
    request_succeeded = False
    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        try:
            request_count += 1
            logger.info(
                "Open Food Facts outbound request: url=%s method=GET params=%s "
                "user_agent=%s timeout=%ss page=%s/%s attempt=%s/%s",
                API_URL, params, HEADERS["User-Agent"], REQUEST_TIMEOUT,
                page, MAX_CRAWL_PAGES, attempt, MAX_REQUEST_ATTEMPTS,
            )
            response = requests.get(
                API_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            request_succeeded = True
            break
        except requests.exceptions.RequestException as error:
            status_code = getattr(error.response, "status_code", None)
            if status_code in RETRYABLE_STATUS_CODES and attempt < MAX_REQUEST_ATTEMPTS:
                retry_count += 1
                logger.warning(
                    "Open Food Facts returned HTTP %s on page %s; retrying once.",
                    status_code, page,
                )
                time.sleep(1)
                continue
            logger.exception(
                "Open Food Facts request failed on page %s (HTTP status: %s).",
                page, status_code,
            )
            errors.append(
                f"Open Food Facts request failed (HTTP {status_code})."
                if status_code else "Could not connect to Open Food Facts."
            )
            break

    products = []
    if request_succeeded:
        try:
            payload = response.json()
        except ValueError:
            logger.exception("Open Food Facts returned invalid JSON on page %s.", page)
            errors.append("Open Food Facts returned invalid JSON.")
        else:
            if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
                logger.error("Open Food Facts returned an unexpected response on page %s.", page)
                errors.append("Open Food Facts returned an unexpected response shape.")
            else:
                products = payload["products"][:page_size]

    logger.info(
        "Open Food Facts page finished: page=%s fetched_count=%s http_requests=%s retries=%s errors=%s",
        page, len(products), request_count, retry_count, len(errors),
    )
    return {
        "products": products,
        "errors": errors,
        "requests_made": request_count,
        "page_fetched": request_succeeded and not errors,
    }

def _optional_text(value, field_name, max_length=None):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    value = value.strip()
    if not value:
        return None
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return value


def save_product(product_data):
    """Insert one validated product and its ingredients; return False if duplicate."""
    if not isinstance(product_data, dict):
        raise ValueError("Product data must be an object")

    raw_barcode = product_data.get("code")
    if raw_barcode is not None and not isinstance(raw_barcode, (str, int)):
        raise ValueError("Barcode must be text or an integer")
    barcode = str(raw_barcode).strip() if raw_barcode is not None else ""
    if not barcode:
        raise ValueError("Barcode is required")
    if len(barcode) > 50:
        raise ValueError("Barcode exceeds 50 characters")

    name = _optional_text(product_data.get("product_name"), "Product name", 255)
    if not name:
        raise ValueError("Product name is required")
    brand = _optional_text(product_data.get("brands"), "Brand", 255)
    ingredients_text = _optional_text(product_data.get("ingredients_text"), "Ingredients")
    allergens_text = _optional_text(product_data.get("allergens"), "Allergens")
    image_url = _optional_text(product_data.get("image_url"), "Image URL", 1000)
    source_url = _optional_text(product_data.get("url"), "Source URL", 1000)

    allergens_tags = product_data.get("allergens_tags")
    ingredients = product_data.get("ingredients")
    if allergens_tags is None:
        allergens_tags = []
    if ingredients is None:
        ingredients = []
    if not isinstance(allergens_tags, list) or not all(
        isinstance(tag, str) for tag in allergens_tags
    ):
        raise ValueError("Allergen tags must be a list of strings")
    if not isinstance(ingredients, list):
        raise ValueError("Ingredients must be a list")

    existing = Product.query.filter_by(barcode=barcode).first()
    if existing:
        return False

    normalized_ingredients = []
    for item in ingredients:
        if not isinstance(item, dict):
            raise ValueError("Ingredient data must be an object")
        ingredient_name = _optional_text(item.get("text"), "Ingredient name", 255)
        if not ingredient_name:
            continue
        off_tag = _optional_text(item.get("id"), "Ingredient tag", 255)
        normalized_ingredients.append((ingredient_name, off_tag))

    product = Product(
        barcode=barcode,
        name=name,
        brand=brand,
        ingredients_text=ingredients_text,
        allergens_text=allergens_text,
        allergens_tags=json.dumps(
            [tag.strip() for tag in allergens_tags if tag.strip()],
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
    errors,
    started_at,
    pages_fetched,
    requests_made,
    warnings,
):
    error_count = len(errors)
    if inserted_count >= requested_count:
        status = "success"
    elif inserted_count:
        status = "partial"
    elif error_count:
        status = "error"
    else:
        status = "no_new"
    return {
        "requested_count": requested_count,
        "fetched_count": fetched_count,
        "inserted_count": inserted_count,
        "duplicate_count": duplicate_count,
        "error_count": error_count,
        "status": status,
        "pages_fetched": pages_fetched,
        "requests_made": requests_made,
        "warnings": warnings[:MAX_DISPLAYED_ERRORS],
        "errors": errors[:MAX_DISPLAYED_ERRORS],
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _describe_validation_error(product_data, error):
    """Present the validation failure using only checks save_product performs."""
    message = str(error)
    if message == "Barcode is required":
        name = product_data.get("product_name") if isinstance(product_data, dict) else None
        if isinstance(name, str) and not name.strip() or name is None:
            return "missing barcode and product name"
        return "missing barcode"
    if message == "Product name is required":
        return "missing product name"
    if message == "Barcode must be text or an integer":
        return "invalid barcode: must be text or an integer"
    if message == "Product data must be an object":
        return "invalid product data"
    return message or "invalid product data"


def _safe_database_error_detail(error):
    """Return database diagnostics with common credential forms redacted."""
    original_error = getattr(error, "orig", None)
    detail = str(original_error or error).strip()
    detail = re.sub(
        r"(?i)(password|passwd|secret|api[_-]?key|token)(\s*[=:]\s*)([^\s,;]+)",
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
    pages_fetched = 0
    requests_made = 0
    errors = []
    warnings = []

    for page_number in range(1, MAX_CRAWL_PAGES + 1):
        fetch_result = fetch_products(page=page_number, page_size=PAGE_SIZE)
        products = fetch_result["products"]
        errors.extend(fetch_result["errors"])
        requests_made += fetch_result.get("requests_made", 1)
        page_succeeded = fetch_result.get("page_fetched", not fetch_result["errors"])
        if page_succeeded:
            pages_fetched += 1
        page_first_product_number = fetched_count + 1
        fetched_count += len(products)

        for product_offset, product_data in enumerate(products):
            if inserted_count >= requested_count:
                break
            product_number = page_first_product_number + product_offset
            try:
                # Each product has its own savepoint and commit; earlier successes survive later errors.
                with db.session.begin_nested():
                    inserted = save_product(product_data)
                db.session.commit()
                if inserted:
                    inserted_count += 1
                else:
                    duplicate_count += 1
                    logger.info(
                        "Product %s skipped: duplicate barcode.", product_number
                    )
            except IntegrityError as error:
                db.session.rollback()
                raw_barcode = product_data.get("code") if isinstance(product_data, dict) else None
                barcode = str(raw_barcode).strip() if raw_barcode is not None else None
                duplicate = False
                if barcode:
                    try:
                        duplicate = Product.query.filter_by(barcode=barcode).first() is not None
                    except SQLAlchemyError:
                        db.session.rollback()
                db.session.rollback()
                if duplicate:
                    duplicate_count += 1
                    logger.info(
                        "Product %s skipped: duplicate barcode.", product_number
                    )
                else:
                    logger.exception("Database integrity error saving crawler product %s.", product_number)
                    errors.append(
                        f"Product {product_number}: database error: "
                        f"{_safe_database_error_detail(error)}"
                    )
            except (ValueError, TypeError) as error:
                db.session.rollback()
                logger.warning("Skipping invalid crawler product %s: %s", product_number, error)
                errors.append(
                    f"Product {product_number}: "
                    f"{_describe_validation_error(product_data, error)}"
                )
            except SQLAlchemyError as error:
                db.session.rollback()
                logger.exception("Database error saving crawler product %s.", product_number)
                errors.append(
                    f"Product {product_number}: database error: "
                    f"{_safe_database_error_detail(error)}"
                )
            except Exception:
                db.session.rollback()
                logger.exception("Unexpected error saving crawler product %s.", product_number)
                errors.append(f"Product {product_number} failed while saving.")

        if inserted_count >= requested_count or not page_succeeded:
            break
        if len(products) < PAGE_SIZE:
            break
        if page_number == MAX_CRAWL_PAGES:
            warnings.append(
                f"Stopped at the safe limit of {MAX_CRAWL_PAGES} pages before reaching the requested number."
            )
            break
        time.sleep(1)

    result = _build_result(
        requested_count=requested_count,
        fetched_count=fetched_count,
        inserted_count=inserted_count,
        duplicate_count=duplicate_count,
        errors=errors,
        started_at=started_at,
        pages_fetched=pages_fetched,
        requests_made=requests_made,
        warnings=warnings,
    )
    print(
        "Crawler finished: "
        f"requested={result['requested_count']} "
        f"fetched={result['fetched_count']} "
        f"inserted={result['inserted_count']} "
        f"duplicates={result['duplicate_count']} "
        f"errors={result['error_count']} "
        f"pages={result['pages_fetched']} "
        f"status={result['status']}"
    )
    return result

def run_crawler(requested_count=MAX_CRAWL_PRODUCTS):
    """Fetch and save products, returning structured statistics for CLI or Admin use."""
    if (
        isinstance(requested_count, bool)
        or not isinstance(requested_count, int)
        or not 1 <= requested_count <= MAX_CRAWL_PRODUCTS
    ):
        raise ValueError(
            f"requested_count must be an integer between 1 and {MAX_CRAWL_PRODUCTS}"
        )

    if has_app_context():
        return _run_crawler_in_context(requested_count)

    with app.app_context():
        return _run_crawler_in_context(requested_count)


if __name__ == "__main__":
    run_crawler()
