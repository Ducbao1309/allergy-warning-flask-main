import unittest
import flask
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from itsdangerous import URLSafeTimedSerializer


class ScanHistoryRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import app

        cls.app = app
        cls.app.config["TESTING"] = True
        cls.app.config["SECRET_KEY"] = "history-tests-only"

    def setUp(self):
        self.client = self.app.test_client()

    def test_history_requires_login(self):
        response = self.client.get("/history/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_history_list_is_scoped_to_signed_in_user(self):
        query = Mock()
        row = SimpleNamespace(
            id=4,
            product_name="Test Noodles",
            brand="Example",
            image_url=None,
            warning_status="warning",
            scanned_at=None,
        )
        pagination = SimpleNamespace(items=[row], pages=1, page=1, has_prev=False, has_next=False)
        query.filter_by.return_value = query
        query.order_by.return_value = query
        query.paginate.return_value = pagination
        history_model = SimpleNamespace(
            query=query,
            scanned_at=Mock(),
            id=Mock(),
        )
        with self.client.session_transaction() as session:
            session["user_id"] = "user-a"
        with patch("routes.history.ScanHistory", history_model):
            response = self.client.get("/history/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test Noodles", response.data)
        query.filter_by.assert_called_once_with(user_id="user-a")

    def test_history_detail_cannot_cross_user_boundary(self):
        query = Mock()
        query.filter_by.return_value = query
        query.first.return_value = None
        history_model = SimpleNamespace(query=query)
        with self.client.session_transaction() as session:
            session["user_id"] = "user-a"
        with patch("routes.history.ScanHistory", history_model):
            response = self.client.get("/history/99")

        self.assertEqual(response.status_code, 404)
        query.filter_by.assert_called_once_with(id=99, user_id="user-a")

    def test_history_detail_reads_saved_snapshot_without_gemini(self):
        query = Mock()
        item = SimpleNamespace(
            id=9,
            product_name="Saved label",
            brand="Example",
            image_url=None,
            warning_status="unknown",
            scanned_at=None,
            ingredients_json='["wheat flour"]',
            allergens_json='["wheat"]',
            warnings_json="[]",
        )
        query.filter_by.return_value.first.return_value = item
        history_model = SimpleNamespace(query=query)
        with self.client.session_transaction() as session:
            session["user_id"] = "user-a"
        with patch("routes.history.ScanHistory", history_model), patch(
            "routes.history.render_template", wraps=flask.render_template
        ) as render:
            response = self.client.get("/history/9")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Saved label", response.data)
        self.assertIn(b"wheat flour", response.data)
        self.assertEqual(render.call_args.kwargs["ingredients"], ["wheat flour"])

    def test_save_product_links_existing_user_scan_history(self):
        from routes.scan import SCAN_SAVE_SALT

        scan_id = uuid.uuid4().hex
        filename = f"history-test-{scan_id}.jpg"
        image_path = Path(self.app.root_path) / "static" / "uploads" / filename
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"test image placeholder")
        serializer = URLSafeTimedSerializer(self.app.secret_key, salt=SCAN_SAVE_SALT)
        token = serializer.dumps({
            "scan_id": scan_id,
            "product_name": "Saved noodles",
            "brand": "Example",
            "ingredients": ["wheat"],
            "allergens": ["wheat"],
            "image_filename": filename,
        })
        product = SimpleNamespace(id=55)
        with self.client.session_transaction() as session:
            session["user_id"] = "user-a"
        try:
            with patch("routes.scan.save_scanned_product", return_value=(product, True)), patch(
                "routes.scan.attach_product_to_scan_history", return_value=True
            ) as attach:
                response = self.client.post("/scan/save-product", data={"save_token": token})
        finally:
            image_path.unlink(missing_ok=True)

        self.assertEqual(response.status_code, 302)
        attach.assert_called_once_with(user_id="user-a", scan_id=scan_id, product_id=55)


if __name__ == "__main__":
    unittest.main()
