from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import User


auth_bp = Blueprint("auth", __name__)


# =========================
# ĐĂNG NHẬP
# =========================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if not user:
            flash("Email không tồn tại.", "error")
            return render_template("login.html")

        if not check_password_hash(
            user.hashed_password,
            password
        ):
            flash("Mật khẩu không đúng.", "error")
            return render_template("login.html")

        # ==========================================
        # QUAN TRỌNG
        # ==========================================

        session.clear()

        session["user_id"] = user.id
        session["user_email"] = user.email
        session["user_name"] = user.full_name or user.email

        return redirect(url_for("main.dashboard"))

    return render_template("login.html")
       


# =========================
# ĐĂNG KÝ
# =========================
@auth_bp.route("/register", methods=["GET", "POST"])
def register():

    # Nếu đã đăng nhập
    if "user_id" in session:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":

        email = request.form.get("email", "").strip()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Kiểm tra dữ liệu
        if not email or not password:
            flash("Vui lòng nhập email và mật khẩu.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Mật khẩu xác nhận không khớp.", "error")
            return render_template("register.html")

        # Kiểm tra email đã tồn tại
        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            flash("Email đã được đăng ký.", "error")
            return render_template("register.html")

        # Mã hóa mật khẩu
        hashed_password = generate_password_hash(
            password,
            method="pbkdf2:sha256"
        )

        new_user = User(
            email=email,
            full_name=full_name,
            hashed_password=hashed_password,
            is_active=True,
            is_superuser=False
        )

        db.session.add(new_user)
        db.session.commit()

        flash("Đăng ký thành công! Hãy đăng nhập.", "success")

        return redirect(url_for("auth.login"))

    return render_template("register.html")


# =========================
# ĐĂNG XUẤT
# =========================
@auth_bp.route("/logout")
def logout():

    session.clear()

    flash("Đã đăng xuất.", "success")

    return redirect(url_for("auth.login"))
