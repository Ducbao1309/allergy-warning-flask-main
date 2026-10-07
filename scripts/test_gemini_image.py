import base64
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPLOADS_DIR = PROJECT_ROOT / "static" / "uploads"
MODEL = "gemini-3.7-flash"
TIMEOUT_MS = 180_000
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def redact_secret(value, api_key):
    text = str(value)
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = re.sub(
        r"(?i)(x-goog-api-key\s*[:=]\s*)([^\s,;]+)",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)",
        r"\1[REDACTED]",
        text,
    )
    return text[:4000]


def latest_image():
    if not UPLOADS_DIR.is_dir():
        raise FileNotFoundError("static/uploads/ was not found.")

    images = [
        path
        for path in UPLOADS_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    if not images:
        raise FileNotFoundError("No supported image was found in static/uploads/.")

    return max(images, key=lambda path: path.stat().st_mtime)


def main():
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("GEMINI_API_KEY")

    print("=== GEMINI IMAGE TEST ===")
    print(f"model={MODEL}")

    image_path = None
    try:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is missing from .env.")

        image_path = latest_image()
        mime_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(image_path.suffix.lower())
        if not mime_type or not mime_type.startswith("image/"):
            raise ValueError("Could not determine the image MIME type.")

        print(f"image={image_path.relative_to(PROJECT_ROOT).as_posix()}")
        print(f"mime_type={mime_type}")
        image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")

        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=TIMEOUT_MS),
        )
        interaction = client.interactions.create(
            model=MODEL,
            input=[
                {
                    "type": "text",
                    "text": "Mô tả ngắn nội dung của ảnh này.",
                },
                {
                    "type": "image",
                    "data": image_data,
                    "mime_type": mime_type,
                },
            ],
        )
        print(f"result={interaction.output_text or ''}")
        return 0
    except Exception as error:
        response = getattr(error, "response", None)
        status_code = getattr(error, "status_code", None)
        if status_code is None and response is not None:
            status_code = getattr(response, "status_code", None)
        body = getattr(error, "body", None)
        if body is None and response is not None:
            body = getattr(response, "text", None)
        if body is None and response is not None:
            body = getattr(response, "content", None)

        print(f"exception type={type(error).__name__}")
        print(f"str(error)={redact_secret(error, api_key)}")
        if status_code is not None:
            print(f"status_code={redact_secret(status_code, api_key)}")
        if response is not None:
            print(f"response={redact_secret(type(response).__name__, api_key)}")
        if body is not None:
            print(f"body={redact_secret(body, api_key)}")
        if image_path is not None:
            print(f"image={image_path.relative_to(PROJECT_ROOT).as_posix()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
