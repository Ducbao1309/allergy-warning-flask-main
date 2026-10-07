from app import app
from extensions import db
from models import User
from services.off_service import get_allergens_from_openfoodfacts


def seed_allergens():

    print("======================================")
    print(" LẤY DỮ LIỆU ALLERGEN TỪ OPEN FOOD FACTS")
    print("======================================")

    allergens = get_allergens_from_openfoodfacts()

    print(f"Tìm thấy {len(allergens)} allergen")

    with app.app_context():

        for allergen in allergens:

            existing = db.session.execute(
                db.text(
                    """
                    SELECT id
                    FROM allergens
                    WHERE off_tag = :off_tag
                    """
                ),
                {
                    "off_tag": allergen["off_tag"]
                }
            ).fetchone()

            if existing:

                print(
                    f"Đã tồn tại: "
                    f"{allergen['name']} "
                    f"({allergen['off_tag']})"
                )

                continue

            db.session.execute(
                db.text(
                    """
                    INSERT INTO allergens
                    (
                        name,
                        name_en,
                        off_tag
                    )
                    VALUES
                    (
                        :name,
                        :name_en,
                        :off_tag
                    )
                    """
                ),
                {
                    "name": allergen["name"],
                    "name_en": allergen["name_en"],
                    "off_tag": allergen["off_tag"]
                }
            )

            print(
                f"Đã thêm: "
                f"{allergen['name']}"
            )

        db.session.commit()

    print("======================================")
    print(" HOÀN TẤT")
    print("======================================")


if __name__ == "__main__":
    seed_allergens()