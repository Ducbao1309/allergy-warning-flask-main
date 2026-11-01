
import os
from dotenv import load_dotenv
from sqlalchemy.engine import URL

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


class Config:

    # FLASK
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # TI DB CLOUD
    DB_HOST = os.environ.get("DB_HOST")
    DB_PORT = int(os.environ.get("DB_PORT", "4000"))
    DB_USER = os.environ.get("DB_USER")
    DB_PASSWORD = os.environ.get("DB_PASSWORD")
    DB_NAME = os.environ.get("DB_NAME")

    DB_SSL_CA = os.path.join(
        PROJECT_ROOT,
        os.environ.get("DB_SSL_CA", "certs/isrgrootx1.pem")
    )

    SQLALCHEMY_DATABASE_URI = URL.create(
        drivername="mysql+pymysql",
        username=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        query={
            "ssl_ca": DB_SSL_CA,
            "ssl_verify_cert": "true",
            "ssl_verify_identity": "true"
        }
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # UPLOAD
    UPLOAD_FOLDER = os.path.join(
        PROJECT_ROOT,
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
