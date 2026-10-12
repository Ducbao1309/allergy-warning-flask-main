import json
import re
import unicodedata
from difflib import SequenceMatcher

from extensions import db
from models import Allergen, Product, ProductIngredient


# =========================================================
# CHUẨN HÓA TEXT
# =========================================================

def normalize_text(text):
    """
    Chuẩn hóa text để dễ so sánh.

    Quy tắc:
    - Chuyển chữ thường
    - Bỏ dấu
    - Xóa phần trăm
    - Chuẩn hóa dấu gạch nối
    - Xóa ký tự đặc biệt
    - Gộp khoảng trắng
    """

    if not text:
        return ""

    text = str(text)

    # 1. Chuyển về chữ thường
    text = text.lower()

    # 2. Chuẩn hóa Unicode và bỏ dấu
    text = unicodedata.normalize("NFKD", text)

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    # 3. Xóa phần trăm
    #
    # Ví dụ:
    # milk (8,7%) -> milk
    # milk 8.7 % -> milk
    #
    text = re.sub(
        r"\(?\s*\d+(?:[.,]\d+)?\s*%\s*\)?",
        " ",
        text
    )

    # 4. Chuẩn hóa dấu gạch nối
    #
    # Sau bước nối line-break, dấu - còn lại
    # được xem như khoảng trắng để:
    #
    # MALZEXTRAKT-PULVER
    # ->
    # malzextrakt pulver
    #
    text = text.replace("-", " ")

    # 5. Xóa một số ký tự đặc biệt
    text = re.sub(
        r"[\(\)\[\]\{\},;:]+",
        " ",
        text
    )

    # 6. Gộp nhiều khoảng trắng
    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


# =========================================================
# CHUẨN HÓA + LOẠI TRÙNG THÀNH PHẦN
# =========================================================

# =========================================================
# CHUẨN HÓA + LOẠI TRÙNG THÀNH PHẦN
# =========================================================

def normalize_and_deduplicate_ingredients(ingredients):
    """
    Chuẩn hóa và loại bỏ thành phần trùng nhau.

    Quy tắc dùng để tạo khóa so sánh:

    1. Nối từ bị ngắt dòng bằng dấu '-'
    2. Bỏ phần phần trăm: (8,7%), 1.5%,...
    3. Chuyển chữ thường
    4. Bỏ dấu tiếng Đức/tiếng Việt
    5. Bỏ dấu gạch nối
    6. Bỏ toàn bộ khoảng trắng khi tạo khóa
    7. Gộp các thành phần có cùng khóa
    8. Giữ lại dạng xuất hiện đầu tiên để hiển thị

    Ví dụ:

        WEIZENMEHL
        WEIZEN MEHL

    -> cùng khóa:

        weizenmehl

    Ví dụ:

        GERSTEN MALZEXTRAKTPULVER
        GERSTEN MALZEXTRAKT-PULVER

    -> cùng khóa:

        gerstenmalzextraktpulver
    """

    if not ingredients:
        return []

    # =====================================================
    # BƯỚC 1 - SỬA TỪ BỊ NGẮT DÒNG
    # =====================================================

    repaired = []
    pending = None

    for item in ingredients:

        if not isinstance(item, str):
            continue

        current = item.strip()

        if not current:
            continue

        # Nếu phần trước bị ngắt bằng dấu "-"
        if pending is not None:
            current = pending + current.lstrip()
            pending = None

        # Ví dụ:
        #
        # GERSTEN MALZEXTRAKT-
        # PULVER
        #
        # -> GERSTEN MALZEXTRAKT-PULVER

        if current.rstrip().endswith("-"):
            pending = current.rstrip()[:-1] + "-"
            continue

        repaired.append(current)

    # Nếu còn phần cuối đang chờ
    if pending:
        repaired.append(
            pending.rstrip("-")
        )

    # =====================================================
    # BƯỚC 2 - NORMALIZE + DEDUP
    # =====================================================

    result = []
    seen = set()

    for ingredient in repaired:

        original = ingredient.strip()

        if not original:
            continue

        # Normalize cơ bản:
        #
        # WEIZEN MEHL
        # ->
        # weizen mehl
        #
        # GERSTEN MALZEXTRAKT-PULVER
        # ->
        # gersten malzextrakt pulver

        normalized = normalize_text(original)

        if not normalized:
            continue

        # =================================================
        # TẠO KHÓA SO SÁNH
        # =================================================
        #
        # Bỏ toàn bộ khoảng trắng để:
        #
        # WEIZENMEHL
        # WEIZEN MEHL
        #
        # trở thành cùng một khóa.
        #
        # Đồng thời:
        #
        # GERSTEN MALZEXTRAKTPULVER
        # GERSTEN MALZEXTRAKT-PULVER
        #
        # cũng thành cùng một khóa.
        # =================================================

        comparison_key = re.sub(
            r"\s+",
            "",
            normalized
        )

        if not comparison_key:
            continue

        # Nếu đã gặp rồi -> bỏ
        if comparison_key in seen:
            continue

        seen.add(comparison_key)

        # Giữ nguyên phiên bản đầu tiên để hiển thị
        result.append(original)

    return result


# =========================================================
# PHÂN BIỆT "CÓ CHỨA" VÀ "CÓ THỂ CHỨA"
# =========================================================

MAY_CONTAIN_PATTERNS = [
    "may contain",
    "may contain traces of",
    "may contain trace of",
    "traces of",
    "trace of",

    "có thể chứa",
    "có thể chứa vết",
    "có thể chứa dấu vết",

    "co the chua",
    "co the chua vet",
    "co the chua dau vet",

    "kann enthalten",
    "kann spuren von",
    "kann spuren enthalten",

    "kann spuren von milch enthalten",
    "kann spuren von soja enthalten",
    "kann spuren von erdnussen enthalten",
    "kann spuren von nüssen enthalten",
    "kann spuren von nussen enthalten",
]


def detect_ingredient_context(text):
    """
    Xác định ngữ cảnh:

    contains
        = sản phẩm có chứa trực tiếp

    may_contain
        = sản phẩm có thể chứa vết
    """

    normalized = normalize_text(text)

    if not normalized:
        return "contains"

    for pattern in MAY_CONTAIN_PATTERNS:

        pattern_normalized = normalize_text(pattern)

        if not pattern_normalized:
            continue

        if pattern_normalized in normalized:
            return "may_contain"

    return "contains"


# =========================================================
# TÌM SẢN PHẨM
# =========================================================

def find_product_by_identity(name, brand=None, barcode=None):
    """
    Tìm sản phẩm dựa trên barcode hoặc
    tên + brand.

    Không fuzzy match tên ở đây để tránh
    nhận nhầm sản phẩm.
    """

    products = Product.query.all()

    # =====================================================
    # ƯU TIÊN BARCODE
    # =====================================================

    if barcode and re.fullmatch(
        r"\d{8,14}",
        str(barcode).strip()
    ):

        barcode_value = str(barcode).strip()

        barcode_match = next(
            (
                item
                for item in products
                if item.barcode == barcode_value
            ),
            None
        )

        if barcode_match:
            return barcode_match

    # =====================================================
    # TÊN + BRAND
    # =====================================================

    normalized_name = normalize_text(name)
    normalized_brand = normalize_text(brand)

    if not normalized_name or not normalized_brand:
        return None

    return next(
        (
            item
            for item in products
            if normalize_text(item.name) == normalized_name
            and normalize_text(item.brand) == normalized_brand
        ),
        None
    )


# =========================================================
# TÌM TAG DỊ NGUYÊN ĐÃ BIẾT TRONG DATABASE
# =========================================================

def _known_allergen_tag(value, allergens):
    """
    Trả về off_tag khi value khớp chính xác
    với name / name_en / off_tag trong bảng Allergen.
    """

    normalized = normalize_text(value)

    if not normalized:
        return None

    for allergen in allergens:

        possible_values = {
            normalize_text(allergen.name),
            normalize_text(allergen.name_en),
            normalize_text(allergen.off_tag),
        }

        possible_values.discard("")

        if normalized in possible_values:
            return allergen.off_tag

    return None


