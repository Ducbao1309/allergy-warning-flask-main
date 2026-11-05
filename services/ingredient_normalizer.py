"""Tách và chuẩn hóa thành phần thực phẩm bằng từ điển bí danh có kiểm soát.

Không dùng fuzzy matching để tự kết luận nguyên liệu/dị nguyên. Chỉ ánh xạ
khi tên sau chuẩn hóa khớp một bí danh đã khai báo; trường hợp khác giữ nguyên
văn bản gốc và đánh dấu unmatched.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class StandardIngredient:
    key: str
    name_vi: str
    name_en: str
    aliases: tuple[str, ...]


STANDARDS = (
    StandardIngredient("wheat_flour", "Bột mì", "Wheat flour", (
        "bot mi", "bột mì", "wheat flour", "wheat flour", "flour wheat",
    )),
    StandardIngredient("sugar", "Đường", "Sugar", (
        "duong", "đường", "sugar", "sucrose",
    )),
    StandardIngredient("glucose_syrup", "Siro glucose", "Glucose syrup", (
        "glucose sirup", "glucose syrup", "siro glucose", "syrup glucose",
    )),
    StandardIngredient("vegetable_shortening", "Shortening thực vật", "Vegetable shortening", (
        "shortening thuc vat", "shortening thực vật", "vegetable shortening", "shortening",
    )),
    StandardIngredient("vegetable_fat", "Chất béo thực vật", "Vegetable fat", (
        "chat beo thuc vat", "chat beo thyc vat khong hydro hoa",
        "chat beo thuc vat khong hydro hoa", "vegetable fat", "non hydrogenated vegetable fat",
    )),
    StandardIngredient("isomaltooligosaccharide_syrup", "Siro isomaltooligosaccharide", "Isomaltooligosaccharide syrup", (
        "isomalito oligo sirup", "isomaltooligosaccharide syrup", "isomalto oligo syrup",
        "isomaltooligo syrup",
    )),
    StandardIngredient("cocoa_powder", "Bột cacao", "Cocoa powder", (
        "bot cacao", "bột cacao", "cocoa powder", "cacao powder", "cocoa",
    )),
    StandardIngredient("whole_milk_powder", "Sữa bột nguyên kem", "Whole milk powder", (
        "sura bot nguyen kem", "sua bot nguyen kem", "sữa bột nguyên kem", "whole milk powder",
    )),
    StandardIngredient("egg", "Trứng", "Egg", (
        "trung", "trứng", "egg", "eggs", "whole egg",
    )),
    StandardIngredient("sodium_bicarbonate", "Natri hydrocarbonat", "Sodium bicarbonate", (
        "natri hydro carbonat", "sodium bicarbonate", "sodium hydrogen carbonate", "e500ii",
    )),
    StandardIngredient("ammonium_bicarbonate", "Amoni hydrocarbonat", "Ammonium bicarbonate", (
        "amoni hydro carbonat", "ammonium bicarbonate", "ammonium hydrogen carbonate", "e503ii",
    )),
    StandardIngredient("dextrose", "Dextrose", "Dextrose", (
        "dextrose", "duong dextrose", "đường dextrose", "glucose monohydrate",
    )),
    StandardIngredient("gelatin", "Gelatin", "Gelatin", (
        "gelatin", "gelatine", "e428",
    )),
    StandardIngredient("salt", "Muối", "Salt", (
        "muoi", "muối", "salt", "sodium chloride",
    )),
    StandardIngredient("monocalcium_phosphate", "Monocalci phosphat", "Monocalcium phosphate", (
        "monocalci orthophosphat", "monocalcium phosphate", "e341i",
    )),
    StandardIngredient("hydroxypropyl_distarch_phosphate", "Tinh bột biến tính hydroxypropyl distarch phosphate", "Hydroxypropyl distarch phosphate", (
        "hydroxypropyi distarch phosphate", "hydroxypropyl distarch phosphate", "e1442",
    )),
    StandardIngredient("xanthan_gum", "Gôm xanthan", "Xanthan gum", (
        "gom xanthan", "gôm xanthan", "xanthan gum", "e415",
    )),
    StandardIngredient("cocoa_butter", "Bơ cacao", "Cocoa butter", (
        "bo ca cao", "bơ cacao", "cocoa butter", "cacao butter",
    )),
    StandardIngredient("soy_lecithin", "Lecithin đậu nành", "Soy lecithin", (
        "lecithin dau nanh", "lecithin đậu nành", "soy lecithin", "soya lecithin", "e322",
    )),
    StandardIngredient("polyglycerol_polyricinoleate", "Este polyglycerol polyricinoleate", "Polyglycerol polyricinoleate", (
        "este ca acid ricinoleic voi polyglycerol", "este của acid ricinoleic với polyglycerol",
        "polyglycerol polyricinoleate", "pgpr", "e476",
    )),
    StandardIngredient("vanilla_flavor", "Hương vani", "Vanilla flavoring", (
        "huong vani tong hop", "hương vani tổng hợp", "synthetic vanilla flavor", "vanilla flavoring",
    )),
    StandardIngredient("milk_protein", "Protein sữa", "Milk protein", (
        "protein sua", "protein sữa", "milk protein", "milk proteins",
    )),
    StandardIngredient("cocoa_mass", "Khối cacao", "Cocoa mass", (
        "khoi cacao", "cocoa mass", "cocoa liquor", "cocoa paste",
    )),
    StandardIngredient("cocoa_powder_butter_mixture", "Hỗn hợp bột cacao và bơ cacao", "Cocoa powder and cocoa butter mixture", (
        "hon hop bot cacao va bo ca cao", "hỗn hợp bột cacao và bơ ca cao",
    )),

    # Sữa và các thành phần từ sữa
    StandardIngredient("milk_powder", "Sữa bột", "Milk powder", (
        "sua bot", "milk powder", "powdered milk",
    )),
    StandardIngredient("skimmed_milk_powder", "Sữa bột gầy", "Skimmed milk powder", (
        "sua bot gay", "skimmed milk powder", "skim milk powder",
    )),
    StandardIngredient("whey", "Whey (đạm whey)", "Whey", (
        "whey", "whey powder", "whey protein", "bot whey",
    )),
    StandardIngredient("whey_protein_concentrate", "Đạm whey cô đặc", "Whey protein concentrate", (
        "whey protein concentrate", "wpc",
    )),
    StandardIngredient("lactose", "Lactose", "Lactose", (
        "lactose", "duong sua", "milk sugar",
    )),
    StandardIngredient("milk_fat", "Chất béo sữa", "Milk fat", (
        "chat beo sua", "milk fat", "butterfat",
    )),
    StandardIngredient("colostrum", "Sữa non", "Colostrum", (
        "colostrum", "colastrum",
    )),
    StandardIngredient("casein", "Casein", "Casein", (
        "casein", "caseinate",
    )),
    StandardIngredient("milk_protein", "Protein sữa", "Milk protein", (
        "protein sua", "milk protein", "milk proteins",
    )),

    # Dầu, chất béo, đường và tinh bột
    StandardIngredient("vegetable_oil", "Dầu thực vật", "Vegetable oil", (
        "dau thuc vat", "vegetable oil", "vegetable oils",
    )),
    StandardIngredient("palm_oil", "Dầu cọ", "Palm oil", (
        "dau co", "palm oil", "palmolein",
    )),
    StandardIngredient("fish_oil", "Dầu cá", "Fish oil", (
        "dau ca", "fish oil", "fish oils",
    )),
    StandardIngredient("maltodextrin", "Maltodextrin", "Maltodextrin", (
        "maltodextrin", "maltodextrine",
    )),
    StandardIngredient("inulin", "Inulin", "Inulin", (
        "inulin",
    )),
    StandardIngredient("modified_starch", "Tinh bột biến tính", "Modified starch", (
        "tinh bot bien tinh", "modified starch",
    )),
    StandardIngredient("starch", "Tinh bột", "Starch", (
        "tinh bot", "starch",
    )),
    StandardIngredient("citric_acid", "Axit citric", "Citric acid", (
        "axit citric", "acid citric", "citric acid", "e330",
    )),
    StandardIngredient("sodium_citrate", "Natri citrat", "Sodium citrate", (
        "natri citrat", "sodium citrate", "e331",
    )),
    StandardIngredient("potassium_citrate", "Kali citrat", "Potassium citrate", (
        "kali citrat", "potassium citrate", "e332",
    )),
    StandardIngredient("calcium_citrate", "Calci citrat", "Calcium citrate", (
        "calci citrat", "calcium citrate", "e333",
    )),
    StandardIngredient("glucose", "Glucose", "Glucose", (
        "glucose", "d glucose",
    )),
    StandardIngredient("fructose", "Fructose", "Fructose", (
        "fructose", "d fructose",
    )),

    # Chất nhũ hóa, phụ gia và chất chống oxy hóa
    StandardIngredient("lecithin", "Lecithin", "Lecithin", (
        "lecithin",
    )),
    StandardIngredient("soy_lecithin", "Lecithin đậu nành", "Soy lecithin", (
        "lecithin dau nanh", "soy lecithin", "soya lecithin",
    )),
    StandardIngredient("xanthan_gum", "Gôm xanthan", "Xanthan gum", (
        "gom xanthan", "xanthan gum", "e415",
    )),
    StandardIngredient("sodium_ascorbate", "Natri ascorbat", "Sodium ascorbate", (
        "natri ascorbat", "sodium ascorbate",
    )),
    StandardIngredient("ascorbyl_palmitate", "Ascorbyl palmitat", "Ascorbyl palmitate", (
        "ascorbyl palmitat", "ascorbyl palmitate", "e304",
    )),
    StandardIngredient("tocopherols", "Hỗn hợp tocopherol", "Mixed tocopherols", (
        "tocopherol", "tocopherols", "mixed tocopherols",
    )),
    StandardIngredient("natural_flavoring", "Hương liệu tự nhiên", "Natural flavouring", (
        "huong lieu tu nhien", "natural flavouring", "natural flavoring",
    )),
    StandardIngredient("antioxidant", "Chất chống oxy hóa", "Antioxidant", (
        "chat chong oxy hoa", "antioxidant",
    )),

    # Vitamin
    StandardIngredient("vitamin_a", "Vitamin A", "Vitamin A", (
        "vitamin a", "retinol",
    )),
    StandardIngredient("vitamin_b1", "Vitamin B1", "Vitamin B1", (
        "vitamin b1", "b1", "thiamin", "thiamine",
    )),
    StandardIngredient("vitamin_b2", "Vitamin B2", "Vitamin B2", (
        "vitamin b2", "b2", "riboflavin",
    )),
    StandardIngredient("vitamin_b3", "Vitamin B3 (Niacin)", "Vitamin B3 (Niacin)", (
        "vitamin b3", "b3", "vitamin pp", "pp", "niacin", "nicotinic acid",
    )),
    StandardIngredient("vitamin_b5", "Vitamin B5", "Vitamin B5", (
        "vitamin b5", "b5", "pantothenic acid",
    )),
    StandardIngredient("vitamin_b6", "Vitamin B6", "Vitamin B6", (
        "vitamin b6", "b6", "pyridoxine",
    )),
    StandardIngredient("vitamin_b9", "Vitamin B9 (Axit folic)", "Vitamin B9 (Folic acid)", (
        "vitamin b9", "b9", "folic acid", "acid folic", "axit folic",
    )),
    StandardIngredient("vitamin_b12", "Vitamin B12", "Vitamin B12", (
        "vitamin b12", "b12", "cyanocobalamin",
    )),
    StandardIngredient("vitamin_c", "Vitamin C", "Vitamin C", (
        "vitamin c", "ascorbic acid", "axit ascorbic",
    )),
    StandardIngredient("vitamin_d3", "Vitamin D3", "Vitamin D3", (
        "vitamin d3", "d3", "cholecalciferol",
    )),
    StandardIngredient("vitamin_e", "Vitamin E", "Vitamin E", (
        "vitamin e", "tocopherol vitamin e",
    )),
    StandardIngredient("vitamin_k1", "Vitamin K1", "Vitamin K1", (
        "vitamin k1", "k1", "phylloquinone",
    )),

    # Khoáng chất
    StandardIngredient("calcium", "Canxi", "Calcium", (
        "canxi", "calcium",
    )),
    StandardIngredient("calcium_d_pantothenate", "Calci D-pantothenat", "Calcium D-pantothenate", (
        "calci d pantothenat", "calcium d pantothenate", "calcium pantothenate",
    )),
    StandardIngredient("iron", "Sắt", "Iron", (
        "sat", "iron",
    )),
    StandardIngredient("zinc", "Kẽm", "Zinc", (
        "kem", "zinc",
    )),
    StandardIngredient("copper_sulfate", "Đồng sulfat", "Copper sulfate", (
        "dong sulfat", "copper sulfate", "copper sulphate",
    )),
    StandardIngredient("manganese_sulfate", "Mangan sulfat", "Manganese sulfate", (
        "mangan sulfat", "manganese sulfate", "manganese sulphate",
    )),
    StandardIngredient("magnesium_sulfate", "Magie sulfat", "Magnesium sulfate", (
        "magie sulfat", "magnesium sulfate", "magnesium sulphate",
    )),
    StandardIngredient("potassium_iodide", "Kali iodid", "Potassium iodide", (
        "kali iodid", "potassium iodide",
    )),
    StandardIngredient("sodium_selenite", "Natri selenit", "Sodium selenite", (
        "natri selenit", "sodium selenite",
    )),

    # Thành phần dinh dưỡng khác
    StandardIngredient("choline", "Cholin", "Choline", (
        "cholin", "choline", "choline chloride",
    )),
    StandardIngredient("taurine", "Taurin", "Taurine", (
        "taurin", "taurine",
    )),
    StandardIngredient("myo_inositol", "Myo-inositol", "Myo-inositol", (
        "myo inositol", "inositol",
    )),
    StandardIngredient("l_carnitine", "L-Carnitin", "L-Carnitine", (
        "l carnitin", "l carnitine", "carnitine",
    )),
    StandardIngredient("ara", "Axit arachidonic (ARA)", "Arachidonic acid (ARA)", (
        "ara", "arachidonic acid", "axit arachidonic",
    )),
    StandardIngredient("dha", "Axit docosahexaenoic (DHA)", "Docosahexaenoic acid (DHA)", (
        "dha", "docosahexaenoic acid", "axit docosahexaenoic",
        "dha from fish oil", "dha tu dau ca", "dha ti dau ca",
    )),
    StandardIngredient("lutein", "Lutein", "Lutein", (
        "lutein", "lutein ester",
    )),
)


def normalize_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("đ", "d")
    value = re.sub(r"\([^)]*\)", " ", value)  # bỏ mã E khi so tên; mã được xử lý riêng
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split()).strip()


ALIAS_LOOKUP: dict[str, StandardIngredient] = {}
for standard in STANDARDS:
    for alias in (standard.name_vi, standard.name_en, *standard.aliases):
        ALIAS_LOOKUP[normalize_key(alias)] = standard

# Nhãn chức năng/phụ gia thường đứng trước danh sách các chất bên trong ngoặc.
FUNCTION_LABELS = {
    "chat tao xop", "chat on dinh", "chat nhu hoa", "chat bao quan",
    "chat tao ngot", "chat dieu chinh do axit", "huong lieu", "hon hop",
}


def _strip_outer_punctuation(value: str) -> str:
    value = value.strip(" \t\r\n.,;:•-–—")
    while value.startswith(("(", "[", "{")):
        value = value[1:].lstrip()
    while value.endswith((")", "]", "}")):
        value = value[:-1].rstrip()
    return value.strip(" \t\r\n.,;:")


def clean_ingredients_text(raw_text: str | None) -> str:
    """Cắt nhãn và phần mô tả ngoài danh sách thành phần khi nhận diện được."""
    text = str(raw_text or "").strip()
    if not text:
        return ""

    # Bỏ nhãn đầu câu tiếng Việt/Anh.
    text = re.sub(r"^\s*(thành\s*phần|thanh\s*phan|ingredients?)\s*[:：-]\s*", "", text, flags=re.I)

    # Cắt các phần ngoài danh sách nếu chúng xuất hiện sau phần thành phần.
    stop_patterns = (
        r"\bHướng dẫn bảo quản\b", r"\bHướng dẫn sử dụng\b",
        r"\bBảo quản nơi\b", r"\bSản phẩm của\b", r"\bĐịa chỉ\b",
        r"\bDrink responsibly\b", r"\bUống bia có trách nhiệm\b",
        r"\bMSD[- ]NSX\b", r"\bSố TNCB\b",
    )
    cuts = [m.start() for pattern in stop_patterns if (m := re.search(pattern, text, re.I))]
    if cuts:
        text = text[:min(cuts)]
    return text.strip(" \t\r\n.;,:-")


def split_ingredient_text(raw_text: str | None) -> list[str]:
    """Tách nguyên liệu từ nhãn gốc; tách cả các chất trong ngoặc phụ gia.

    Dấu phẩy/chấm phẩy được dùng làm dấu phân cách. Các nhãn chức năng như
    'chất tạo xốp' được bỏ nếu phía sau là danh sách chất cụ thể trong ngoặc.
    """
    text = clean_ingredients_text(raw_text)
    if not text:
        return []

    # Gỡ nhãn nhóm trước dấu ngoặc để giữ lại các chất cụ thể bên trong.
    text = re.sub(
        r"(?i)(?:chất|chat|chát)\s+(?:tạo\s+xốp|tao\s+xop|ổn\s+định|on\s+dinh|"
        r"nhũ\s+hóa|nhu\s+hoa|bảo\s+quản|bao\s+quan|tạo\s+ngọt|tao\s+ngot|"
        r"điều\s+chỉnh\s+độ\s+axit|dieu\s+chinh\s+do\s+axit)\s*\(",
        "(", text,
    )

    # Tách theo dấu phân cách kể cả trong ngoặc để không gộp thành phần phụ gia.
    vitamin_context = bool(re.search(r"\bvitamin\b", text, re.I))
    pieces = re.split(r"[,;\n]+", text)
    if vitamin_context:
        expanded_pieces = []
        for piece in pieces:
            compact = normalize_key(piece)
            if compact in {"d3 b12", "b12 d3"}:
                expanded_pieces.extend(["D3", "B12"])
            else:
                expanded_pieces.append(piece)
        pieces = expanded_pieces
    result: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        item = _strip_outer_punctuation(piece)
        item = re.sub(r"^\(+\s*", "", item).strip()
        # Khôi phục dấu ngoặc đóng bị thiếu trong dữ liệu OCR/nhãn nguồn.
        open_count = item.count("(")
        close_count = item.count(")")
        if open_count > close_count:
            item += ")" * (open_count - close_count)
        if not item:
            continue
        key = normalize_key(item)
        if vitamin_context and key in {"a", "e"}:
            item = "Vitamin " + key.upper()
            key = normalize_key(item)
        if not key or key in FUNCTION_LABELS:
            continue
        # Bỏ đoạn chỉ còn mã E; mã E gắn với tên chất vẫn được giữ để tra cứu.
        if re.fullmatch(r"e\s*\d+[a-z]{0,2}", key):
            continue
        if key not in seen:
            seen.add(key)
            result.append(item[:255])
    return result


def normalize_ingredient(name: str, off_tag: str | None = None) -> dict:
    """Trả kết quả chuẩn hóa có kiểm soát; không tự đoán khi không khớp."""
    key = normalize_key(name)
    standard = ALIAS_LOOKUP.get(key)

    # Mã OFF có thể giúp xác nhận một số phụ gia đã biết.
    tag_key = normalize_key(off_tag or "")
    if standard is None and tag_key:
        # Một số tag tiếng Việt của OFF có dạng vi:<tên-nguyên-liệu>.
        tag_tail = tag_key.split()[-1] if tag_key else ""
        standard = ALIAS_LOOKUP.get(tag_tail)
        tag_aliases = {
            "en e500ii": "sodium_bicarbonate",
            "en e503ii": "ammonium_bicarbonate",
            "en e428": "gelatin",
            "en e341i": "monocalcium_phosphate",
            "en e1442": "hydroxypropyl_distarch_phosphate",
            "en e415": "xanthan_gum",
            "en e322": "soy_lecithin",
            "en e476": "polyglycerol_polyricinoleate",
        }
        wanted = tag_aliases.get(tag_key) or tag_aliases.get(tag_tail)
        if wanted and standard is None:
            standard = next((item for item in STANDARDS if item.key == wanted), None)

    if standard:
        return {
            "normalized_name": standard.name_vi,
            "normalized_name_en": standard.name_en,
            "standard_key": standard.key,
            "normalization_status": "matched",
        }

    return {
        "normalized_name": None,
        "normalized_name_en": None,
        "standard_key": None,
        "normalization_status": "unmatched",
    }


def build_normalized_ingredients(product) -> list[dict]:
    """Tạo danh sách hiển thị; ưu tiên parse lại text gốc để sửa row cũ bị cụt."""
    source_rows = []
    if getattr(product, "ingredients_text", None):
        source_rows = [{"name": name, "off_tag": None} for name in split_ingredient_text(product.ingredients_text)]
    else:
        source_rows = [
            {"name": item.name, "off_tag": item.off_tag}
            for item in getattr(product, "ingredients", [])
            if getattr(item, "name", None)
        ]

    output = []
    for row in source_rows:
        normalized = normalize_ingredient(row["name"], row.get("off_tag"))
        output.append({**row, **normalized})
    return output


def normalize_product_rows(product) -> list[dict]:
    """Rows để crawler/backfill lưu vào product_ingredients."""
    rows = []
    for name in split_ingredient_text(getattr(product, "ingredients_text", None)):
        normalized = normalize_ingredient(name)
        rows.append({"name": name, **normalized, "off_tag": None})
    return rows
