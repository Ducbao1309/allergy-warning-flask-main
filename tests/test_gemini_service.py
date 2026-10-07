import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from services.gemini_service import (
    GEMINI_MODEL,
    REQUEST_TIMEOUT_SECONDS,
    GeminiServiceError,
    analyze_product_image,
)


class GeminiImageRequestTests(unittest.TestCase):
    def _write_image(self, path, image_format):
        image = Image.new("RGB", (100, 60), color=(240, 200, 40))
        image.save(path, format=image_format)
        return Path(path)

    def test_supported_upload_formats_are_sent_to_mocked_gemini(self):
        response_json = json.dumps({
            "product_name": "Test noodles",
            "brand": "Test brand",
            "ingredients": ["wheat flour", "salt"],
            "allergens": ["wheat"],
        })
        for image_format, extension in (
            ("JPEG", ".jpg"),
            ("PNG", ".png"),
            ("WEBP", ".webp"),
        ):
            with self.subTest(image_format=image_format), tempfile.TemporaryDirectory() as folder:
                image_path = self._write_image(Path(folder) / f"label{extension}", image_format)
                client = Mock()
                client.interactions.create.return_value = SimpleNamespace(
                    output_text=response_json
                )
                with patch.dict(os.environ, {"GEMINI_API_KEY": "unit-test-key"}), patch(
                    "services.gemini_service.genai.Client",
                    return_value=client,
                ) as client_factory:
                    result = analyze_product_image(image_path)

                self.assertEqual(result["product_name"], "Test noodles")
                self.assertEqual(result["ingredients"], ["wheat flour", "salt"])
                self.assertEqual(result["allergens"], ["wheat"])
                client_factory.assert_called_once()
                options = client_factory.call_args.kwargs["http_options"]
                self.assertEqual(options.timeout, REQUEST_TIMEOUT_SECONDS * 1000)
                self.assertEqual(options.retry_options.attempts, 1)

                request = client.interactions.create.call_args.kwargs
                self.assertEqual(request["model"], GEMINI_MODEL)
                self.assertEqual(request["response_format"]["mime_type"], "application/json")
                image_part = next(item for item in request["input"] if item["type"] == "image")
                self.assertEqual(image_part["mime_type"], "image/jpeg")
                decoded_image = base64.b64decode(image_part["data"])
                with Image.open(io.BytesIO(decoded_image)) as sent_image:
                    self.assertEqual(sent_image.format, "JPEG")

    def test_request_timeout_is_reported_without_swallowing_exception(self):
        with tempfile.TemporaryDirectory() as folder:
            image_path = self._write_image(Path(folder) / "label.jpg", "JPEG")
            client = Mock()
            client.interactions.create.side_effect = [
                TimeoutError("mock request timeout") for _ in range(3)
            ]
            with patch.dict(os.environ, {"GEMINI_API_KEY": "unit-test-key"}), patch(
                "services.gemini_service.genai.Client",
                return_value=client,
            ), patch("services.gemini_service.time.sleep") as sleep:
                with self.assertLogs("services.gemini_service", level="ERROR") as captured:
                    with self.assertRaises(GeminiServiceError) as raised:
                        analyze_product_image(image_path)

            self.assertIsInstance(raised.exception.__cause__, TimeoutError)
            self.assertIn("Gemini request failed after", captured.output[0])
            self.assertEqual(client.interactions.create.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_429_retries_twice_logs_safe_error_details_and_returns_clear_error(self):
        error_body = {
            "error": {
                "code": "rate_limit_exceeded",
                "message": "Requests per minute limit exceeded.",
            }
        }
        api_error = RuntimeError("429 Too Many Requests")
        api_error.status_code = 429
        api_error.response = SimpleNamespace(
            status_code=429,
            headers={
                "Retry-After": "2",
                "Authorization": "Bearer unit-test-key",
                "X-Goog-Api-Key": "unit-test-key",
                "X-Api-Key": "unit-test-key",
                "X-Request-Id": "request-123",
            },
            text=json.dumps(error_body),
        )

        with tempfile.TemporaryDirectory() as folder:
            image_path = self._write_image(Path(folder) / "label.jpg", "JPEG")
            client = Mock()
            client.interactions.create.side_effect = [api_error, api_error, api_error]
            with patch.dict(os.environ, {"GEMINI_API_KEY": "unit-test-key"}), patch(
                "services.gemini_service.genai.Client",
                return_value=client,
            ), patch("services.gemini_service.time.sleep") as sleep:
                with self.assertLogs("services.gemini_service", level="ERROR") as captured:
                    with self.assertRaisesRegex(
                        GeminiServiceError,
                        "Gemini API đang giới hạn request/quota",
                    ) as raised:
                        analyze_product_image(image_path)

        self.assertIs(raised.exception.__cause__, api_error)
        self.assertEqual(client.interactions.create.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(sleep.call_args_list[0].args, (2.0,))
        self.assertEqual(sleep.call_args_list[1].args, (2.0,))
        logged = "\n".join(captured.output)
        self.assertIn("status=429", logged)
        self.assertIn("code=rate_limit_exceeded", logged)
        self.assertIn("Requests per minute limit exceeded.", logged)
        self.assertIn("retry_after=2", logged)
        self.assertIn("X-Request-Id", logged)
        self.assertNotIn("unit-test-key", logged)


if __name__ == "__main__":
    unittest.main()