# =========================================================
# LƯU SẢN PHẨM ĐÃ QUÉT
# =========================================================

def save_scanned_product(label_data, image_url, barcode=None):
    """
    Insert một sản phẩm được Gemini nhận diện
    và các thành phần của sản phẩm.

    Ingredients được normalize + deduplicate
    trước khi lưu.
    """

    product_name = (
        label_data.get("product_name") or ""
    ).strip()

    brand = (
        label_data.get("brand") or ""
    ).strip() or None

    # =====================================================
    # NORMALIZE + DEDUP NGAY TRƯỚC KHI LƯU
    # =====================================================

    ingredients = normalize_and_deduplicate_ingredients(
        label_data.get("ingredients", [])
    )

    # =====================================================
    # DỊ NGUYÊN ACTUAL
    # =====================================================

    declared_allergens = []

    seen_allergens = set()

    for item in label_data.get("allergens", []):

        if not isinstance(item, str):
            continue

        value = item.strip()

        if not value:
            continue

        normalized = normalize_text(value)

        if normalized in seen_allergens:
            continue

        seen_allergens.add(normalized)

        declared_allergens.append(value)

    # =====================================================
    # DỊ NGUYÊN MAY CONTAIN
    #
    # Hiện model Product chưa có cột riêng cho phần này,
    # nên chỉ chuẩn hóa để dùng trong scan.
    # =====================================================

    may_contain_allergens = []

    seen_may_contain = set()

    for item in label_data.get(
        "may_contain_allergens",
        []
    ):

        if not isinstance(item, str):
            continue

        value = item.strip()

        if not value:
            continue

        normalized = normalize_text(value)

        if normalized in seen_may_contain:
            continue

        seen_may_contain.add(normalized)

        may_contain_allergens.append(value)

    if not product_name:
        raise ValueError(
            "Product name is required to save a scan."
        )

    # =====================================================
    # TÌM SẢN PHẨM ĐÃ CÓ
    # =====================================================

    existing = find_product_by_identity(
        product_name,
        brand,
        barcode
    )

    if existing:
        return existing, False

    # =====================================================
    # LẤY DANH SÁCH DỊ NGUYÊN TRONG DATABASE
    # =====================================================

    known_allergens = Allergen.query.all()

    mapped_product_tags = list(
        dict.fromkeys(
            tag
            for tag in (
                _known_allergen_tag(
                    item,
                    known_allergens
                )
                for item in declared_allergens
            )
            if tag
        )
    )

    # =====================================================
    # BARCODE HỢP LỆ
    # =====================================================

    valid_barcode = (
        str(barcode).strip()
        if barcode
        and re.fullmatch(
            r"\d{8,14}",
            str(barcode).strip()
        )
        else None
    )

    # =====================================================
    # TẠO PRODUCT
    # =====================================================

    product = Product(
        barcode=valid_barcode,
        name=product_name,
        brand=brand,
        ingredients_text=", ".join(
            ingredients
        ),
        allergens_text=", ".join(
            declared_allergens
        ),
        allergens_tags=json.dumps(
            mapped_product_tags,
            ensure_ascii=False
        ),
        image_url=image_url,
        source_url=None,
    )

    try:

        db.session.add(product)

        db.session.flush()

        # =================================================
        # LƯU TỪNG INGREDIENT
        # =================================================

        for ingredient in ingredients:

            db.session.add(
                ProductIngredient(
                    product_id=product.id,
                    name=ingredient,
                    name_en=None,
                    off_tag=_known_allergen_tag(
                        ingredient,
                        known_allergens
                    ),
                )
            )

        db.session.commit()

    except Exception:

        db.session.rollback()

        raise

    return product, True


