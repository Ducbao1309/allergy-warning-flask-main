import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from google import genai
from google.genai import types

from services.gemini_service import (
    GEMINI_MODEL,
    REQUEST_TIMEOUT_SECONDS,
    _image_payload,
)


def _safe(value, api_key):
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    elif not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)

    if api_key:
        value = value.replace(api_key, "[REDACTED]")
    value = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(
        r"(?i)(x-goog-api-key|api[_-]?key|access[_-]?token)(\s*[:=]\s*[\"']?)([^\s\"'&,}]+)",
        r"\1\2[REDACTED]",
        value,
    )
    return value[:4000]


def _diagnostics(error, api_key):
    response = getattr(error, "response", None)
    status = getattr(error, "status_code", None) or getattr(response, "status_code", None)
    body = getattr(error, "body", None)
    if body is None:
        body = getattr(response, "text", None)
    if body is None:
        body = getattr(response, "content", None)
    headers = getattr(error, "headers", None) or getattr(response, "headers", None)

    if isinstance(body, bytes):
        body_text = body.decode("utf-8", errors="replace")
    elif isinstance(body, str):
        body_text = body
    else:
        body_text = json.dumps(body, ensure_ascii=False, default=str) if body is not None else ""

    try:
        payload = json.loads(body_text) if body_text else {}
    except json.JSONDecodeError:
        payload = {}
    error_payload = payload.get("error", payload) if isinstance(payload, dict) else {}
    if not isinstance(error_payload, dict):
        error_payload = {}

    retry_after = None
    safe_headers = {}
    if headers is not None:
        try:
            for name, value in headers.items():
                name_text = str(name)
                normalized = name_text.strip().lower().replace("_", "-")
                if normalized == "retry-after":
                    retry_after = value
                if any(secret in normalized for secret in (
                    "authorization", "api-key", "access-token", "cookie"
                )):
                    continue
                safe_headers[name_text] = _safe(value, api_key)
        except Exception:
            safe_headers = {}
    retry_after = retry_after or getattr(error, "retry_after", None)

    error_code = (
        error_payload.get("code")
        or error_payload.get("status")
        or getattr(error, "error_code", None)
        or getattr(error, "code", None)
    )
    if status is None and isinstance(error_code, int):
        status = error_code
    message = error_payload.get("message") or getattr(error, "message", None) or str(error)

    return {
        "status": _safe(status, api_key),
        "code": _safe(error_code, api_key),
        "message": _safe(message, api_key),
        "retry_after": _safe(retry_after, api_key),
        "headers": safe_headers,
        "body": _safe(body_text, api_key) if body_text else None,
    }


def _run_request(label, client, request_kwargs, api_key):
    print(f"[{label}] model={GEMINI_MODEL}")
    print(f"[{label}] API request starting", flush=True)
    try:
        response = client.interactions.create(**request_kwargs)
    except Exception as error:
        details = _diagnostics(error, api_key)
        print(f"[{label}] FAIL exception_type={type(error).__name__}")
        print(
            f"[{label}] status={details['status']} code={details['code']} "
            f"message={details['message']} retry_after={details['retry_after']}"
        )
        if details["headers"]:
            print(f"[{label}] headers={json.dumps(details['headers'], ensure_ascii=False)}")
        if details["body"]:
            print(f"[{label}] body={details['body']}")
        return False

    output_text = getattr(response, "output_text", None)
    status = getattr(response, "status_code", None)
    print(
        f"[{label}] PASS status={status if status is not None else 'success (not exposed by SDK)'} "
        "output_text_length="
        f"{len(output_text) if isinstance(output_text, str) else 0}"
    )
    return True


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not configured in the environment or .env.")
        return 2

    uploads = PROJECT_ROOT / "static" / "uploads"
    jpg_files = [
        path
        for path in uploads.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
    ] if uploads.is_dir() else []
    if not jpg_files:
        print(f"No JPG/JPEG image found in {uploads}.")
        return 2
    image_path = max(jpg_files, key=lambda path: path.stat().st_mtime)

    print(f"model={GEMINI_MODEL}")
    print(f"image={image_path}")
    print("GEMINI_API_KEY=present (value hidden)")

    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
    except Exception as error:
        details = _diagnostics(error, api_key)
        print(f"CLIENT FAIL exception_type={type(error).__name__}")
        print(
            f"CLIENT status={details['status']} code={details['code']} "
            f"message={details['message']} retry_after={details['retry_after']}"
        )
        return 1

    text_ok = _run_request(
        "TEXT",
        client,
        {
            "model": GEMINI_MODEL,
            "input": [{"type": "text", "text": "Reply with only: OK"}],
        },
        api_key,
    )
    if not text_ok:
        print("IMAGE=SKIPPED because the minimal text request failed.")
        return 1

    try:
        encoded_image, outgoing_mime, _source_mime = _image_payload(image_path)
    except Exception as error:
        print(f"IMAGE PREPARATION FAIL exception_type={type(error).__name__}")
        print(f"IMAGE PREPARATION message={_safe(str(error), api_key)}")
        return 1

    image_ok = _run_request(
        "IMAGE",
        client,
        {
            "model": GEMINI_MODEL,
            "input": [
                {"type": "image", "data": encoded_image, "mime_type": outgoing_mime},
                {"type": "text", "text": "Describe this food label briefly."},
            ],
        },
        api_key,
    )
    return 0 if image_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
