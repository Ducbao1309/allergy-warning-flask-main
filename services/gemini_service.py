import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import os
import re
import time
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image, ImageOps


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

_SECRET_PATTERNS = (
    re.compile(r"(?i)(x-goog-api-key\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(gemini_api_key\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)"),
    re.compile(r"(?i)(\b(?:api[_ -]?key|access[_ -]?token)\b\s*[:=]\s*[\"']?)([^\s\"'&,}]+)"),
    re.compile(r"(?i)([\"'](?:api[_-]?key|access[_-]?token|x-goog-api-key)[\"']\s*:\s*[\"'])([^\"']+)([\"'])"),
)


def _safe_log_value(value):
    if value is None:
        return None

    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    elif not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            value = str(value)

    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        value = value.replace(api_key, "[REDACTED]")

    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(lambda match: match.group(1) + "[REDACTED]", value)

    return value[:4000]


def _safe_getattr(value, attribute):
    try:
        return getattr(value, attribute, None)
    except Exception:
        return None


def _safe_response_headers(headers):
    if headers is None:
        return None

    try:
        header_items = headers.items()
    except Exception:
        return None

    sensitive_headers = {
        "authorization",
        "x-goog-api-key",
        "api-key",
        "access-token",
        "cookie",
        "set-cookie",
    }
    safe_headers = {}
    for name, value in header_items:
        header_name = str(name).strip().lower().replace("_", "-")
        if header_name in sensitive_headers:
            continue
        if any(secret_name in header_name for secret_name in (
            "authorization",
            "api-key",
            "access-token",
        )):
            continue
        safe_headers[str(name)] = _safe_log_value(value)
    return safe_headers


def _get_header(headers, wanted_name):
    if headers is None:
        return None

    try:
        for name, value in headers.items():
            if str(name).strip().lower() == wanted_name.lower():
                return value
    except Exception:
        return None
    return None


def _get_error_body(error, response):
    body = _safe_getattr(error, "body")
    if body is None:
        body = _safe_getattr(response, "text")
    if body is None:
        body = _safe_getattr(response, "content")
    if body is None:
        json_method = _safe_getattr(response, "json")
        if callable(json_method):
            try:
                body = json_method()
            except Exception:
                body = None
    return body


def _error_payload(body):
    if isinstance(body, dict):
        payload = body
    elif isinstance(body, (str, bytes)):
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            return {}
    else:
        return {}

    error_payload = payload.get("error", payload)
    return error_payload if isinstance(error_payload, dict) else {}


def _error_diagnostics(error):
    response = _safe_getattr(error, "response")
    status_code = (
        _safe_getattr(error, "status_code")
        or _safe_getattr(response, "status_code")
    )
    error_headers = _safe_getattr(error, "headers")
    response_headers = _safe_getattr(response, "headers")
    headers = error_headers or response_headers
    body = _get_error_body(error, response)
    payload = _error_payload(body)
    retry_after = (
        _get_header(error_headers, "retry-after")
        or _get_header(response_headers, "retry-after")
        or _safe_getattr(error, "retry_after")
    )
    error_code = (
        payload.get("code")
        or payload.get("status")
        or _safe_getattr(error, "error_code")
        or _safe_getattr(error, "code")
    )
    error_message = (
        payload.get("message")
        or _safe_getattr(error, "message")
        or str(error)
    )
    if status_code is None and isinstance(error_code, int):
        status_code = error_code

    return {
        "response": response,
        "status_code": status_code,
        "code": error_code,
        "message": error_message,
        "retry_after": retry_after,
        "headers": headers,
        "body": body,
    }


def _retry_after_seconds(value):
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass

    try:
        retry_at = parsedate_to_datetime(str(value))
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _is_transient_network_error(error):
    current = error
    for _ in range(5):
        if current is None:
            break
        if isinstance(current, (TimeoutError, ConnectionError)):
            return True
        exception_name = type(current).__name__.lower()
        if any(token in exception_name for token in (
            "timeout",
            "connectionerror",
            "connecterror",
            "networkerror",
            "protocolerror",
        )):
            return True
        current = _safe_getattr(current, "__cause__") or _safe_getattr(
            current, "__context__"
        )
    return False