# =========================================================
# TÌM SẢN PHẨM TỪ NỘI DUNG OCR
# =========================================================

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

        # =================================================
        # CÁCH 1:
        # TÊN SẢN PHẨM NẰM TRONG OCR
        # =================================================

        if product_name in ocr_normalized:
            return product

        # =================================================
        # CÁCH 2:
        # SO SÁNH TỪ
        # =================================================

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

        # =================================================
        # CÁCH 3:
        # SO SÁNH CHUỖI GẦN GIỐNG
        # =================================================

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

    # =====================================================
    # CHỈ NHẬN KẾT QUẢ ĐỦ GIỐNG
    # =====================================================

    if best_score >= 0.45:
        return best_product

    return None


# =========================================================
# LẤY DANH SÁCH THÀNH PHẦN SẢN PHẨM
# =========================================================

def get_product_ingredients(product):

    if not product:
        return []

    if not product.ingredients_text:
        return []

    # Tách theo dấu phẩy nhưng không tách số thập phân
    #
    # 7,4% -> giữ nguyên
    # 6,6% -> giữ nguyên

    ingredients = re.split(
        r",\s*(?!\d)",
        product.ingredients_text
    )

    # Quan trọng:
    # normalize + dedup ngay sau khi lấy từ DB
    return normalize_and_deduplicate_ingredients(
        ingredients
    )


# =========================================================
# LẤY DỊ NGUYÊN CỦA SẢN PHẨM
# =========================================================

def get_product_allergens(product):

    if not product:
        return []

    if not product.allergens_tags:
        return []

    try:

        allergens = json.loads(
            product.allergens_tags
        )

        if isinstance(allergens, list):
            return allergens

    except (
        json.JSONDecodeError,
        TypeError
    ):

        pass

    return []


# =========================================================
# TỪ KHÓA DỊ NGUYÊN
# =========================================================

ALLERGEN_DEFINITIONS = {

    # =====================================================
    # SỮA
    # =====================================================

    "en:milk": (
        "Sữa",
        [
            "sữa",
            "sua",
            "milk",
            "milch",
            "lait",
            "milk powder",
            "milkpowder",
            "milchpulver",
            "magermilchpulver",
            "whey",
            "molke",
            "lactoserum",
            "casein",
            "lactose",
            "butter",
            "cream",
            "cheese",
        ],
    ),

    # =====================================================
    # ĐẬU NÀNH
    # =====================================================

    "en:soybeans": (
        "Đậu nành",
        [
            "soy",
            "soya",
            "soybean",
            "soybeans",
            "soja",
        ],
    ),

    # =====================================================
    # ĐẬU PHỘNG
    # =====================================================

    "en:peanuts": (
        "Đậu phộng",
        [
            "peanut",
            "peanuts",
            "groundnut",
            "erdnuss",
            "erdnusse",
        ],
    ),

    # =====================================================
    # TRỨNG
    # =====================================================

    "en:eggs": (
        "Trứng",
        [
            "egg",
            "eggs",
            "albumin",
            "albumen",
        ],
    ),

    # =====================================================
    # NGŨ CỐC CHỨA GLUTEN
    #
    # Giữ tag en:wheat để tương thích với dữ liệu
    # hiện tại của hệ thống.
    # =====================================================

    "en:wheat": (
        "Ngũ cốc chứa gluten",
        [
            "wheat",
            "weizen",
            "weizenmehl",
            "flour",
            "gluten",

            # Lúa mạch
            "barley",
            "barley flour",
            "barley malt",
            "malted barley",
            "gerste",
            "gersten",
            "gerstenmehl",
            "gerstenmalz",
        ],
    ),

    # =====================================================
    # CÁ
    # =====================================================

    "en:fish": (
        "Cá",
        [
            "fish",
            "fisch",
            "salmon",
            "tuna",
            "cod",
        ],
    ),

    # =====================================================
    # GIÁP XÁC
    # =====================================================

    "en:crustaceans": (
        "Giáp xác",
        [
            "shrimp",
            "prawn",
            "crab",
            "shellfish",
            "crustaceans",
        ],
    ),

    # =====================================================
    # CÁC LOẠI HẠT
    # =====================================================

    "en:tree-nuts": (
        "Các loại hạt",
        [
            "almond",
            "almonds",
            "cashew",
            "walnut",
            "hazelnut",
            "hazelnuts",
            "haselnuss",
            "haselnusse",
            "pistachio",
            "pistachios",
            "noisette",
            "noisettes",
        ],
    ),

    # =====================================================
    # MÙ TẠT
    # =====================================================

    "en:mustard": (
        "Mù tạt",
        [
            "mustard",
            "senf",
        ],
    ),

    # =====================================================
    # LUPIN
    # =====================================================

    "en:lupin": (
        "Đậu lupin",
        [
            "lupin",
            "lupine",
            "lupinen",
        ],
    ),

    # =====================================================
    # MÈ / VỪNG
    # =====================================================

    "en:sesame": (
        "Mè / vừng",
        [
            "sesame",
            "sesam",
        ],
    ),

    # =====================================================
    # ĐỘNG VẬT THÂN MỀM
    # =====================================================

    "en:molluscs": (
        "Động vật thân mềm",
        [
            "mollusc",
            "mollusk",
            "squid",
            "octopus",
            "mussel",
            "oyster",
            "clam",
        ],
    ),

    # =====================================================
    # CẦN TÂY
    # =====================================================

    "en:celery": (
        "Cần tây",
        [
            "celery",
            "sellerie",
        ],
    ),

    # =====================================================
    # SULFITE
    # =====================================================

    "en:sulphites": (
        "Sulfite",
        [
            "sulphite",
            "sulfite",
            "sulphur dioxide",
        ],
    ),
}


