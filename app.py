
from flask import Flask

from config import Config
from extensions import db

from datetime import timezone
from zoneinfo import ZoneInfo

from routes.product import product_bp
from routes.main import main_bp
from routes.auth import auth_bp
from routes.scan import scan_bp
from routes.profile import profile_bp
from routes.history import history_bp
from routes.admin import admin_bp


# =========================================================
# TẠO FLASK APP
# =========================================================

app = Flask(__name__)

@app.template_filter("vn_datetime")
def vn_datetime(value):
    if not value:
        return ""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    value = value.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))

    return value.strftime("%d/%m/%Y %H:%M")

app.config.from_object(Config)


# =========================================================
# CẤU HÌNH KẾT NỐI DATABASE
# =========================================================

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,
    "pool_timeout": 30,
    "pool_size": 5,
    "max_overflow": 10,
    "connect_args": {
        "connect_timeout": 10
    }
}


# =========================================================
# KHỞI TẠO DATABASE
# =========================================================

db.init_app(app)


# =========================================================
# REGISTER BLUEPRINT
# =========================================================

app.register_blueprint(main_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(scan_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(product_bp)
app.register_blueprint(history_bp)
app.register_blueprint(admin_bp)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )
