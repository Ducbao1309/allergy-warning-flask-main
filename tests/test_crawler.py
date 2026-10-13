import unittest
from unittest.mock import Mock, patch

import requests
from flask import Flask

from extensions import db


class OpenFoodFactsFetchTests(unittest.TestCase):
    def test_fetch_uses_existing_api_filter_and_requested_page_size(self):
        from crawler.openfoodfacts_crawler import API_URL, HEADERS, fetch_products

        response = Mock()
        response.json.return_value = {"products": [{"code": str(i)} for i in range(10)]}
        with patch("crawler.openfoodfacts_crawler.requests.get", return_value=response) as get:
            result = fetch_products(10)

        self.assertEqual(len(result["products"]), 10)
        self.assertEqual(result["errors"], [])
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.args[0], API_URL)
        self.assertEqual(get.call_args.kwargs["headers"]["User-Agent"], HEADERS["User-Agent"])
        self.assertEqual(
            HEADERS["User-Agent"], "AllergyWarning/1.0 (educational project)"
        )
        self.assertEqual(get.call_args.kwargs["timeout"], 30)
        self.assertEqual(get.call_args.kwargs["params"]["page_size"], 10)
        self.assertEqual(get.call_args.kwargs["params"]["page"], 1)
        self.assertEqual(get.call_args.kwargs["params"]["countries_tags"], "en:vietnam")
        self.assertIn("ingredients", get.call_args.kwargs["params"]["fields"])

    def test_fetch_paginates_only_as_far_as_requested_limit(self):
        from crawler.openfoodfacts_crawler import fetch_products

        responses = []
        for page in range(2):
            response = Mock()
            response.json.return_value = {
                "products": [{"code": f"{page}-{i}"} for i in range(50)]
            }
            responses.append(response)
        with patch("crawler.openfoodfacts_crawler.requests.get", side_effect=responses) as get, patch(
            "crawler.openfoodfacts_crawler.time.sleep"
        ):
            result = fetch_products(100)

        self.assertEqual(len(result["products"]), 100)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(
            [call.kwargs["params"]["page"] for call in get.call_args_list],
            [1, 2],
        )

    def test_fetch_reports_api_and_invalid_json_errors_without_raising(self):
        from crawler.openfoodfacts_crawler import fetch_products

        with patch(
            "crawler.openfoodfacts_crawler.requests.get",
            side_effect=requests.Timeout("offline"),
        ):
            failed_request = fetch_products(10)
        self.assertEqual(failed_request["products"], [])
        self.assertEqual(len(failed_request["errors"]), 1)

        with patch(
            "crawler.openfoodfacts_crawler.requests.get",
            side_effect=requests.ConnectionError("offline"),
        ):
            failed_connection = fetch_products(10)
        self.assertEqual(failed_connection["products"], [])
        self.assertEqual(len(failed_connection["errors"]), 1)

        response = Mock()
        response.json.side_effect = ValueError("bad json")
        with patch("crawler.openfoodfacts_crawler.requests.get", return_value=response):
            invalid_json = fetch_products(10)
        self.assertEqual(invalid_json["products"], [])
        self.assertEqual(len(invalid_json["errors"]), 1)

        response.json.side_effect = None
        response.json.return_value = {"products": "not-a-list"}
        with patch("crawler.openfoodfacts_crawler.requests.get", return_value=response):
            unexpected_shape = fetch_products(10)
        self.assertEqual(unexpected_shape["products"], [])
        self.assertEqual(len(unexpected_shape["errors"]), 1)

    def test_fetch_retries_http_503_once_then_succeeds_or_reports_status(self):
        from crawler.openfoodfacts_crawler import fetch_products

        unavailable = requests.Response()
        unavailable.status_code = 503
        error = requests.HTTPError("503 Service Unavailable", response=unavailable)
        success = Mock()
        success.ok = True
        success.json.return_value = {"products": [{"code": "one"}]}

        with patch(
            "crawler.openfoodfacts_crawler.requests.get",
            side_effect=[Mock(raise_for_status=Mock(side_effect=error)), success],
        ) as get, patch("crawler.openfoodfacts_crawler.time.sleep"):
            recovered = fetch_products(1)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(recovered["products"], [{"code": "one"}])
        self.assertEqual(recovered["errors"], [])

        with patch(
            "crawler.openfoodfacts_crawler.requests.get",
            return_value=Mock(raise_for_status=Mock(side_effect=error)),
        ) as get, patch("crawler.openfoodfacts_crawler.time.sleep"):
            still_unavailable = fetch_products(1)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(still_unavailable["products"], [])
        self.assertEqual(len(still_unavailable["errors"]), 1)
        self.assertIn("HTTP 503", still_unavailable["errors"][0])

    def test_fetch_rejects_limits_outside_supported_range(self):
        from crawler.openfoodfacts_crawler import fetch_products

        for value in (0, -1, 101, "10", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fetch_products(value)


class CrawlerPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask("crawler_test")
        cls.app.config.update(
            TESTING=True,
            SECRET_KEY="crawler-tests-only",
            SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)

    def setUp(self):
        from models import Allergen, Product, ProductIngredient, ScanHistory, User, UserAllergen

        self.models = (Allergen, Product, ProductIngredient, ScanHistory, User, UserAllergen)
        with self.app.app_context():
            db.drop_all()
            db.create_all()

    def test_run_crawler_inserts_products_and_ingredients_and_counts_duplicates_errors(self):
        from crawler.openfoodfacts_crawler import run_crawler
        from models import Product, ProductIngredient

        fetched = {
            "products": [
                {
                    "code": "000111",
                    "product_name": "First Product",
                    "brands": "Example",
                    "ingredients_text": "water, soy",
                    "allergens": "soy",
                    "allergens_tags": ["en:soybeans"],
                    "ingredients": [{"text": "water", "id": "en:water"}],
                    "image_url": "https://example.test/image.jpg",
                    "url": "https://example.test/product",
                },
                {
                    "code": "000111",
                    "product_name": "Duplicate Product",
                    "brands": "Example",
                },
                {"code": "bad", "product_name": "", "brands": "Example"},
                {
                    "code": "000333",
                    "product_name": "Third Product",
                    "brands": "Other",
                    "ingredients": [{"text": "oats", "id": "en:oats"}],
                },
            ],
            "errors": [],
        }
        with self.app.app_context(), patch(
            "crawler.openfoodfacts_crawler.fetch_products", return_value=fetched
        ):
            result = run_crawler(4)
            products = Product.query.order_by(Product.barcode).all()
            ingredients = ProductIngredient.query.order_by(ProductIngredient.name).all()

        self.assertEqual(result["requested_count"], 4)
        self.assertEqual(result["fetched_count"], 4)
        self.assertEqual(result["inserted_count"], 2)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["status"], "partial")
        self.assertEqual([product.name for product in products], ["First Product", "Third Product"])
        self.assertEqual(len(ingredients), 2)
        self.assertEqual(products[0].ingredients_text, "water, soy")
        self.assertEqual(products[0].allergens_tags, '["en:soybeans"]')

    def test_duplicate_does_not_replace_existing_product_or_ingredients(self):
        from crawler.openfoodfacts_crawler import run_crawler
        from models import Product, ProductIngredient

        with self.app.app_context():
            product = Product(
                barcode="same-code",
                name="Original Name",
                brand="Original Brand",
                ingredients_text="original ingredients",
            )
            db.session.add(product)
            db.session.flush()
            db.session.add(ProductIngredient(product_id=product.id, name="original"))
            db.session.commit()

            fetched = {
                "products": [{
                    "code": "same-code",
                    "product_name": "Replacement Name",
                    "brands": "Replacement Brand",
                    "ingredients": [{"text": "replacement"}],
                }],
                "errors": [],
            }
            with patch("crawler.openfoodfacts_crawler.fetch_products", return_value=fetched):
                result = run_crawler(1)

            saved = Product.query.filter_by(barcode="same-code").one()
            ingredient_names = [row.name for row in saved.ingredients]

        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(result["inserted_count"], 0)
        self.assertEqual(saved.name, "Original Name")
        self.assertEqual(saved.ingredients_text, "original ingredients")
        self.assertEqual(ingredient_names, ["original"])

    def test_product_without_barcode_is_rejected(self):
        from crawler.openfoodfacts_crawler import run_crawler
        from models import Product

        with self.app.app_context():
            fetched = {
                "products": [{
                    "product_name": "No Barcode Product",
                    "brands": "Example",
                }],
                "errors": [],
            }
            with patch("crawler.openfoodfacts_crawler.fetch_products", return_value=fetched):
                result = run_crawler(1)

            self.assertEqual(Product.query.count(), 0)

        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["inserted_count"], 0)

    def test_database_error_is_counted_and_later_product_still_inserts(self):
        from crawler.openfoodfacts_crawler import run_crawler, save_product
        from models import Product
        from sqlalchemy.exc import SQLAlchemyError

        fetched = {
            "products": [
                {"code": "db-error", "product_name": "Fails"},
                {"code": "good-code", "product_name": "Still Saved"},
            ],
            "errors": [],
        }

        def fail_first_product(product_data):
            if product_data["code"] == "db-error":
                raise SQLAlchemyError("simulated database failure")
            return save_product(product_data)

        with self.app.app_context(), patch(
            "crawler.openfoodfacts_crawler.fetch_products", return_value=fetched
        ), patch(
            "crawler.openfoodfacts_crawler.save_product",
            side_effect=fail_first_product,
        ):
            result = run_crawler(2)
            saved = Product.query.filter_by(barcode="good-code").one_or_none()

        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["inserted_count"], 1)
        self.assertIsNotNone(saved)

    def test_run_crawler_validates_requested_count(self):
        from crawler.openfoodfacts_crawler import run_crawler

        for value in (0, -1, 101, "10", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_crawler(value)