# =========================================================
# QUAN HỆ DỊ NGUYÊN CHA - CON
# =========================================================

ALLERGEN_HIERARCHY = {

    # =====================================================
    # CÁC LOẠI HẠT
    # =====================================================

    "en:tree-nuts": {
        "almond",
        "almonds",
        "cashew",
        "walnut",
        "hazelnut",
        "hazelnuts",
        "haselnuss",
        "haselnusse",
        "pistachio",
        "pistachios",
        "noisette",
        "noisettes",
    },

    # =====================================================
    # GIÁP XÁC
    # =====================================================

    "en:crustaceans": {
        "shrimp",
        "prawn",
        "crab",
        "shellfish",
        "crustaceans",
    },

    # =====================================================
    # ĐỘNG VẬT THÂN MỀM
    # =====================================================

    "en:molluscs": {
        "squid",
        "octopus",
        "mussel",
        "oyster",
        "clam",
    },

    # =====================================================
    # CÁ
    # =====================================================

    "en:fish": {
        "salmon",
        "tuna",
        "cod",
        "fish",
        "fisch",
    },

    # =====================================================
    # SỮA
    # =====================================================

    "en:milk": {
        "milk",
        "milch",
        "lait",
        "whey",
        "molke",
        "lactoserum",
        "casein",
        "lactose",
        "butter",
        "cream",
        "cheese",
    },

    # =====================================================
    # ĐẬU NÀNH
    # =====================================================

    "en:soybeans": {
        "soy",
        "soya",
        "soybean",
        "soybeans",
        "soja",
    },

    # =====================================================
    # ĐẬU PHỘNG
    # =====================================================

    "en:peanuts": {
        "peanut",
        "peanuts",
        "groundnut",
        "erdnuss",
        "erdnusse",
    },

    # =====================================================
    # TRỨNG
    # =====================================================

    "en:eggs": {
        "egg",
        "eggs",
        "albumin",
        "albumen",
    },

    # =====================================================
    # NGŨ CỐC CHỨA GLUTEN
    # =====================================================

    "en:wheat": {
        "wheat",
        "weizen",
        "weizenmehl",
        "flour",
        "gluten",
        "barley",
        "barley flour",
        "barley malt",
        "malted barley",
        "gerste",
        "gersten",
        "gerstenmehl",
        "gerstenmalz",
    },

    # =====================================================
    # MÙ TẠT
    # =====================================================

    "en:mustard": {
        "mustard",
        "senf",
    },

    # =====================================================
    # LUPIN
    # =====================================================

    "en:lupin": {
        "lupin",
        "lupine",
        "lupinen",
    },

    # =====================================================
    # MÈ
    # =====================================================

    "en:sesame": {
        "sesame",
        "sesam",
    },

    # =====================================================
    # CẦN TÂY
    # =====================================================

    "en:celery": {
        "celery",
        "sellerie",
    },

    # =====================================================
    # SULFITE
    # =====================================================

    "en:sulphites": {
        "sulphite",
        "sulfite",
        "sulphur dioxide",
    },
}