def _is_retryable_error(diagnostics, error):
    status_code = str(diagnostics["status_code"] or "")
    error_code = str(diagnostics["code"] or "").lower()
    return (
        status_code in {"408", "429", "500", "502", "503", "504"}
        or error_code in {
            "rate_limit_exceeded",
            "quota_exceeded",
            "too_many_requests",
            "service_unavailable",
        }
        or _is_transient_network_error(error)
    )


def _log_api_error(error, diagnostics, attempt, elapsed_seconds):
    logger.error(
        "Gemini request failed after %.2fs; attempt=%s; exception_type=%s; "
        "error=%s; message=%s; "
        "response_type=%s; status_code=%s; retry_after=%s; headers=%s; body=%s",
        elapsed_seconds,
        attempt,
        type(error).__name__,
        _safe_log_value(str(error)),
        _safe_log_value(diagnostics["message"]),
        type(diagnostics["response"]).__name__
        if diagnostics["response"] is not None else None,
        _safe_log_value(diagnostics["status_code"]),
        _safe_log_value(diagnostics["retry_after"]),
        _safe_response_headers(diagnostics["headers"]),
        _safe_log_value(diagnostics["body"]),
    )
    logger.error(
        "[GEMINI ERROR] status=%s code=%s message=%s retry_after=%s",
        _safe_log_value(diagnostics["status_code"]),
        _safe_log_value(diagnostics["code"]),
        _safe_log_value(diagnostics["message"]),
        _safe_log_value(diagnostics["retry_after"]),
    )


def _service_error_for(diagnostics):
    is_rate_limited = (
        str(diagnostics["status_code"]) == "429"
        or str(diagnostics["code"] or "").lower() in {
            "rate_limit_exceeded",
            "quota_exceeded",
            "too_many_requests",
        }
    )
    if is_rate_limited:
        return GeminiServiceError(
            "Gemini API đang giới hạn request/quota. Vui lòng thử lại sau."
        )
    return GeminiServiceError(
        "Gemini tạm thời không khả dụng hoặc gặp lỗi khi phân tích ảnh. "
        "Vui lòng thử lại sau."
    )

GEMINI_MODEL="gemini-3.5-flash-lite"
REQUEST_TIMEOUT_SECONDS = 60
MAX_API_RETRIES = 2
MAX_RETRY_AFTER_SECONDS = 30
MAX_IMAGE_BYTES = 20 * 1024 * 1024

PRODUCT_LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "product_name": {
            "type": "string"
        },
        "brand": {
            "type": "string"
        },
        "ingredients": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },
        "allergens": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },
        "may_contain_allergens": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },
    },
    "required": [
        "product_name",
        "brand",
        "ingredients",
        "allergens",
        "may_contain_allergens",
    ],
}


