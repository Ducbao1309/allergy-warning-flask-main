import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import app


class ProductBarcodeAllergenMatchingTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "product-allergen-tests-only"
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = "test-user"

    def _post_product_check(self, user_tag, product_tags):
        user = SimpleNamespace(id="test-user")
        product = SimpleNamespace(
            allergens_tags=json.dumps(product_tags),
            barcode="123",
            name="Test Food",
            brand="Example",
            ingredients_text="",
        )
        user_query = Mock()
        user_query.filter_by.return_value.first.return_value = user
        product_query = Mock()
        product_query.filter_by.return_value.first.return_value = product
        user_allergen_query = Mock()
        user_allergen_query.filter_by.return_value.all.return_value = [
            SimpleNamespace(
                allergen=SimpleNamespace(name="Tree Nut Allergy", off_tag=user_tag)
            )
        ]
        with patch("routes.product.User", SimpleNamespace(query=user_query)), patch(
            "routes.product.Product", SimpleNamespace(query=product_query)
        ), patch(
            "routes.product.UserAllergen", SimpleNamespace(query=user_allergen_query)
        ):
            return self.client.post("/product/check", data={"barcode": "123"})

    def test_off_leaf_tag_matches_canonical_group_tag(self):
        response = self._post_product_check("en:almond", ["en:tree-nuts"])
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Tree Nut Allergy", response.data)
        self.assertIn(b"c\xc3\xb3 trong d\xe1\xbb\xaf li\xe1\xbb\x87u s\xe1\xba\xa3n ph\xe1\xba\xa9m", response.data)

    def test_peanut_does_not_match_tree_nuts(self):
        response = self._post_product_check("en:peanuts", ["en:tree-nuts"])
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Tree Nut Allergy", response.data)
        self.assertIn(b"lookup-result", response.data)