# =========================================================
# ALIAS TAG
# =========================================================

ALLERGEN_TAG_ALIASES = {
    "en:nuts": "en:tree-nuts",
    "en:tree_nuts": "en:tree-nuts",
    "en:sulfites": "en:sulphites",
    "en:sulfite": "en:sulphites",
}


# =========================================================
# CHUẨN HÓA TAG DỊ NGUYÊN
# =========================================================

def normalize_allergen_tag(tag):

    if not tag:
        return None

    normalized = str(
        tag
    ).strip().lower()

    if not normalized:
        return None

    if ":" not in normalized:
        normalized = f"en:{normalized}"

    return ALLERGEN_TAG_ALIASES.get(
        normalized,
        normalized
    )


# =========================================================
# RESOLVE TÊN DỊ NGUYÊN -> TAG
# =========================================================

def resolve_allergen_tag(value):
    """
    Chuyển tên dị nguyên thành tag chuẩn.

    Ví dụ:

        SOJA
        -> en:soybeans

        SENF
        -> en:mustard

        LUPINEN
        -> en:lupin

        HASELNÜSSE
        -> en:tree-nuts

    Hàm này giúp Gemini có thể trả về tên dị nguyên
    thay vì bắt buộc phải trả về off_tag.
    """

    if not value:
        return None

    # -----------------------------------------------------
    # Nếu value đã là tag
    # -----------------------------------------------------

    direct_tag = normalize_allergen_tag(value)

    if direct_tag in ALLERGEN_DEFINITIONS:
        return direct_tag

    normalized_value = normalize_text(value)

    if not normalized_value:
        return None

    # -----------------------------------------------------
    # So với label + keyword
    # -----------------------------------------------------

    for tag, definition in ALLERGEN_DEFINITIONS.items():

        label = definition[0]
        keywords = definition[1]

        candidates = {
            normalize_text(tag),
            normalize_text(
                tag.replace("en:", "")
            ),
            normalize_text(label),
        }

        candidates.update(
            normalize_text(keyword)
            for keyword in keywords
        )

        candidates.discard("")

        if normalized_value in candidates:
            return tag

    return None


# =========================================================
# KIỂM TRA TAG KHÔNG HỖ TRỢ
# =========================================================

def has_unsupported_allergen_tags(tags):

    return any(
        normalize_allergen_tag(tag)
        not in ALLERGEN_DEFINITIONS
        for tag in (tags or set())
    )


# =========================================================
# LẤY KEYWORD CỦA NHÓM DỊ NGUYÊN
# =========================================================

def get_allergen_keywords(tag):
    """
    Lấy toàn bộ keyword của một dị nguyên.

    Bao gồm:
    - keyword cơ bản
    - keyword của nhóm con
    """

    normalized_tag = normalize_allergen_tag(
        tag
    )

    if not normalized_tag:
        return set()

    definition = ALLERGEN_DEFINITIONS.get(
        normalized_tag
    )

    if not definition:
        return set()

    keywords = set(
        definition[1]
    )

    child_keywords = ALLERGEN_HIERARCHY.get(
        normalized_tag,
        set()
    )

    keywords.update(
        child_keywords
    )

    return keywords


# =========================================================
# KIỂM TRA MỘT THÀNH PHẦN CÓ THUỘC
# NHÓM DỊ NGUYÊN HAY KHÔNG
# =========================================================

