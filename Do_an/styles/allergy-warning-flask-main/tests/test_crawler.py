import unittest
from unittest.mock import Mock, patch

import requests
from flask import Flask

from extensions import db


def page(products, errors=None, page_fetched=True, requests_made=1):
    return {
        "products": products,
        "errors": errors or [],
        "page_fetched": page_fetched,
        "requests_made": requests_made,
    }


def product(code, name=None, **extra):
    return {"code": code, "product_name": name or f"Product {code}", **extra}


class OpenFoodFactsFetchTests(unittest.TestCase):
    def test_fetch_uses_existing_api_filter_fields_and_requested_page(self):
        from crawler.openfoodfacts_crawler import API_URL, HEADERS, fetch_products

        response = Mock()
        response.json.return_value = {"products": [{"code": "a"}, {"code": "b"}]}
        with patch("crawler.openfoodfacts_crawler.requests.get", return_value=response) as get:
            result = fetch_products(page=3, page_size=2)

        self.assertEqual(result["products"], [{"code": "a"}, {"code": "b"}])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["requests_made"], 1)
        self.assertEqual(get.call_args.args[0], API_URL)
        self.assertEqual(get.call_args.kwargs["params"]["page"], 3)
        self.assertEqual(get.call_args.kwargs["params"]["page_size"], 2)
        self.assertEqual(get.call_args.kwargs["params"]["countries_tags"], "en:vietnam")
        fields = get.call_args.kwargs["params"]["fields"]
        for field in ("code", "product_name", "brands", "ingredients_text", "allergens", "allergens_tags", "image_url", "url", "ingredients"):
            self.assertIn(field, fields)
        self.assertEqual(get.call_args.kwargs["headers"]["User-Agent"], HEADERS["User-Agent"])
        self.assertEqual(get.call_args.kwargs["timeout"], 30)

    def test_fetch_reports_api_invalid_json_and_unexpected_shape(self):
        from crawler.openfoodfacts_crawler import fetch_products

        with patch("crawler.openfoodfacts_crawler.requests.get", side_effect=requests.Timeout("offline")):
            failed = fetch_products(1, 2)
        self.assertEqual(failed["products"], [])
        self.assertFalse(failed["page_fetched"])
        self.assertEqual(failed["requests_made"], 1)
        self.assertEqual(len(failed["errors"]), 1)

        response = Mock()
        response.json.side_effect = ValueError("bad json")
        with patch("crawler.openfoodfacts_crawler.requests.get", return_value=response):
            invalid = fetch_products(1, 2)
        self.assertFalse(invalid["page_fetched"])
        self.assertEqual(len(invalid["errors"]), 1)

        response.json.side_effect = None
        response.json.return_value = {"products": "not-a-list"}
        with patch("crawler.openfoodfacts_crawler.requests.get", return_value=response):
            malformed = fetch_products(1, 2)
        self.assertFalse(malformed["page_fetched"])
        self.assertEqual(len(malformed["errors"]), 1)

    def test_fetch_retries_retryable_http_once(self):
        from crawler.openfoodfacts_crawler import fetch_products

        unavailable = requests.Response()
        unavailable.status_code = 503
        error = requests.HTTPError("503 Service Unavailable", response=unavailable)
        success = Mock()
        success.json.return_value = {"products": [{"code": "a"}]}
        with patch(
            "crawler.openfoodfacts_crawler.requests.get",
            side_effect=[Mock(raise_for_status=Mock(side_effect=error)), success],
        ) as get, patch("crawler.openfoodfacts_crawler.time.sleep"):
            result = fetch_products(1, 2)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(result["requests_made"], 2)
        self.assertEqual(result["products"], [{"code": "a"}])
        self.assertEqual(result["errors"], [])

    def test_fetch_rejects_page_and_page_size_outside_bounds(self):
        from crawler.openfoodfacts_crawler import fetch_products

        for args in ((0, 1), (11, 1), (True, 1), (1, 0), (1, 51), (1, True)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                fetch_products(*args)

    def test_database_error_detail_redacts_credentials(self):
        from crawler.openfoodfacts_crawler import _safe_database_error_detail

        detail = _safe_database_error_detail(
            RuntimeError("password=hunter2 api_key=key123 https://user:pass@db")
        )
        self.assertNotIn("hunter2", detail)
        self.assertNotIn("key123", detail)
        self.assertNotIn("user:pass", detail)
        self.assertIn("[redacted]", detail)


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

    def seed_existing(self, codes):
        from models import Product
        for code in codes:
            db.session.add(Product(barcode=code, name=f"Existing {code}"))
        db.session.commit()

    def run_with_pages(self, requested, pages, page_size=3, max_pages=10):
        from crawler.openfoodfacts_crawler import run_crawler
        def fetch(page, page_size):
            return pages.get(page, globals()["page"]([]))
        with self.app.app_context(), patch("crawler.openfoodfacts_crawler.PAGE_SIZE", page_size), patch(
            "crawler.openfoodfacts_crawler.MAX_CRAWL_PAGES", max_pages
        ), patch("crawler.openfoodfacts_crawler.fetch_products", side_effect=fetch) as fetch_mock, patch(
            "crawler.openfoodfacts_crawler.time.sleep"
        ):
            result = run_crawler(requested)
        return result, fetch_mock

    def test_target_means_new_insertions_and_stops_mid_page(self):
        from models import Product
        with self.app.app_context():
            result, fetch_mock = self.run_with_pages(5, {
                1: page([product("n1"), product("n2"), product("n3")]),
                2: page([product("n4"), product("n5"), product("unused")]),
            })
            self.assertEqual(Product.query.count(), 5)
        self.assertEqual(result["requested_count"], 5)
        self.assertEqual(result["inserted_count"], 5)
        self.assertEqual(result["fetched_count"], 6)
        self.assertEqual(result["status"], "success")
        self.assertEqual(fetch_mock.call_count, 2)
        self.assertLessEqual(result["inserted_count"], result["requested_count"])

    def test_all_duplicates_on_first_page_continues_to_page_with_new_products(self):
        with self.app.app_context():
            self.seed_existing(["d1", "d2", "d3"])
            result, fetch_mock = self.run_with_pages(2, {
                1: page([product("d1"), product("d2"), product("d3")]),
                2: page([product("new1"), product("new2"), product("new3")]),
            })
        self.assertEqual(result["duplicate_count"], 3)
        self.assertEqual(result["inserted_count"], 2)
        self.assertEqual(result["status"], "success")
        self.assertEqual(fetch_mock.call_count, 2)

    def test_duplicates_over_multiple_pages_do_not_stop_pagination(self):
        with self.app.app_context():
            self.seed_existing([f"d{i}" for i in range(6)])
            result, fetch_mock = self.run_with_pages(1, {
                1: page([product("d0"), product("d1"), product("d2")]),
                2: page([product("d3"), product("d4"), product("d5")]),
                3: page([product("new")]),
            })
        self.assertEqual(result["duplicate_count"], 6)
        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(result["pages_fetched"], 3)
        self.assertEqual(fetch_mock.call_count, 3)

    def test_missing_barcode_and_invalid_product_do_not_prevent_later_insert(self):
        with self.app.app_context():
            result, fetch_mock = self.run_with_pages(1, {
                1: page([{"product_name": "No barcode"}, {"code": "bad", "product_name": ""}, {"code": "bad-tags", "product_name": "Bad tags", "allergens_tags": "not-a-list"}]),
                2: page([product("later"), product("more"), product("more2")]),
            })
        self.assertEqual(result["error_count"], 3)
        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(fetch_mock.call_count, 2)

    def test_validation_errors_identify_missing_and_invalid_fields(self):
        with self.app.app_context():
            result, _ = self.run_with_pages(1, {
                1: page([
                    {"product_name": "Name without barcode"},
                    {"code": "no-name", "product_name": "   "},
                    {"product_name": "   "},
                    {"code": [], "product_name": "Invalid barcode"},
                ]),
            })
        self.assertEqual(result["error_count"], 4)
        self.assertEqual(result["errors"], [
            "Product 1: missing barcode",
            "Product 2: missing product name",
            "Product 3: missing barcode and product name",
            "Product 4: invalid barcode: must be text or an integer",
        ])

    def test_short_page_exhaustion_returns_partial_or_error(self):
        with self.app.app_context():
            partial, _ = self.run_with_pages(4, {1: page([product("one"), product("two")])})
            none, _ = self.run_with_pages(2, {1: page([{"product_name": "No barcode"}])})
        self.assertEqual(partial["inserted_count"], 2)
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(none["inserted_count"], 0)
        self.assertEqual(none["status"], "error")

    def test_duplicate_only_exhaustion_reports_no_new_products(self):
        with self.app.app_context():
            self.seed_existing(["dup1", "dup2"])
            result, fetch_mock = self.run_with_pages(1, {
                1: page([product("dup1"), product("dup2")]),
            })
        self.assertEqual(result["duplicate_count"], 2)
        self.assertEqual(result["inserted_count"], 0)
        self.assertEqual(result["status"], "no_new")
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["errors"], [])
        self.assertEqual(fetch_mock.call_count, 1)
    def test_api_error_after_prior_page_keeps_committed_products(self):
        from models import Product
        with self.app.app_context():
            result, fetch_mock = self.run_with_pages(4, {
                1: page([product("saved1"), product("saved2"), product("saved3")]),
                2: page([], errors=["HTTP 503"], page_fetched=False, requests_made=2),
            })
            self.assertEqual(Product.query.count(), 3)
        self.assertEqual(result["inserted_count"], 3)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["requests_made"], 3)
        self.assertEqual(fetch_mock.call_count, 2)

    def test_database_error_does_not_prevent_later_insertions(self):
        from crawler.openfoodfacts_crawler import save_product, run_crawler
        from models import Product
        from sqlalchemy.exc import SQLAlchemyError
        def fail_first(data):
            if data["code"] == "db-error":
                raise SQLAlchemyError("simulated database failure")
            return save_product(data)
        with self.app.app_context(), patch("crawler.openfoodfacts_crawler.PAGE_SIZE", 3), patch(
            "crawler.openfoodfacts_crawler.fetch_products",
            return_value=page([product("db-error"), product("good")]),
        ), patch("crawler.openfoodfacts_crawler.save_product", side_effect=fail_first), patch(
            "crawler.openfoodfacts_crawler.time.sleep"
        ):
            result = run_crawler(1)
            saved = Product.query.filter_by(barcode="good").one_or_none()
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["inserted_count"], 1)
        self.assertIn(
            "Product 1: database error: simulated database failure",
            result["errors"],
        )
        self.assertIsNotNone(saved)

    def test_safe_page_cap_is_enforced_and_inserted_never_exceeds_requested(self):
        from crawler.openfoodfacts_crawler import MAX_CRAWL_PRODUCTS
        pages = {
            1: page([product("cap1"), product("cap2")]),
            2: page([product("cap3"), product("cap4")]),
            3: page([product("cap5"), product("cap6")]),
        }
        with self.app.app_context():
            result, fetch_mock = self.run_with_pages(MAX_CRAWL_PRODUCTS, pages, page_size=2, max_pages=2)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(fetch_mock.call_count, 2)
        self.assertEqual(result["inserted_count"], 4)
        self.assertLessEqual(result["inserted_count"], result["requested_count"])
        self.assertIn("safe limit", result["warnings"][-1])
        self.assertEqual(result["status"], "partial")

    def test_run_crawler_validates_requested_count(self):
        from crawler.openfoodfacts_crawler import run_crawler
        for value in (0, -1, 101, "10", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_crawler(value)
