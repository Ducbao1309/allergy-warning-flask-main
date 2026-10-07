import inspect
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from services.gemini_service import analyze_product_image


def main():
    upload_directory = PROJECT_ROOT / "static" / "uploads"
    image_files = [
        path
        for path in upload_directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
    ] if upload_directory.is_dir() else []

    if not image_files:
        raise FileNotFoundError(
            f"No JPG/JPEG images found in {upload_directory}"
        )

    latest_image = max(image_files, key=lambda path: path.stat().st_mtime)
    function_code = getattr(analyze_product_image, "__code__", None)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print("=== GEMINI RUNTIME DEBUG ===")
    print(f"module={getattr(analyze_product_image, '__module__', None)}")
    print(f"function={getattr(analyze_product_image, '__name__', None)}")
    print(f"source_file={getattr(function_code, 'co_filename', None)}")
    print(f"inspect_source_file={inspect.getsourcefile(analyze_product_image)}")
    print(f"image_file={latest_image}")
    print("[GEMINI DIRECT] calling analyze_product_image", flush=True)

    try:
        result = analyze_product_image(latest_image)
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