def ingredient_matches_allergen(
    ingredient,
    allergen_tag
):
    """
    Kiểm tra thành phần có liên quan
    đến dị nguyên hay không.

    Ví dụ:

        ingredient = "almond flour"
        allergen = "en:tree-nuts"

        -> True

    Sử dụng word boundary để tránh match sai.
    """

    ingredient_normalized = normalize_text(
        ingredient
    )

    if not ingredient_normalized:
        return False

    keywords = get_allergen_keywords(
        allergen_tag
    )

    for keyword in keywords:

        keyword_normalized = normalize_text(
            keyword
        )

        if not keyword_normalized:
            continue

        # =================================================
        # Match theo từ hoàn chỉnh
        # =================================================

        keyword_pattern = (
            r"(?<!\w)"
            + re.escape(keyword_normalized)
            + r"(?!\w)"
        )

        if re.search(
            keyword_pattern,
            ingredient_normalized
        ):
            return True

    return False


# =========================================================
# CHUẨN HÓA DANH SÁCH DỊ NGUYÊN
# =========================================================

def _resolve_allergen_values(values):
    """
    Nhận:
        - en:soybeans
        - SOJA
        - soy
        - Đậu nành
        - mustard
        - SENF
        ...

    Trả về set tag chuẩn.
    """

    resolved = set()

    for value in values or []:

        tag = resolve_allergen_tag(value)

        if tag:
            resolved.add(tag)

    return resolved


# =========================================================
# SO SÁNH THÀNH PHẦN VỚI DỊ NGUYÊN
# =========================================================

