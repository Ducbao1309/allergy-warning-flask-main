import json
import re
import unicodedata
from difflib import SequenceMatcher

from extensions import db
from models import Allergen, Product, ProductIngredient


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

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


def find_product_by_identity(name, brand=None, barcode=None):
    """Find a confidently identified product without fuzzy name matching."""
    products = Product.query.all()
    if barcode and re.fullmatch(r"\d{8,14}", str(barcode).strip()):
        barcode_match = next(
            (item for item in products if item.barcode == str(barcode).strip()),
            None,
        )
        if barcode_match:
            return barcode_match

    normalized_name = normalize_text(name)
    normalized_brand = normalize_text(brand)
    if not normalized_name or not normalized_brand:
        return None

    return next(
        (
            item for item in products
            if normalize_text(item.name) == normalized_name
            and normalize_text(item.brand) == normalized_brand
        ),
        None,
    )


def _known_allergen_tag(value, allergens):
    """Return a tag only for an exact match in the existing allergens table."""
    normalized = normalize_text(value)
    if not normalized:
        return None
    for allergen in allergens:
        if normalized in {
            normalize_text(allergen.name),
            normalize_text(allergen.name_en),
            normalize_text(allergen.off_tag),
        }:
            return allergen.off_tag
    return None


def save_scanned_product(label_data, image_url, barcode=None):
    """Insert one user-approved Gemini scan and its ingredient rows."""
    product_name = (label_data.get("product_name") or "").strip()
    brand = (label_data.get("brand") or "").strip() or None
    ingredients = list(dict.fromkeys(
        item.strip() for item in label_data.get("ingredients", [])
        if isinstance(item, str) and item.strip()
    ))
    declared_allergens = list(dict.fromkeys(
        item.strip() for item in label_data.get("allergens", [])
        if isinstance(item, str) and item.strip()
    ))
    if not product_name:
        raise ValueError("Product name is required to save a scan.")

    existing = find_product_by_identity(product_name, brand, barcode)
    if existing:
        return existing, False

    known_allergens = Allergen.query.all()
    mapped_product_tags = list(dict.fromkeys(
        tag for tag in (
            _known_allergen_tag(item, known_allergens)
            for item in declared_allergens
        ) if tag
    ))
    valid_barcode = (
        str(barcode).strip()
        if barcode and re.fullmatch(r"\d{8,14}", str(barcode).strip())
        else None
    )
    product = Product(
        barcode=valid_barcode,
        name=product_name,
        brand=brand,
        ingredients_text=", ".join(ingredients),
        allergens_text=", ".join(declared_allergens),
        allergens_tags=json.dumps(mapped_product_tags, ensure_ascii=False),
        image_url=image_url,
        source_url=None,
    )
    try:
        db.session.add(product)
        db.session.flush()
        for ingredient in ingredients:
            db.session.add(ProductIngredient(
                product_id=product.id,
                name=ingredient,
                name_en=None,
                off_tag=_known_allergen_tag(ingredient, known_allergens),
            ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return product, True


# ========================================
# TÌM SẢN PHẨM TỪ NỘI DUNG OCR
# ========================================

def find_product_from_ocr(ocr_text):

    if not ocr_text:
        return None

    ocr_normalized = normalize_text(
        ocr_text
    )

    products = Product.query.all()

    best_product = None
    best_score = 0


    for product in products:

        if not product.name:
            continue

        product_name = normalize_text(
            product.name
        )

        if not product_name:
            continue


        # ====================================
        # CÁCH 1:
        # TÊN SẢN PHẨM NẰM TRONG OCR
        # ====================================

        if product_name in ocr_normalized:

            return product


        # ====================================
        # CÁCH 2:
        # SO SÁNH TỪ
        # ====================================

        product_words = set(
            product_name.split()
        )

        ocr_words = set(
            ocr_normalized.split()
        )

        common_words = (
            product_words
            & ocr_words
        )


        if product_words:

            word_score = (
                len(common_words)
                / len(product_words)
            )

        else:

            word_score = 0


        # ====================================
        # CÁCH 3:
        # SO SÁNH CHUỖI GẦN GIỐNG
        # ====================================

        similarity = SequenceMatcher(
            None,
            product_name,
            ocr_normalized
        ).ratio()


        score = max(
            word_score,
            similarity
        )


        if score > best_score:

            best_score = score
            best_product = product


    # ====================================
    # CHỈ NHẬN KẾT QUẢ ĐỦ GIỐNG
    # ====================================

    if best_score >= 0.45:

        return best_product


    return None


# ========================================
# LẤY DANH SÁCH THÀNH PHẦN SẢN PHẨM
# ========================================

def get_product_ingredients(product):

    if not product:
        return []


    if not product.ingredients_text:
        return []


    # Tách theo dấu phẩy nhưng KHÔNG tách
    # số thập phân:
    #
    # 7,4%  -> giữ nguyên
    # 6,6%  -> giữ nguyên

    ingredients = re.split(
        r",\s*(?!\d)",
        product.ingredients_text
    )


    return [
        item.strip()
        for item in ingredients
        if item.strip()
    ]


# ========================================
# LẤY DỊ NGUYÊN CỦA SẢN PHẨM
# ========================================

def get_product_allergens(product):

    if not product:
        return []


    if not product.allergens_tags:
        return []


    try:

        allergens = json.loads(
            product.allergens_tags
        )


        if isinstance(
            allergens,
            list
        ):

            return allergens


    except (
        json.JSONDecodeError,
        TypeError
    ):

        pass


    return []


# ========================================
# TỪ KHÓA DỊ NGUYÊN
# ========================================

ALLERGEN_DEFINITIONS = {
    "en:milk": ("Sữa", ["milk", "milch", "lait", "milk powder", "milkpowder", "milchpulver", "magermilchpulver", "whey", "molke", "lactoserum", "casein", "lactose", "butter", "cream", "cheese"]),
    "en:soybeans": ("Đậu nành", ["soy", "soya", "soybean", "soybeans", "soja"]),
    "en:peanuts": ("Đậu phộng", ["peanut", "peanuts", "groundnut", "erdnuss", "erdnusse"]),
    "en:eggs": ("Trứng", ["egg", "eggs", "albumin", "albumen"]),
    "en:wheat": ("Lúa mì", ["wheat", "weizen", "weizenmehl", "flour", "gluten"]),
    "en:fish": ("Cá", ["fish", "fisch", "salmon", "tuna", "cod"]),
    "en:crustaceans": ("Giáp xác", ["shrimp", "prawn", "crab", "shellfish", "crustaceans"]),
    "en:tree-nuts": ("Các loại hạt", ["almond", "almonds", "cashew", "walnut", "hazelnut", "hazelnuts", "haselnuss", "haselnusse", "pistachio", "pistachios", "noisette", "noisettes"]),
    "en:mustard": ("Mù tạt", ["mustard", "senf"]),
    "en:lupin": ("Đậu lupin", ["lupin", "lupine", "lupinen"]),
    "en:sesame": ("Mè / vừng", ["sesame", "sesam"]),
    "en:molluscs": ("Động vật thân mềm", ["mollusc", "mollusk", "squid", "octopus", "mussel", "oyster", "clam"]),
    "en:celery": ("Cần tây", ["celery", "sellerie"]),
    "en:sulphites": ("Sulfite", ["sulphite", "sulfite", "sulphur dioxide"]),
}

ALLERGEN_TAG_ALIASES = {
    "en:nuts": "en:tree-nuts",
    "en:tree_nuts": "en:tree-nuts",
    "en:sulfites": "en:sulphites",
}


def normalize_allergen_tag(tag):
    if not tag:
        return None
    normalized = str(tag).strip().lower()
    if not normalized:
        return None
    if ":" not in normalized:
        normalized = f"en:{normalized}"
    return ALLERGEN_TAG_ALIASES.get(normalized, normalized)


def has_unsupported_allergen_tags(tags):
    return any(
        normalize_allergen_tag(tag) not in ALLERGEN_DEFINITIONS
        for tag in (tags or set())
    )


def check_product_ingredients(product_ingredients, user_allergen_tags, product_allergen_tags=None):
    """Match selected allergen tags against declared tags and ingredient text."""
    selected_tags = {normalize_allergen_tag(tag) for tag in (user_allergen_tags or set())}
    selected_tags.discard(None)
    product_tags = {normalize_allergen_tag(tag) for tag in (product_allergen_tags or [])}
    product_tags.discard(None)

    grouped_results = {}
    for tag in selected_tags:
        definition = ALLERGEN_DEFINITIONS.get(tag)
        if definition and tag in product_tags:
            grouped_results[tag] = {"label": definition[0], "ingredients": []}

    for ingredient in product_ingredients or []:
        ingredient_normalized = normalize_text(ingredient)
        for tag in selected_tags:
            definition = ALLERGEN_DEFINITIONS.get(tag)
            if not definition:
                continue
            label, keywords = definition
            if any(normalize_text(keyword) in ingredient_normalized for keyword in keywords):
                match = grouped_results.setdefault(tag, {"label": label, "ingredients": []})
                if ingredient not in match["ingredients"]:
                    match["ingredients"].append(ingredient)

    results = []
    for match in grouped_results.values():
        ingredients = match["ingredients"]
        label = match["label"]
        results.append({
            "allergen": label,
            "ingredients": ingredients,
            "ingredient": ingredients[0] if ingredients else None,
            "warning": f"Có khai báo hoặc phát hiện thành phần liên quan đến {label}.",
        })
    return results