LABEL_READING_PROMPT = """Read the food product label in the image and return structured JSON.

IMPORTANT:

Extraction priorities, in order:

- Product name
- Brand
- Ingredients / ingredient list
- Explicit allergen or "contains" statement
- Precautionary "may contain" statement and other visible food components

Search the whole image for ingredient and allergen sections in English,
Vietnamese, or mixed languages. Section headings may include "Ingredients",
"Ingredients:", "Composition", "Contains", "Allergen information", or
"May contain", as well as equivalent wording in other languages. Do not
require a Vietnamese heading to identify an ingredient list.

Keep ingredient wording in the language shown on the package. Do not translate
or infer ingredients from the product name, brand, product type, or from other
ingredients. If the text cannot be read, return an empty list for that field.

1. Read the actual ingredient list, not only highlighted, bold, uppercase,
   colored, or otherwise formatted words.

2. DO NOT use uppercase, bold, color, font weight, or visual formatting as
   the rule for detecting allergens.

3. The system must still detect an allergen when the same text is written
   in lowercase.

4. "ingredients" MUST contain only actual ingredients/components of the
   recipe.

5. "allergens" MUST contain allergens explicitly shown in the ingredient
   list or in an explicit "contains" / allergen statement. Do not infer
   allergens from the product name or product type.

6. "may_contain_allergens" MUST contain allergens mentioned ONLY in
   precautionary or cross-contact warning statements, for example:

   - "May contain ..."
   - "May contain traces of ..."
   - "May contain trace of ..."
   - "Kann ... enthalten"
   - "Kann Spuren von ... enthalten"
   - "Có thể chứa ..."
   - "Có thể chứa vết ..."

7. A precautionary statement is NOT an ingredient.

   For example:

   "Emulgator Lecithine (SOJA)"
       -> SOJA belongs to "allergens"

   "Kann SOJA, SENF und LUPINEN enthalten"
       -> SOJA, SENF, LUPINEN belong to "may_contain_allergens"

   Do NOT put the second sentence into "ingredients".

8. If an allergen appears both in the actual ingredient list and in the
   precautionary statement, put it in BOTH "allergens" and
   "may_contain_allergens".

9. Keep the original visible ingredient wording as much as possible.

10. A line break caused by the image layout is NOT a new ingredient.

    If a word is split with a trailing hyphen across lines, join it back.

    Example:
        "GERSTEN MALZEXTRAKT-"
        "PULVER (1,3%)"

    should become one ingredient:
        "GERSTEN MALZEXTRAKTPULVER (1,3%)"

11. Do not duplicate the same ingredient merely because:
    - percentage was removed,
    - capitalization differs,
    - a word was broken by a line break,
    - a hyphen was introduced by line wrapping.

12. Use only visible/readable information.
    Do not invent ingredients or allergens.

13. If a field is unreadable or uncertain, return an empty string or list.

14. Do not make medical or safety conclusions.

Return exactly these fields:

- product_name
- brand
- ingredients
- allergens
- may_contain_allergens
"""




class GeminiServiceError(Exception):
    """Base error for product-label analysis failures."""


class GeminiConfigurationError(GeminiServiceError):
    """Raised when Gemini credentials are unavailable."""


class InvalidProductImageError(GeminiServiceError):
    """Raised when the uploaded file is not a supported image."""


class InvalidGeminiResponseError(GeminiServiceError):
    """Raised when Gemini returns data outside the expected schema."""


def _emit_diagnostic(diagnostic_callback, stage, **details):
    if diagnostic_callback is not None:
        diagnostic_callback(stage, details)


