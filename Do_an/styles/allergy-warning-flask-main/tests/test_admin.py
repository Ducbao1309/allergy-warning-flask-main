import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from werkzeug.security import generate_password_hash


class _Comparable:
    def __ge__(self, _other):
        return True


class AdminRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import app

        cls.app = app
        cls.app.config.update(TESTING=True, SECRET_KEY="admin-tests-only")

    def setUp(self):
        self.client = self.app.test_client()
        self.admin = SimpleNamespace(
            id="admin-id",
            email="admin@example.test",
            full_name="Admin User",
            hashed_password=generate_password_hash("correct-password"),
            is_active=True,
            is_superuser=True,
        )

    def _set_session(self, client=None, user_id="admin-id"):
        client = client or self.client
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["user_email"] = self.admin.email
            session["user_name"] = self.admin.full_name
            session["admin_csrf_token"] = "valid-token"

    def _user_patch(self, user=None):
        query = Mock()
        query.filter_by.return_value.first.return_value = user or self.admin
        return patch("routes.admin.User", SimpleNamespace(query=query))

    def _auth_user_patch(self, user=None):
        query = Mock()
        query.filter_by.return_value.first.return_value = user or self.admin
        return patch("routes.auth.User", SimpleNamespace(query=query))

    def _fake_product_model(self, products=None, total=0, page=1, pages=1):
        products = products or []
        query = Mock()
        query.filter.return_value = query
        query.order_by.return_value = query
        pagination = SimpleNamespace(
            items=products,
            total=total,
            page=page,
            pages=pages,
            has_prev=page > 1,
            has_next=page < pages,
            prev_num=page - 1,
            next_num=page + 1,
        )
        query.paginate.return_value = pagination
        field = SimpleNamespace(ilike=Mock(return_value=True))
        fake_product = SimpleNamespace(
            query=query,
            name=field,
            brand=field,
            barcode=field,
            id=SimpleNamespace(desc=Mock(return_value="id_desc")),
            created_at=_Comparable(),
        )
        return fake_product, query, pagination

    def test_shared_login_redirects_normal_user_to_user_dashboard(self):
        normal = SimpleNamespace(
            **{**vars(self.admin), "is_superuser": False}
        )
        with self._auth_user_patch(normal), self.client:
            response = self.client.post(
                "/login",
                data={"email": normal.email, "password": "correct-password"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/dashboard"))
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], normal.id)
            self.assertEqual(session["user_email"], normal.email)
            self.assertEqual(session["user_name"], normal.full_name)
        with self._user_patch(normal):
            denied = self.client.get("/admin/")
        self.assertEqual(denied.status_code, 403)

    def test_shared_login_redirects_active_admin_to_admin_dashboard(self):
        with self._auth_user_patch(), self.client:
            response = self.client.post(
                "/login",
                data={"email": self.admin.email, "password": "correct-password"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/admin/"))
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], self.admin.id)
            self.assertNotIn("role", session)

        product_query = Mock()
        product_query.count.return_value = 0
        product_query.filter.return_value.count.return_value = 0
        fake_product = SimpleNamespace(
            query=product_query,
            created_at=_Comparable(),
        )
        with self._user_patch(), patch("routes.admin.Product", fake_product):
            dashboard = self.client.get("/admin/")
        self.assertEqual(dashboard.status_code, 200)

    def test_invalid_credentials_through_shared_login_keep_existing_response(self):
        with self._auth_user_patch(), self.client:
            response = self.client.post(
                "/login",
                data={"email": self.admin.email, "password": "incorrect"},
            )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_inactive_admin_can_not_access_admin_after_shared_login(self):
        inactive = SimpleNamespace(
            **{**vars(self.admin), "is_active": False}
        )
        with self._auth_user_patch(inactive), self.client:
            response = self.client.post(
                "/login",
                data={"email": inactive.email, "password": "correct-password"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/dashboard"))
        with self._user_patch(inactive):
            denied = self.client.get("/admin/")
        self.assertEqual(denied.status_code, 403)

    def test_legacy_admin_login_url_redirects_to_shared_login(self):
        self.assertEqual(self.client.get("/admin/login").status_code, 302)
        response = self.client.post("/admin/login")
        self.assertTrue(response.headers["Location"].endswith("/login"))

    def test_anonymous_and_normal_users_cannot_access_admin(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))

        self._set_session()
        normal = SimpleNamespace(is_active=True, is_superuser=False)
        with self._user_patch(normal):
            self.assertEqual(self.client.get("/admin/").status_code, 403)

    def test_admin_logout_requires_post_and_clears_session(self):
        self._set_session()
        with self._user_patch():
            self.assertEqual(self.client.get("/admin/logout").status_code, 405)
            response = self.client.post("/admin/logout", data={"csrf_token": "valid-token"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_dashboard_shows_database_counts_and_phase_c_status(self):
        self._set_session()
        query = Mock()
        query.count.return_value = 12
        query.filter.return_value.count.return_value = 3
        fake_product = SimpleNamespace(
            query=query,
            created_at=_Comparable(),
        )
        with self._user_patch(), patch("routes.admin.Product", fake_product):
            response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"12", response.data)
        self.assertIn(b"3", response.data)
        self.assertIn(b"Admin Panel", response.data)
        self.assertIn(b"admin@example.test", response.data)
        self.assertNotIn(b'class="navbar"', response.data)
        for user_path in (b'href="/scan', b'href="/history', b'href="/profile', b'href="/dashboard'):
            self.assertNotIn(user_path, response.data)
        for admin_navigation in ("Dashboard", "Sản phẩm", "Data Crawler", "Đăng xuất"):
            self.assertIn(admin_navigation.encode(), response.data)
        self.assertIn("Chưa có dữ liệu".encode(), response.data)
        self.assertNotIn("Ch\u01b0a tri\u1ec3n khai".encode(), response.data)
        self.assertGreaterEqual(response.data.count("Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u".encode()), 2)

    def test_crawler_page_renders_controls(self):
        self._set_session()
        with self._user_patch():
            response = self.client.get("/admin/crawler")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Open Food Facts", response.data)
        self.assertIn(b'name="count"', response.data)
        self.assertIn(b'type="number"', response.data)
        self.assertIn(b'min="1"', response.data)
        self.assertIn(b'max="100"', response.data)
        self.assertIn(b'action="/admin/crawler/start"', response.data)

    def test_crawler_start_requires_admin_and_post(self):
        response = self.client.post(
            "/admin/crawler/start", data={"count": "10", "csrf_token": "valid-token"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))

        self._set_session()
        regular_user = SimpleNamespace(is_active=True, is_superuser=False)
        with self._user_patch(regular_user), patch(
            "crawler.openfoodfacts_crawler.run_crawler"
        ) as run_crawler:
            response = self.client.post(
                "/admin/crawler/start",
                data={"count": "10", "csrf_token": "valid-token"},
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.client.get("/admin/crawler/start").status_code, 405)
        run_crawler.assert_not_called()

    def test_crawler_start_validates_count_and_csrf_before_running(self):
        self._set_session()
        with self._user_patch(), patch(
            "crawler.openfoodfacts_crawler.run_crawler"
        ) as run_crawler:
            no_csrf = self.client.post("/admin/crawler/start", data={"count": "10"})
            self.assertEqual(no_csrf.status_code, 400)

            for count in ("", "not-a-number", "0", "-1", "101", "10.5"):
                response = self.client.post(
                    "/admin/crawler/start",
                    data={"count": count, "csrf_token": "valid-token"},
                )
                self.assertEqual(response.status_code, 400, count)
        run_crawler.assert_not_called()

    def test_admin_crawler_post_renders_structured_result(self):
        self._set_session()
        result = {
            "requested_count": 10,
            "fetched_count": 10,
            "inserted_count": 7,
            "duplicate_count": 3,
            "error_count": 0,
            "status": "success",
            "errors": [],
            "started_at": "2026-10-13T10:00:00+07:00",
            "finished_at": "2026-10-13T10:00:02+07:00",
        }
        with self._user_patch(), patch(
            "crawler.openfoodfacts_crawler.run_crawler", return_value=result
        ) as run_crawler:
            response = self.client.post(
                "/admin/crawler/start",
                data={"count": "10", "csrf_token": "valid-token"},
            )

        self.assertEqual(response.status_code, 200)
        run_crawler.assert_called_once_with(10)
        self.assertIn(b"admin-crawl-status-success", response.data)
        for value in (b">10<", b">7<", b">3<", b">0<"):
            self.assertIn(value, response.data)

    def test_admin_crawler_api_error_renders_friendly_result(self):
        self._set_session()
        with self._user_patch(), patch(
            "crawler.openfoodfacts_crawler.requests.get",
            side_effect=requests.Timeout("offline"),
        ):
            response = self.client.post(
                "/admin/crawler/start",
                data={"count": "10", "csrf_token": "valid-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"admin-crawl-status-error", response.data)
        self.assertIn(b"Could not connect to Open Food Facts.", response.data)
        self.assertNotIn(b"Traceback", response.data)

    def test_product_delete_uses_custom_confirmation_modal_and_post_form(self):
        self._set_session()
        product = SimpleNamespace(
            id=7,
            name="Soy Drink",
            brand="Example",
            barcode="123",
            created_at=None,
        )
        fake_product, _query, _pagination = self._fake_product_model(
            products=[product], total=1
        )
        with self._user_patch(), patch("routes.admin.Product", fake_product):
            response = self.client.get("/admin/products")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'method="post"', response.data)
        self.assertIn(b'action="/admin/products/7/delete"', response.data)
        self.assertIn(b"data-confirm-delete", response.data)
        self.assertNotIn(b"onsubmit=", response.data)
        self.assertIn("Xóa sản phẩm?".encode(), response.data)
        self.assertIn("Bạn có chắc chắn muốn xóa sản phẩm này không?".encode(), response.data)
        self.assertIn("Lịch sử quét của sản phẩm sẽ được giữ lại.".encode(), response.data)
        self.assertIn("data-delete-cancel".encode(), response.data)
        self.assertIn("data-delete-confirm".encode(), response.data)

    def test_product_search_is_database_side_and_pagination_keeps_query(self):
        self._set_session()
        fake_product, query, pagination = self._fake_product_model(total=41, page=1, pages=3)
        with self._user_patch(), patch("routes.admin.Product", fake_product):
            response = self.client.get("/admin/products?q=Vina&page=2")
        self.assertEqual(response.status_code, 200)
        query.filter.assert_called_once()
        query.paginate.assert_called_once_with(page=2, per_page=20, error_out=False)
        self.assertIn(b"q=Vina", response.data)
        self.assertEqual(pagination.total, 41)

    def test_product_detail_displays_actual_fields_and_ingredients(self):
        self._set_session()
        product = SimpleNamespace(
            id=7,
            name="Soy Drink",
            brand="Example",
            barcode=None,
            created_at=None,
            image_url=None,
            source_url=None,
            ingredients_text="water, soy",
            allergens_text="soy",
            allergens_tags='["en:soybeans"]',
            ingredients=[SimpleNamespace(name="soy", name_en="Soy", off_tag="en:soybeans")],
        )
        with self._user_patch(), patch("routes.admin.db.session.get", return_value=product):
            response = self.client.get("/admin/products/7")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Soy Drink", response.data)
        self.assertIn(b"en:soybeans", response.data)
        self.assertNotIn(b"updated_at", response.data)

    def test_missing_product_returns_404(self):
        self._set_session()
        with self._user_patch(), patch("routes.admin.db.session.get", return_value=None):
            response = self.client.get("/admin/products/999")
        self.assertEqual(response.status_code, 404)

    def test_product_edit_updates_fields_and_leaves_ingredient_rows_untouched(self):
        self._set_session()
        ingredients = [SimpleNamespace(name="soy")]
        product = SimpleNamespace(id=7, ingredients=ingredients)
        with self._user_patch(), patch("routes.admin.db.session.get", return_value=product), patch(
            "routes.admin.db.session.commit"
        ) as commit:
            response = self.client.post(
                "/admin/products/7/edit",
                data={
                    "csrf_token": "valid-token",
                    "name": "  Updated Soy Drink  ",
                    "brand": "",
                    "barcode": "",
                    "ingredients_text": "water, soy",
                    "allergens_text": "soy",
                    "allergens_tags": "[\"en:soybeans\"]",
                    "image_url": "",
                    "source_url": "",
                },
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(product.name, "Updated Soy Drink")
        self.assertIsNone(product.brand)
        self.assertIsNone(product.barcode)
        self.assertIs(product.ingredients, ingredients)
        commit.assert_called_once()

    def test_empty_name_is_rejected(self):
        self._set_session()
        product = SimpleNamespace(id=7, ingredients=[])
        with self._user_patch(), patch("routes.admin.db.session.get", return_value=product), patch(
            "routes.admin.db.session.commit"
        ) as commit:
            response = self.client.post(
                "/admin/products/7/edit",
                data={"csrf_token": "valid-token", "name": "   "},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Tên sản phẩm không được để trống".encode(), response.data)
        commit.assert_not_called()

    def test_product_delete_is_post_only_and_targets_one_product(self):
        self._set_session()
        product = SimpleNamespace(id=7)
        with self._user_patch(), patch("routes.admin.db.session.get", return_value=product), patch(
            "routes.admin.db.session.delete"
        ) as delete, patch("routes.admin.db.session.commit") as commit:
            self.assertEqual(self.client.get("/admin/products/7/delete").status_code, 405)
            response = self.client.post(
                "/admin/products/7/delete", data={"csrf_token": "valid-token"}
            )
        self.assertEqual(response.status_code, 302)
        delete.assert_called_once_with(product)
        commit.assert_called_once()

    def test_admin_post_without_csrf_token_is_rejected(self):
        self._set_session()
        with self._user_patch():
            response = self.client.post("/admin/logout", data={})
        self.assertEqual(response.status_code, 400)


class AdminDatabaseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask

        from extensions import db
        from routes.admin import admin_bp
        from routes.auth import auth_bp
        from routes.history import history_bp
        from routes.main import main_bp
        from routes.product import product_bp
        from routes.profile import profile_bp
        from routes.scan import scan_bp

        cls.db = db
        cls.app = Flask("admin_sqlite_test")
        cls.app.config.update(
            TESTING=True,
            SECRET_KEY="admin-db-tests-only",
            SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)
        for blueprint in (main_bp, auth_bp, scan_bp, profile_bp, product_bp, history_bp, admin_bp):
            cls.app.register_blueprint(blueprint)
        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        from models import Allergen, Product, ProductIngredient, ScanHistory, User, UserAllergen

        self.models = (Allergen, UserAllergen, ScanHistory, ProductIngredient, Product, User)
        with self.app.app_context():
            self.db.drop_all()
            self.db.create_all()

    def test_deleting_product_preserves_scan_snapshot_and_removes_ingredient_rows(self):
        from models import Product, ProductIngredient, ScanHistory, User

        with self.app.app_context():
            user = User(
                email="sqlite-admin@example.test",
                full_name="SQLite Admin",
                hashed_password="not-used",
                is_active=True,
                is_superuser=True,
            )
            product = Product(name="Delete Test Product", barcode="0123456789012")
            self.db.session.add_all([user, product])
            self.db.session.flush()
            ingredient = ProductIngredient(product_id=product.id, name="soy")
            history = ScanHistory(
                scan_id="a" * 32,
                user_id=user.id,
                product_id=product.id,
                product_name=product.name,
                ingredients_json='["soy"]',
                allergens_json='[]',
                warnings_json='[]',
                warning_status="clear",
            )
            self.db.session.add_all([ingredient, history])
            self.db.session.commit()
            product_id = product.id
            user_id = user.id

        client = self.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["admin_csrf_token"] = "sqlite-csrf-token"
        response = client.post(
            f"/admin/products/{product_id}/delete",
            data={"csrf_token": "sqlite-csrf-token"},
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            self.assertIsNone(self.db.session.get(Product, product_id))
            self.assertEqual(ProductIngredient.query.filter_by(product_id=product_id).count(), 0)
            history = ScanHistory.query.filter_by(scan_id="a" * 32).one()
            self.assertIsNone(history.product_id)
            self.assertEqual(history.product_name, "Delete Test Product")

    def test_sqlite_product_search_and_pagination_work_for_name_brand_and_barcode(self):
        from models import Product, User

        with self.app.app_context():
            admin = User(
                email="search-admin@example.test",
                full_name="Search Admin",
                hashed_password="not-used",
                is_active=True,
                is_superuser=True,
            )
            products = [
                Product(name="VinaSoy Special", brand="Local", barcode="111222333"),
                Product(name="Other Drink", brand="BeanHouse", barcode="444555666"),
                Product(name="Barcode Match", brand="Local", barcode="777888999"),
            ]
            products.extend(
                Product(name=f"Bulk Soy {index:02d}", brand="Bulk", barcode=f"900000000{index:02d}")
                for index in range(21)
            )
            self.db.session.add_all([admin, *products])
            self.db.session.commit()
            admin_id = admin.id

        client = self.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = admin_id
            session["admin_csrf_token"] = "sqlite-csrf-token"

        for term, expected in (
            ("vinasoy", "VinaSoy Special"),
            ("beanhouse", "Other Drink"),
            ("777888999", "Barcode Match"),
        ):
            with self.subTest(term=term):
                response = client.get("/admin/products", query_string={"q": term})
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected.encode(), response.data)

        response = client.get("/admin/products?q=bulk&page=2")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Trang 2 / 2", response.data)
        self.assertIn(b"q=bulk", response.data)
if __name__ == "__main__":
    unittest.main()
