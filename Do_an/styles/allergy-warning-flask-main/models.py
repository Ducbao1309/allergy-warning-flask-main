from extensions import db
import uuid


# =========================================================
# USER
# =========================================================

class User(db.Model):
    __tablename__ = "user"

    id = db.Column(
        db.CHAR(32),
        primary_key=True,
        default=lambda: uuid.uuid4().hex
    )

    email = db.Column(
        db.String(255),
        unique=True,
        nullable=False
    )

    full_name = db.Column(
        db.String(255),
        nullable=True
    )

    hashed_password = db.Column(
        db.String(255),
        nullable=False
    )

    is_active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    is_superuser = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    # Quan hệ với UserAllergen
    allergens = db.relationship(
        "UserAllergen",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    scan_histories = db.relationship(
        "ScanHistory",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self):
        return f"<User {self.email}>"


# =========================================================
# ALLERGEN
# =========================================================

class Allergen(db.Model):
    __tablename__ = "allergens"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True
    )

    name = db.Column(
        db.String(255),
        nullable=False,
        unique=True
    )

    name_en = db.Column(
        db.String(255),
        nullable=True
    )

    off_tag = db.Column(
        db.String(255),
        nullable=True,
        unique=True
    )

    description = db.Column(
        db.String(255),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    # Quan hệ với UserAllergen
    users = db.relationship(
        "UserAllergen",
        back_populates="allergen",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Allergen {self.name}>"


# =========================================================
# USER - ALLERGEN
# =========================================================

class UserAllergen(db.Model):
    __tablename__ = "user_allergens"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True
    )

    user_id = db.Column(
        db.CHAR(32),
        db.ForeignKey(
            "user.id",
            ondelete="CASCADE"
        ),
        nullable=False
    )

    allergen_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "allergens.id",
            ondelete="CASCADE"
        ),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    # Quan hệ User
    user = db.relationship(
        "User",
        back_populates="allergens"
    )

    # Quan hệ Allergen
    allergen = db.relationship(
        "Allergen",
        back_populates="users"
    )

    # Không cho user chọn cùng một dị ứng 2 lần
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "allergen_id",
            name="unique_user_allergen"
        ),
    )

    def __repr__(self):
        return (
            f"<UserAllergen "
            f"user={self.user_id} "
            f"allergen={self.allergen_id}>"
        )


# =========================================================
# PRODUCT
# =========================================================

class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True
    )

    barcode = db.Column(
        db.String(50),
        unique=True,
        nullable=True
    )

    name = db.Column(
        db.String(255),
        nullable=False
    )

    brand = db.Column(
        db.String(255),
        nullable=True
    )

    ingredients_text = db.Column(
        db.Text,
        nullable=True
    )

    allergens_text = db.Column(
        db.Text,
        nullable=True
    )

    allergens_tags = db.Column(
        db.Text,
        nullable=True
    )

    image_url = db.Column(
        db.String(1000),
        nullable=True
    )

    source_url = db.Column(
        db.String(1000),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    # Quan hệ với ProductIngredient
    ingredients = db.relationship(
        "ProductIngredient",
        back_populates="product",
        cascade="all, delete-orphan"
    )

    scan_histories = db.relationship(
        "ScanHistory",
        back_populates="product",
    )

    def __repr__(self):
        return f"<Product {self.name}>"


# =========================================================
# PRODUCT INGREDIENT
# =========================================================

class ProductIngredient(db.Model):
    __tablename__ = "product_ingredients"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "products.id",
            ondelete="CASCADE"
        ),
        nullable=False
    )

    name = db.Column(
        db.String(255),
        nullable=False
    )

    name_en = db.Column(
        db.String(255),
        nullable=True
    )

    off_tag = db.Column(
        db.String(255),
        nullable=True
    )

    product = db.relationship(
        "Product",
        back_populates="ingredients"
    )

    def __repr__(self):
        return f"<ProductIngredient {self.name}>"


class ScanHistory(db.Model):
    """Immutable per-user snapshot of one completed product-label scan."""

    __tablename__ = "scan_history"
    __table_args__ = (
        db.Index("ix_scan_history_user_scanned_at", "user_id", "scanned_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_general_ci",
        },
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    scan_id = db.Column(db.String(32), nullable=False, unique=True)
    user_id = db.Column(
        db.CHAR(32),
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )
    product_name = db.Column(db.String(255), nullable=False)
    brand = db.Column(db.String(255), nullable=True)
    image_url = db.Column(db.String(1000), nullable=True)
    ingredients_json = db.Column(db.Text, nullable=False)
    allergens_json = db.Column(db.Text, nullable=False)
    warnings_json = db.Column(db.Text, nullable=False)
    warning_status = db.Column(db.String(20), nullable=False, index=True)
    scanned_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        index=True,
    )

    user = db.relationship("User", back_populates="scan_histories")
    product = db.relationship("Product", back_populates="scan_histories")

    def __repr__(self):
        return f"<ScanHistory {self.scan_id} user={self.user_id}>"
