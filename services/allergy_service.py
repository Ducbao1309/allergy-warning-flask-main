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

    # SỮA
    "Sữa": [
        "milk",
        "milch",
        "milk powder",
        "milkpowder",
        "milchpulver",
        "magermilchpulver",
        "whey",
        "molke",
        "casein",
        "lactose",
        "butter",
        "cream",
        "cheese"
    ],


    # ĐẬU PHỘNG
    "Đậu phộng": [
        "peanut",
        "peanuts",
        "groundnut",
        "erdnuss",
        "erdnusse"
    ],


    # ĐẬU NÀNH
    "Đậu nành": [
        "soy",
        "soya",
        "soybean",
        "soybeans",
        "soja"
    ],


    # TRỨNG
    "Trứng": [
        "egg",
        "eggs",
        "ei",
        "albumin",
        "albumen"
    ],


    # LÚA MÌ
    "Lúa mì": [
        "wheat",
        "weizen",
        "weizenmehl",
        "flour",
        "gluten"
    ],


    # CÁ
    "Cá": [
        "fish",
        "fisch",
        "salmon",
        "tuna",
        "cod"
    ],


    # GIÁP XÁC / HẢI SẢN
    "Tôm": [
        "shrimp",
        "prawn",
        "crab",
        "shellfish",
        "crustaceans"
    ],


    # CÁC LOẠI HẠT
    "Các loại hạt": [
        "almond",
        "almonds",
        "cashew",
        "walnut",
        "hazelnut",
        "hazelnuts",
        "haselnuss",
        "haselnusse",
        "pistachio",
        "pistachios"
    ],


    # MÙ TẠT
    "Mù tạt": [
        "mustard",
        "senf"
    ],


    # ĐẬU LUPIN
    "Đậu lupin": [
        "lupin",
        "lupine",
        "lupinen"
    ],


    # MÈ / VỪNG
    "Mè": [
        "sesame",
        "sesam"
    ]
}


# ========================================
# KIỂM TRA DỊ NGUYÊN
# ========================================

def check_allergens(text):

    if not text:
        return []


    text_normalized = normalize_text(text)

    results = []


    for allergen, keywords in ALLERGEN_KEYWORDS.items():

        matched_keywords = []


        for keyword in keywords:

            keyword_normalized = normalize_text(
                keyword
            )


            if not keyword_normalized:
                continue


            # ----------------------------
            # Từ khóa có khoảng trắng
            # ----------------------------

            if " " in keyword_normalized:

                if keyword_normalized in text_normalized:

                    matched_keywords.append(
                        keyword
                    )

                continue


            # ----------------------------
            # Từ khóa một từ
            # ----------------------------

            pattern = (
                r"(?<![a-z])"
                + re.escape(keyword_normalized)
                + r"(?![a-z])"
            )


            if re.search(
                pattern,
                text_normalized
            ):

                matched_keywords.append(
                    keyword
                )


            # Một số trường hợp OCR dính chữ
            elif keyword_normalized in text_normalized:

                matched_keywords.append(
                    keyword
                )


        # ----------------------------
        # Nếu phát hiện dị nguyên
        # ----------------------------

        if matched_keywords:

            matched_keywords = list(
                dict.fromkeys(
                    matched_keywords
                )
            )


            results.append({

                "allergen": allergen,

                "keywords": matched_keywords,

                "warning": (
                    f"Phát hiện thành phần "
                    f"liên quan đến {allergen}."
                )

            })


    return results