def check_product_ingredients(
    product_ingredients,
    user_allergen_tags,
    product_allergen_tags=None,
    may_contain_allergen_values=None,
):
    """
    So sánh thành phần sản phẩm với dị nguyên
    mà người dùng đã chọn.

    Kết quả được chia thành:

    1. contains
       Sản phẩm thực sự có thành phần liên quan.

    2. may_contain
       Sản phẩm có cảnh báo có thể chứa vết.

    QUAN TRỌNG:

    Cùng một dị nguyên có thể xuất hiện ở cả hai nhóm.

    Ví dụ:

        Thành phần:
            Emulgator Lecithine (SOJA)

        Cảnh báo:
            Kann SOJA, SENF und LUPINEN enthalten

    Kết quả:

        Đậu nành
            -> contains
            -> may_contain

        Mù tạt
            -> may_contain

        Lupin
            -> may_contain

    Lupin KHÔNG được đưa vào contains chỉ vì
    Gemini đọc thấy chữ LUPINEN trong câu cảnh báo.
    """

    # =====================================================
    # 1. USER ALLERGENS
    # =====================================================

    selected_tags = _resolve_allergen_values(
        user_allergen_tags
    )

    # =====================================================
    # 2. PRODUCT DECLARED ALLERGENS
    # =====================================================

    product_tags = _resolve_allergen_values(
        product_allergen_tags
    )

    # =====================================================
    # 3. MAY CONTAIN ALLERGENS
    # =====================================================

    may_contain_tags = _resolve_allergen_values(
        may_contain_allergen_values
    )

    # =====================================================
    # KẾT QUẢ
    #
    # Dùng key:
    #
    # (tag, status)
    #
    # thay vì chỉ:
    #
    # tag
    #
    # để cùng một allergen có thể tồn tại:
    #
    # (soy, contains)
    # (soy, may_contain)
    # =====================================================

    grouped_results = {}

    # =====================================================
    # HÀM TẠO RESULT
    # =====================================================

    def get_or_create_result(
        tag,
        status
    ):

        key = (
            tag,
            status
        )

        definition = ALLERGEN_DEFINITIONS.get(
            tag
        )

        if not definition:
            return None

        if key not in grouped_results:

            grouped_results[key] = {
                "tag": tag,
                "label": definition[0],
                "ingredients": [],
                "evidence": [],
                "status": status,
            }

        return grouped_results[key]

    # =====================================================
    # 4. DỊ NGUYÊN KHAI BÁO TRỰC TIẾP
    # =====================================================

    for tag in selected_tags:

        if tag not in product_tags:
            continue

        result = get_or_create_result(
            tag,
            "contains"
        )

        if result is None:
            continue

        result["evidence"].append(
            "Dị nguyên được khai báo trong dữ liệu sản phẩm."
        )

    # =====================================================
    # 5. KIỂM TRA TỪNG THÀNH PHẦN
    # =====================================================

    normalized_ingredients = (
        normalize_and_deduplicate_ingredients(
            product_ingredients or []
        )
    )

    for ingredient in normalized_ingredients:

        ingredient_normalized = normalize_text(
            ingredient
        )

        if not ingredient_normalized:
            continue

        # =================================================
        # XÁC ĐỊNH CONTEXT
        #
        # Nếu ingredients thật sự chứa câu
        # "may contain..." thì vẫn nhận ra.
        #
        # Tuy nhiên dữ liệu tốt nhất là Gemini đã
        # tách phần may_contain riêng.
        # =================================================

        context = detect_ingredient_context(
            ingredient
        )

        for tag in selected_tags:

            definition = ALLERGEN_DEFINITIONS.get(
                tag
            )

            if not definition:
                continue

            matched = ingredient_matches_allergen(
                ingredient,
                tag
            )

            if not matched:
                continue

            result = get_or_create_result(
                tag,
                context
            )

            if result is None:
                continue

            # ---------------------------------------------
            # Lưu ingredient gây match
            # ---------------------------------------------

            if ingredient not in result["ingredients"]:

                result["ingredients"].append(
                    ingredient
                )

            # ---------------------------------------------
            # Lưu evidence
            # ---------------------------------------------

            evidence_text = (
                f"Thành phần: {ingredient}"
            )

            if evidence_text not in result["evidence"]:

                result["evidence"].append(
                    evidence_text
                )

    # =====================================================
    # 6. MAY CONTAIN
    #
    # Đây là phần QUAN TRỌNG NHẤT.
    #
    # Không đưa may_contain vào product_ingredients.
    #
    # Ví dụ:
    #
    # may_contain_allergen_values:
    # [
    #     "SOJA",
    #     "SENF",
    #     "LUPINEN"
    # ]
    #
    # thì:
    #
    # SOJA -> may_contain
    # SENF -> may_contain
    # LUPINEN -> may_contain
    #
    # nhưng không tự động -> contains.
    # =====================================================

    for value in (
        may_contain_allergen_values or []
    ):

        tag = resolve_allergen_tag(
            value
        )

        if not tag:
            continue

        # Chỉ cảnh báo nếu user có chọn dị nguyên này
        if tag not in selected_tags:
            continue

        result = get_or_create_result(
            tag,
            "may_contain"
        )

        if result is None:
            continue

        # ---------------------------------------------
        # Giữ bằng chứng gốc
        # ---------------------------------------------

        evidence_text = (
            f"Cảnh báo trên nhãn: {value}"
        )

        if evidence_text not in result["evidence"]:

            result["evidence"].append(
                evidence_text
            )

    # =====================================================
    # 7. TẠO KẾT QUẢ CUỐI
    # =====================================================

    results = []

    # Sắp xếp để contains đứng trước may_contain
    ordered_results = sorted(
        grouped_results.values(),
        key=lambda item: (
            0
            if item["status"] == "contains"
            else 1,
            item["label"]
        )
    )

    for match in ordered_results:

        ingredients = match[
            "ingredients"
        ]

        evidence = match[
            "evidence"
        ]

        label = match[
            "label"
        ]

        status = match[
            "status"
        ]

        # =================================================
        # MAY CONTAIN
        # =================================================

        if status == "may_contain":

            warning = (
                f"Có thể chứa vết {label}. "
                f"Không xác định chắc chắn "
                f"sản phẩm có chứa {label}."
            )

        # =================================================
        # CONTAINS
        # =================================================

        else:

            warning = (
                f"Sản phẩm có chứa thành phần "
                f"liên quan đến {label}."
            )

        results.append(
            {
                "tag": match["tag"],

                "allergen": label,

                "ingredients": ingredients,

                "ingredient": (
                    ingredients[0]
                    if ingredients
                    else None
                ),

                "evidence": evidence,

                "status": status,

                "warning": warning,
            }
        )

    return results