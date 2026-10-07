import io
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw, ImageFilter
from services.gemini_service import GeminiServiceError


def _label_image(width=1000, height=1000, blur=0, image_format="JPEG"):
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    step = max(8, min(width, height) // 24)
    for y in range(0, height, step * 2):
        for x in range(0, width, step * 2):
            draw.rectangle((x, y, x + step - 1, y + step - 1), fill="black")
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(radius=blur))
    output = io.BytesIO()
    options = {"quality": 95} if image_format == "JPEG" else {}
    image.save(output, format=image_format, **options)
    return output.getvalue()


class ScanUploadIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import app

        cls.app = app
        cls.app.config["TESTING"] = True
        cls.app.config["SECRET_KEY"] = "image-quality-tests-only"

    def setUp(self):
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = "test-user"
        self.uploaded_paths = []

    def tearDown(self):
        for path in self.uploaded_paths:
            path.unlink(missing_ok=True)

    def test_debug_upload_page_renders_standalone_native_form(self):
        response = self.client.get("/scan/debug-upload")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        form_start = html.index("<form")
        input_position = html.index('name="image"', form_start)
        button_position = html.index("<button", form_start)
        form_end = html.index("</form>", form_start)

        self.assertIn('action="/scan/process"', html)
        self.assertIn('method="POST"', html)
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertLess(form_start, input_position)
        self.assertLess(input_position, form_end)
        self.assertLess(button_position, form_end)
        self.assertNotIn("style.css", html)
        self.assertNotIn("<script", html.lower())

    def test_debug_upload_post_logs_multipart_before_auth_redirect(self):
        client = self.app.test_client()
        gemini = Mock()

        with patch("routes.scan.analyze_product_image", gemini):
            with self.assertLogs("app", level="INFO") as captured:
                response = client.post(
                    "/scan/process",
                    data={"image": (io.BytesIO(b"debug upload"), "test.jpg")},
                    content_type="multipart/form-data",
                )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(any(
            "[SCAN DEBUG] POST /scan/process RECEIVED" in line
            for line in captured.output
        ))
        self.assertTrue(any(
            "[SCAN DEBUG] files=['image']" in line
            for line in captured.output
        ))
        self.assertTrue(any(
            "[SCAN DEBUG] uploaded_file=True" in line
            for line in captured.output
        ))
        gemini.assert_not_called()

    def _post_scan(
        self,
        image_bytes,
        gemini_mock,
        low_level_mocks=True,
        filename="label.jpg",
        follow_redirects=False,
    ):
        upload_id = uuid.uuid4()
        upload_path = Path(self.app.root_path) / "static" / "uploads" / f"{upload_id}{Path(filename).suffix}"
        self.uploaded_paths.append(upload_path)
        patches = [
            patch("routes.scan.uuid.uuid4", return_value=upload_id),
            patch("routes.scan.analyze_product_image", gemini_mock),
            patch(
                "routes.scan.save_scan_history",
                return_value=(SimpleNamespace(id=1), True),
            ),
        ]
        if low_level_mocks:
            user_query = Mock()
            user_query.filter_by.return_value.all.return_value = []
            patches.extend([
                patch("routes.scan.UserAllergen", SimpleNamespace(query=user_query)),
                patch("routes.scan.find_product_by_identity", return_value=None),
                patch("routes.scan.get_product_ingredients", return_value=[]),
                patch("routes.scan.get_product_allergens", return_value=[]),
                patch("routes.scan.check_product_ingredients", return_value=[]),
                patch("routes.scan.has_unsupported_allergen_tags", return_value=False),
            ])

        with self.app.app_context(), ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            response = self.client.post(
                "/scan/process",
                data={"image": (io.BytesIO(image_bytes), filename)},
                content_type="multipart/form-data",
                follow_redirects=follow_redirects,
            )
        return response, gemini_mock

    def test_native_multipart_upload_renders_result_with_mocked_gemini(self):
        gemini = Mock(return_value={
            "product_name": "Test product",
            "brand": "Test brand",
            "ingredients": ["water"],
            "allergens": [],
        })
        response, analyze = self._post_scan(_label_image(), gemini)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test product", response.data)
        analyze.assert_called_once()
        self.assertTrue(Path(analyze.call_args.args[0]).is_file())

    def test_small_valid_image_reaches_mocked_gemini(self):
        gemini = Mock(return_value={
            "product_name": "Small label",
            "brand": "Test brand",
            "ingredients": ["salt"],
            "allergens": [],
        })
        response, analyze = self._post_scan(_label_image(100, 100), gemini)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Small label", response.data)
        analyze.assert_called_once()
    def test_800_by_450_image_reaches_mocked_gemini(self):
        gemini = Mock(return_value={
            "product_name": "Landscape label",
            "brand": "Test brand",
            "ingredients": ["water"],
            "allergens": [],
        })
        response, analyze = self._post_scan(_label_image(800, 450), gemini)
        self.assertEqual(response.status_code, 200)
        analyze.assert_called_once()

    def test_png_and_webp_uploads_reach_mocked_gemini(self):
        for image_format, extension in (("PNG", "png"), ("WEBP", "webp")):
            with self.subTest(image_format=image_format):
                gemini = Mock(return_value={
                    "product_name": f"{image_format} label",
                    "brand": "Test brand",
                    "ingredients": ["water"],
                    "allergens": [],
                })
                response, analyze = self._post_scan(
                    _label_image(image_format=image_format),
                    gemini,
                    filename=f"label.{extension}",
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(f"{image_format} label".encode(), response.data)
                analyze.assert_called_once()

    def test_upload_form_posts_multipart_image_to_scan_process(self):
        response = self.client.get("/scan/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'action="/scan/process"', response.data)
        self.assertIn(b'enctype="multipart/form-data"', response.data)
        self.assertIn(b'name="image"', response.data)

    def test_missing_upload_field_returns_to_scan_without_calling_gemini(self):
        gemini = Mock()
        with patch("routes.scan.analyze_product_image", gemini):
            response = self.client.post("/scan/process", data={}, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Vui lòng chọn ảnh".encode("utf-8"), response.data)
        gemini.assert_not_called()

    def test_full_mocked_upload_flow_renders_allergy_result(self):
        upload_id = uuid.uuid4()
        upload_path = Path(self.app.root_path) / "static" / "uploads" / f"{upload_id}.jpg"
        self.uploaded_paths.append(upload_path)
        gemini = Mock(return_value={
            "product_name": "Test Noodle",
            "brand": "Test Brand",
            "ingredients": ["wheat flour", "salt"],
            "allergens": ["wheat"],
        })
        user_query = Mock()
        user_query.filter_by.return_value.all.return_value = [
            SimpleNamespace(allergen=SimpleNamespace(off_tag="en:wheat"))
        ]
        product_lookup = Mock(return_value=None)
        ingredient_lookup = Mock(return_value=[])
        allergen_lookup = Mock(return_value=[])
        with self.app.app_context(), ExitStack() as stack:
            stack.enter_context(patch("routes.scan.uuid.uuid4", return_value=upload_id))
            stack.enter_context(patch("routes.scan.analyze_product_image", gemini))
            stack.enter_context(patch(
                "routes.scan.save_scan_history",
                return_value=(SimpleNamespace(id=1), True),
            ))
            stack.enter_context(patch(
                "routes.scan.UserAllergen",
                SimpleNamespace(query=user_query),
            ))
            stack.enter_context(patch(
                "routes.scan.find_product_by_identity",
                product_lookup,
            ))
            stack.enter_context(patch(
                "routes.scan.get_product_ingredients",
                ingredient_lookup,
            ))
            stack.enter_context(patch(
                "routes.scan.get_product_allergens",
                allergen_lookup,
            ))
            stack.enter_context(patch(
                "routes.scan.has_unsupported_allergen_tags",
                return_value=False,
            ))
            response = self.client.post(
                "/scan/process",
                data={"image": (io.BytesIO(_label_image(800, 450)), "label.jpg")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test Noodle", response.data)
        self.assertIn(b"wheat flour", response.data)
        self.assertIn(b"allergen-item", response.data)
        gemini.assert_called_once()
        gemini_image_path = Path(gemini.call_args.args[0])
        self.assertEqual(gemini_image_path, upload_path)
        self.assertTrue(gemini_image_path.is_file())
        with Image.open(gemini_image_path) as uploaded_image:
            self.assertEqual(uploaded_image.format, "JPEG")
        product_lookup.assert_called_once_with("Test Noodle", "Test Brand")
        ingredient_lookup.assert_called_once_with(None)
        allergen_lookup.assert_called_once_with(None)
        user_query.filter_by.assert_called_once_with(user_id="test-user")

    def test_blurry_valid_image_reaches_mocked_gemini(self):
        gemini = Mock(return_value={
            "product_name": "Blurred label",
            "brand": "Test brand",
            "ingredients": ["salt"],
            "allergens": [],
        })
        response, analyze = self._post_scan(
            _label_image(300, 500, blur=40),
            gemini,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Blurred label", response.data)
        analyze.assert_called_once()

    def test_gemini_error_shows_message_and_returns_to_scan(self):
        gemini = Mock(side_effect=GeminiServiceError("mock timeout"))
        response, analyze = self._post_scan(
            _label_image(100, 100),
            gemini,
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Gemini bị quá thời gian chờ".encode("utf-8"), response.data)
        analyze.assert_called_once()

    def test_unsupported_extension_is_rejected_before_gemini(self):
        gemini = Mock()
        response, analyze = self._post_scan(
            b"not an image",
            gemini,
            low_level_mocks=False,
            filename="label.gif",
        )
        self.assertEqual(response.status_code, 302)
        analyze.assert_not_called()
if __name__ == "__main__":
    unittest.main()
