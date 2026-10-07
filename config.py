import os
from dotenv import load_dotenv


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


class Config:

    # =========================
    # FLASK
    # =========================

    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "allergy-warning-secret-key"
    )


    # =========================
    # MYSQL
    # =========================

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "mysql+pymysql://root:@localhost:3306/food_allergen_system"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False


    # =========================
    # UPLOAD
    # =========================

    UPLOAD_FOLDER = os.path.join(
        "static",
        "uploads"
    )

    MAX_CONTENT_LENGTH = 10 * 1024 * 1024

    TESSERACT_CMD = os.environ.get("TESSERACT_CMD")

    ALLOWED_EXTENSIONS = {
        "png",
        "jpg",
        "jpeg",
        "webp"
    }
