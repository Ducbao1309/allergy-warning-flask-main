from flask import Flask

from config import Config
from extensions import db

from routes.product import product_bp
from routes.main import main_bp
from routes.auth import auth_bp
from routes.scan import scan_bp
from routes.profile import profile_bp
from routes.history import history_bp


# =========================================================
# TẠO FLASK APP
# =========================================================

app = Flask(__name__)

app.config.from_object(Config)


# =========================================================
# KẾT NỐI DATABASE
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

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )
