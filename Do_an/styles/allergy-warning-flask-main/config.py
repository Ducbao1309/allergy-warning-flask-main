import os
from dotenv import load_dotenv
from sqlalchemy.engine import URL

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def _database_uri():
    """
    Ưu tiên DATABASE_URL khi triển khai hosting.
    Nếu không có, ghép URI từ DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME.
    """
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # Một số nền tảng cung cấp postgres:// hoặc mysql:// dạng cũ.
        if database_url.startswith("mysql://"):
            database_url = database_url.replace(
                "mysql://", "mysql+pymysql://", 1
            )
        return database_url

    ssl_ca_value = os.environ.get("DB_SSL_CA", "certs/isrgrootx1.pem").strip()
    query = {}
    if ssl_ca_value:
        query = {
            "ssl_ca": os.path.join(PROJECT_ROOT, ssl_ca_value)
            if not os.path.isabs(ssl_ca_value)
            else ssl_ca_value,
            "ssl_verify_cert": "true",
            "ssl_verify_identity": "true",
        }

    return URL.create(
        drivername="mysql+pymysql",
        username=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        host=os.environ.get("DB_HOST"),
        port=int(os.environ.get("DB_PORT", "3306")),
        database=os.environ.get("DB_NAME"),
        query=query,
    )


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, "static", "uploads")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024

    TESSERACT_CMD = os.environ.get("TESSERACT_CMD")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