def _image_payload(image_path, diagnostic_callback=None):
    logger.info("[GEMINI IMAGE 1] stat started")
    try:
        image_size = Path(image_path).stat().st_size
        logger.info("[GEMINI IMAGE 2] stat completed size_bytes=%s", image_size)
        if image_size > MAX_IMAGE_BYTES:
            raise InvalidProductImageError("The uploaded image is too large.")
    except OSError as error:
        logger.exception("[GEMINI IMAGE] stat failed")
        raise InvalidProductImageError("The uploaded image could not be read.") from error

    logger.info("[GEMINI IMAGE 3] Image.open verify started")
    try:
        with Image.open(image_path) as image:
            image_format = image.format
            image.verify()
        logger.info("[GEMINI IMAGE 4] Image.verify completed format=%s", image_format)
    except Exception as error:
        logger.exception("[GEMINI IMAGE] Image.open or verify failed")
        raise InvalidProductImageError("The uploaded file is not a valid image.") from error

    mime_type = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
    }.get(image_format)
    if not mime_type:
        raise InvalidProductImageError("The image format is not supported.")

    logger.info("[GEMINI IMAGE 5] image conversion started")
    try:
        with Image.open(image_path) as source:
            logger.info("[GEMINI IMAGE] EXIF transpose started")
            oriented_image = ImageOps.exif_transpose(source)
            logger.info("[GEMINI IMAGE] EXIF transpose completed")
            source_dimensions = oriented_image.size
            logger.info("[GEMINI IMAGE] RGB conversion started")
            image = oriented_image.convert("RGB")
            logger.info("[GEMINI IMAGE] RGB conversion completed")
            resampling = getattr(Image, "Resampling", Image)
            logger.info("[GEMINI IMAGE] thumbnail started")
            image.thumbnail((2048, 2048), resampling.LANCZOS)
            logger.info("[GEMINI IMAGE] thumbnail completed")
            outgoing_dimensions = image.size
            logger.info(
                "[GEMINI IMAGE] source_dimensions=%sx%s; outgoing_dimensions=%sx%s; jpeg_quality=85.",
                source_dimensions[0],
                source_dimensions[1],
                outgoing_dimensions[0],
                outgoing_dimensions[1],
            )
            logger.info("[GEMINI IMAGE 6] image conversion completed")
            output = BytesIO()
            logger.info("[GEMINI IMAGE 7] JPEG encoding started")
            image.save(output, format="JPEG", quality=85, optimize=True)
        logger.info("[GEMINI IMAGE 7] JPEG encoding completed")
    except Exception as error:
        logger.exception("[GEMINI IMAGE] image conversion or JPEG encoding failed")
        raise InvalidProductImageError("The uploaded image could not be processed.") from error

    logger.info("[GEMINI IMAGE 8] base64 encoding started")
    encoded_image = base64.b64encode(output.getvalue()).decode("ascii")
    logger.info(
        "[GEMINI IMAGE 8] base64 encoding completed chars=%s",
        len(encoded_image),
    )
    _emit_diagnostic(
        diagnostic_callback,
        "image",
        image_file=Path(image_path).name,
        source_mime_type=mime_type,
        outgoing_mime_type="image/jpeg",
        source_dimensions=source_dimensions,
        processed_dimensions=outgoing_dimensions,
        jpeg_quality=85,
        exif_transpose=True,
        resize_limit=(2048, 2048),
    )
    return (
        encoded_image,
        "image/jpeg",
        mime_type,
    )


def _normalize_response(response_text, diagnostic_callback=None):
    if not response_text:
        raise InvalidGeminiResponseError(
            "Gemini returned an empty response."
        )

    try:
        result = json.loads(response_text)
    except (json.JSONDecodeError, TypeError) as error:
        raise InvalidGeminiResponseError(
            "Gemini returned invalid JSON."
        ) from error

    if not isinstance(result, dict):
        raise InvalidGeminiResponseError(
            "Gemini returned an invalid data structure."
        )

    logger.info(
        "[GEMINI] response_fields=%s; ingredients_field_present=%s; ingredients_field_type=%s.",
        sorted(result),
        "ingredients" in result,
        type(result.get("ingredients", [])).__name__,
    )
    _emit_diagnostic(
        diagnostic_callback,
        "response_fields",
        response_type=type(result).__name__,
        response_keys=sorted(result),
        ingredients_field_present="ingredients" in result,
        ingredients_raw_type=type(result.get("ingredients")).__name__
        if "ingredients" in result else "missing",
        ingredients_raw_value=result.get("ingredients"),
        allergens_field_present="allergens" in result,
        allergens_raw_type=type(result.get("allergens")).__name__
        if "allergens" in result else "missing",
        allergens_raw_value=result.get("allergens"),
        raw_product_name=result.get("product_name"),
    )

    product_name = result.get("product_name", "")
    brand = result.get("brand", "")
    ingredients = result.get("ingredients", [])
    allergens = result.get("allergens", [])
    may_contain_allergens = result.get(
        "may_contain_allergens",
        []
    )

    # ========================================
    # KIỂM TRA PRODUCT NAME
    # ========================================

    if not isinstance(product_name, str):
        raise InvalidGeminiResponseError(
            "Gemini returned an invalid product name."
        )

    # ========================================
    # KIỂM TRA BRAND
    # ========================================

    if not isinstance(brand, str):
        raise InvalidGeminiResponseError(
            "Gemini returned an invalid brand."
        )

    # ========================================
    # KIỂM TRA INGREDIENTS
    # ========================================

    if isinstance(ingredients, str):
        ingredients = [ingredients]

    if not isinstance(ingredients, list) or not all(
        isinstance(item, str)
        for item in ingredients
    ):
        raise InvalidGeminiResponseError(
            "Gemini returned an invalid ingredient list."
        )

    # ========================================
    # KIỂM TRA ALLERGENS
    # ========================================

    if not isinstance(allergens, list) or not all(
        isinstance(item, str)
        for item in allergens
    ):
        raise InvalidGeminiResponseError(
            "Gemini returned an invalid allergen list."
        )

    # ========================================
    # KIỂM TRA MAY-CONTAIN ALLERGENS
    # ========================================

    if not isinstance(
        may_contain_allergens,
        list
    ) or not all(
        isinstance(item, str)
        for item in may_contain_allergens
    ):
        raise InvalidGeminiResponseError(
            "Gemini returned an invalid "
            "may-contain allergen list."
        )

    # ========================================
    # CHUẨN HÓA KẾT QUẢ
    # ========================================

    normalized_ingredients = list(
        dict.fromkeys(
            item.strip()
            for item in ingredients
            if item.strip()
        )
    )

    normalized_allergens = list(
        dict.fromkeys(
            item.strip()
            for item in allergens
            if item.strip()
        )
    )

    normalized_may_contain = list(
        dict.fromkeys(
            item.strip()
            for item in may_contain_allergens
            if item.strip()
        )
    )

    return {
        "product_name": product_name.strip(),

        "brand": brand.strip(),

        "ingredients": normalized_ingredients,

        "allergens": normalized_allergens,

        "may_contain_allergens": normalized_may_contain,
    }


