import os

# pyrefly: ignore [missing-import]
import pytesseract

# pyrefly: ignore [missing-import]
from PIL import Image

_configured_tesseract_cmd = os.environ.get("TESSERACT_CMD")
if _configured_tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = _configured_tesseract_cmd


def get_ocr_lang():
    """
    Dùng thêm tiếng Việt nếu máy đã cài
    bộ ngôn ngữ 'vie' cho Tesseract,
    chưa cài thì dùng tiếng Anh.
    """

    try:
        langs = pytesseract.get_languages(
            config=""
        )

    except Exception:
        return "eng"

    if "vie" in langs:
        return "eng+vie"

    return "eng"


def extract_text(image_path):

    print()
    print("================================")
    print("BẮT ĐẦU OCR")
    print("File:", image_path)
    print("================================")

    try:

        # Kiểm tra Tesseract
        print("Tesseract version:")
        print(pytesseract.get_tesseract_version())

        print()
        print("Ngôn ngữ Tesseract:")
        print(pytesseract.get_languages(config=""))

        # Mở ảnh
        image = Image.open(image_path)

        print()
        print("Kích thước ảnh:", image.size)

        # Ngôn ngữ OCR
        ocr_lang = get_ocr_lang()

        print()
        print("Ngôn ngữ OCR:", ocr_lang)

        # OCR
        text = pytesseract.image_to_string(
            image,
            lang=ocr_lang,
            config="--psm 6"
        )

        print()
        print("================================")
        print("KẾT QUẢ OCR")
        print("================================")
        print(text)
        print("================================")

        return text.strip()

    except Exception as e:

        print()
        print("================================")
        print("❌ OCR ERROR")
        print("================================")
        print(type(e).__name__)
        print(e)
        print("================================")

        return ""
