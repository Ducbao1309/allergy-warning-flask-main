import requests

OFF_ALLERGEN_URL = "https://static.openfoodfacts.org/data/taxonomies/allergens.json"


def get_allergens_from_openfoodfacts():
    """
    Lấy danh sách allergen từ Open Food Facts.
    """

    headers = {
        "User-Agent": "AllergyWarning/1.0"
    }

    response = requests.get(
        OFF_ALLERGEN_URL,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    allergens = []

    for tag, value in data.items():

        # Ví dụ tag:
        # en:milk
        # en:peanuts
        # en:soybeans

        if not tag.startswith("en:"):
            continue

        name_en = tag.replace("en:", "").replace("-", " ").title()

        name_vi = name_en

        # Một số tên tiếng Việt thông dụng
        vietnamese_names = {
            "Milk": "Sữa",
            "Eggs": "Trứng",
            "Peanuts": "Đậu phộng",
            "Soybeans": "Đậu nành",
            "Fish": "Cá",
            "Crustaceans": "Giáp xác",
            "Molluscs": "Động vật thân mềm",
            "Tree Nuts": "Các loại hạt cây",
            "Wheat": "Lúa mì",
            "Sesame": "Mè / Vừng",
            "Mustard": "Mù tạt",
            "Celery": "Cần tây",
            "Lupin": "Đậu lupin",
            "Sulphites": "Sulfite"
        }

        if name_en in vietnamese_names:
            name_vi = vietnamese_names[name_en]

        allergens.append({
            "name": name_vi,
            "name_en": name_en,
            "off_tag": tag
        })

    return allergens