def analyze_product_image(image_path, diagnostic_callback=None):
    """Send a product-label image to Gemini and return structured label data."""
    logger.info(
        "[GEMINI RUNTIME] analyze_product_image ENTERED file=%s",
        __file__,
    )
    analysis_started_at = time.perf_counter()
    logger.info("[GEMINI STAGE 1] analyze_product_image entered")
    logger.info("[GEMINI STAGE 2] checking API key")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiConfigurationError("GEMINI_API_KEY is not configured.")
    logger.info("[GEMINI STAGE 3] API key available")

    image_preparation_started_at = time.perf_counter()
    logger.info("Gemini image preparation started; source=%s", Path(image_path).name)
    logger.info("[GEMINI STAGE 4] calling _image_payload")
    encoded_image, mime_type, source_mime_type = _image_payload(
        image_path,
        diagnostic_callback=diagnostic_callback,
    )
    _emit_diagnostic(
        diagnostic_callback,
        "request",
        model=GEMINI_MODEL,
        prompt=LABEL_READING_PROMPT,
        outgoing_mime_type=mime_type,
    )
    logger.info("[GEMINI STAGE 5] _image_payload returned")
    logger.info(
        "Gemini image prepared after %.2fs; source_mime_type=%s; outgoing_mime_type=%s; payload_base64_chars=%s.",
        time.perf_counter() - image_preparation_started_at,
        source_mime_type,
        mime_type,
        len(encoded_image),
    )

    api_phase_started_at = time.perf_counter()
    try:
        logger.info("[GEMINI STAGE 6] creating genai client")
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        logger.info("[GEMINI STAGE 7] genai client created")
    except Exception as error:
        diagnostics = _error_diagnostics(error)
        _log_api_error(
            error,
            diagnostics,
            attempt=0,
            elapsed_seconds=time.perf_counter() - api_phase_started_at,
        )
        raise _service_error_for(diagnostics) from error

    interaction_input = [
        {
            "type": "image",
            "data": encoded_image,
            "mime_type": mime_type,
        },
        {"type": "text", "text": LABEL_READING_PROMPT},
    ]
    interaction_options = {
        "model": GEMINI_MODEL,
        "input": interaction_input,
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": PRODUCT_LABEL_SCHEMA,
        },
    }

    request_started_at = time.perf_counter()
    interaction = None
    for attempt in range(1, MAX_API_RETRIES + 2):
        logger.info(
            "Gemini API request started; model=%s; timeout_seconds=%s; "
            "attempt=%s/%s; source_mime_type=%s; outgoing_mime_type=%s.",
            GEMINI_MODEL,
            REQUEST_TIMEOUT_SECONDS,
            attempt,
            MAX_API_RETRIES + 1,
            source_mime_type,
            mime_type,
        )
        logger.info("[GEMINI STAGE 8] interactions.create starting")
        try:
            interaction = client.interactions.create(**interaction_options)
            break
        except Exception as error:
            diagnostics = _error_diagnostics(error)
            _log_api_error(
                error,
                diagnostics,
                attempt=attempt,
                elapsed_seconds=time.perf_counter() - request_started_at,
            )
            can_retry = (
                attempt <= MAX_API_RETRIES
                and _is_retryable_error(diagnostics, error)
            )
            if not can_retry:
                raise _service_error_for(diagnostics) from error

            retry_after = _retry_after_seconds(diagnostics["retry_after"])
            if retry_after is not None:
                if retry_after > MAX_RETRY_AFTER_SECONDS:
                    logger.warning(
                        "Gemini retry skipped; Retry-After %.2fs exceeds the %ss wait limit.",
                        retry_after,
                        MAX_RETRY_AFTER_SECONDS,
                    )
                    raise _service_error_for(diagnostics) from error
                retry_delay = retry_after
            else:
                retry_delay = float(attempt)

            logger.warning(
                "Retrying Gemini request after %.2fs; retry=%s/%s; status=%s; code=%s.",
                retry_delay,
                attempt,
                MAX_API_RETRIES,
                diagnostics["status_code"],
                _safe_log_value(diagnostics["code"]),
            )
            time.sleep(retry_delay)

    if interaction is None:
        # All attempts raise above; this guard keeps the return path explicit.
        raise GeminiServiceError(
            "Gemini tạm thời không khả dụng. Vui lòng thử lại sau."
        )
        
    logger.info("[GEMINI STAGE 9] interactions.create returned")

    _emit_diagnostic(
        diagnostic_callback,
        "response_envelope",
        response_type=type(interaction).__name__,
        output_text_type=type(getattr(interaction, "output_text", None)).__name__,
    )

    logger.info(
        "Gemini API response received after %.2fs.",
        time.perf_counter() - request_started_at,
    )
    logger.info("[GEMINI STAGE 10] reading output_text")
    response_text = getattr(interaction, "output_text", None)
    logger.info(
        "[GEMINI STAGE 11] output_text received length=%s",
        len(response_text) if isinstance(response_text, str) else 0,
    )
    logger.info("[GEMINI STAGE 12] normalizing Gemini response")
    try:
        label_data = _normalize_response(
            response_text,
            diagnostic_callback=diagnostic_callback,
        )
    except InvalidGeminiResponseError:
        logger.exception(
            "Gemini JSON parsing failed after API response; total_elapsed=%.2fs.",
            time.perf_counter() - analysis_started_at,
        )
        raise
    logger.info("[GEMINI STAGE 13] Gemini response normalized")
    logger.info(
        "[GEMINI] JSON parsed after %.2fs; product_name=%s; ingredients_count=%s; allergens_count=%s.",
        time.perf_counter() - analysis_started_at,
        label_data["product_name"],
        len(label_data["ingredients"]),
        len(label_data["allergens"]),
    )
    _emit_diagnostic(
        diagnostic_callback,
        "parsed_result",
        parsed_product_name=label_data["product_name"],
        parsed_ingredients=label_data["ingredients"],
        parsed_ingredients_count=len(label_data["ingredients"]),
        parsed_allergens=label_data["allergens"],
        parsed_allergens_count=len(label_data["allergens"]),
    )
    logger.info("[GEMINI STAGE 14] analyze_product_image completed")
    return label_data
