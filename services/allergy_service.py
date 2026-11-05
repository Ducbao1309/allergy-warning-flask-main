import re
import unicodedata


# ========================================
# CHUẨN HÓA TEXT
# ========================================

def normalize_text(text):
    if not text:
        return ""

    text = str(text).lower()

    text = unicodedata.normalize(
        "NFKD",
        text
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    return text


# ========================================
# DANH SÁCH DỊ NGUYÊN
# ========================================

ALLERGEN_KEYWORDS = {
    # SỮA VÀ SẢN PHẨM TỪ SỮA
    "Sữa": [
        "milk", "milk powder", "milkpowder", "skimmed milk powder",
        "whole milk powder", "milch", "milchpulver", "magermilchpulver",
        "whey", "whey powder", "molke", "casein", "caseinate",
        "lactose", "butter", "cream", "cheese",
        "sua", "sua bo", "sua tuoi", "sua bot", "bot sua",
        "bot whey", "dam whey", "casein sua", "kem sua", "pho mai",
    ],

    # ĐẬU PHỘNG
    "Đậu phộng": [
        "peanut", "peanuts", "groundnut", "ground nuts",
        "erdnuss", "erdnusse", "dau phong", "lac",
    ],

    # ĐẬU NÀNH
    "Đậu nành": [
        "soy", "soya", "soybean", "soybeans", "soja",
        "dau nanh", "dau tuong", "tuong nanh", "dau nanh lecithin",
    ],

    # TRỨNG
    "Trứng": [
        "egg", "eggs", "egg white", "egg yolk", "albumin", "albumen",
        "ei", "trung", "long trang trung", "long do trung", "bot trung",
    ],

    # LÚA MÌ / GLUTEN
    "Lúa mì": [
        "wheat", "wheat flour", "whole wheat", "weizen", "weizenmehl",
        "gluten", "bot mi", "lua mi", "bot lua mi", "lu mi",
    ],

    # CÁ
    "Cá": [
        "fish", "fish sauce", "fisch", "salmon", "tuna", "cod",
        "nuoc mam", "mam ca", "fish sauce",
    ],

    # GIÁP XÁC / HẢI SẢN
    "Tôm": [
        "shrimp", "prawn", "crab", "shellfish", "crustaceans",
        "tom", "cua", "ghe", "giap xac",
    ],

    # CÁC LOẠI HẠT CÂY
    "Các loại hạt": [
        "almond", "almonds", "cashew", "cashews", "walnut", "walnuts",
        "hazelnut", "hazelnuts", "haselnuss", "haselnusse",
        "pistachio", "pistachios", "macadamia", "pecan",
        "hanh nhan", "hat dieu", "oc cho", "hat phuong",
    ],

    # MÙ TẠT
    "Mù tạt": ["mustard", "senf", "mu tat"],

    # ĐẬU LUPIN
    "Đậu lupin": ["lupin", "lupine", "lupinen", "dau lupin"],

    # MÈ / VỪNG
    "Mè": ["sesame", "sesam", "vung", "hat me", "dau me"],
}


# ========================================
# KIỂM TRA DỊ NGUYÊN
# ========================================

def check_allergens(text):
    """
    Nhận diện dị nguyên từ văn bản thành phần (tiếng Việt/Anh/Đức).

    Lưu ý: đây là nhận diện theo từ khóa để hỗ trợ cảnh báo, không thay thế
    nhãn dị ứng chính thức hoặc xác nhận an toàn của nhà sản xuất.
    """
    if not text:
        return []

    text_normalized = normalize_text(text)
    results = []

    for allergen, keywords in ALLERGEN_KEYWORDS.items():
        matched_keywords = []

        for keyword in keywords:
            keyword_normalized = normalize_text(keyword).strip()
            if not keyword_normalized:
                continue

            # Từ/cụm từ phải khớp theo ranh giới từ để tránh match nhầm
            # các chuỗi con nằm bên trong từ khác.
            pattern = (
                r"(?<![a-z0-9])"
                + re.escape(keyword_normalized)
                + r"(?![a-z0-9])"
            )
            if re.search(pattern, text_normalized):
                matched_keywords.append(keyword)

        if matched_keywords:
            matched_keywords = list(dict.fromkeys(matched_keywords))
            results.append({
                "allergen": allergen,
                "keywords": matched_keywords,
                "warning": f"Phát hiện thành phần có từ khóa liên quan đến {allergen}.",
                "source": "ingredient_text_keyword_match",
                "confidence": "needs_review",
            })

    return results

