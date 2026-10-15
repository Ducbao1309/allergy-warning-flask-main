import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from services.gemini_service import (
    GEMINI_MODEL,
    LABEL_READING_PROMPT,
    analyze_product_image,
)


def main():
    parser = argparse.ArgumentParser(
        description="Run the current Gemini label pipeline against one explicit image."
    )
    parser.add_argument("image_path", type=Path, help="Path to the exact scan image to trace")
    args = parser.parse_args()
    image_path = args.image_path.expanduser().resolve(strict=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    function_code = getattr(analyze_product_image, "__code__", None)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print("=== GEMINI RUNTIME DEBUG ===")
    print(f"module={getattr(analyze_product_image, '__module__', None)}")
    print(f"function={getattr(analyze_product_image, '__name__', None)}")
    print(f"source_file={getattr(function_code, 'co_filename', None)}")
    print(f"image_file={image_path}")
    print(f"model={GEMINI_MODEL}")
    print("=== ACTUAL PROMPT ===")
    print(LABEL_READING_PROMPT)
    print("[GEMINI DIRECT] calling analyze_product_image", flush=True)

    def print_diagnostic(stage, details):
        print(
            f"[GEMINI DEBUG] {stage}="
            f"{json.dumps(details, ensure_ascii=False, default=str)}",
            flush=True,
        )

    try:
        result = analyze_product_image(
            image_path,
            diagnostic_callback=print_diagnostic,
        )
    except Exception as error:
        print(
            f"[GEMINI DIRECT] exception_type={type(error).__name__} "
            f"error={error}"
        )
        return 1

    print("[GEMINI DIRECT] result=")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
