import unittest

from services.product_service import (
    check_product_ingredients,
    has_unsupported_allergen_tags,
    ingredient_matches_allergen,
    normalize_allergen_tag,
    normalize_allergen_tags,
    should_mark_allergen_result_unknown,
)


class AllergenNormalizationTests(unittest.TestCase):
    def test_vietnamese_fish_soy_and_tree_nut_aliases_map_to_existing_ids(self):
        aliases = {
            "C\u00e1 tr\u00edch": "FISH",
            "ca trich": "FISH",
            "C\u00e1 h\u1ed3i": "FISH",
            "\u0110\u1eadu n\u00e0nh": "SOY",
            "dau nanh": "SOY",
            "D\u1ea7u \u0111\u1eadu n\u00e0nh tinh luy\u1ec7n": "SOY",
            "H\u1ea1t h\u1ea1nh nh\u00e2n": "TREE_NUTS",
            "H\u1ea1t \u0111i\u1ec1u": "TREE_NUTS",
            "H\u1ea1t ph\u1ec9": "TREE_NUTS",
        }
        for value, expected in aliases.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_allergen_tag(value), expected)

    def test_vietnamese_ingredient_phrases_match_without_substring_false_positives(self):
        self.assertTrue(ingredient_matches_allergen(
            "C\u00e1 tr\u00edch 52% kh\u1ed1i l\u01b0\u1ee3ng", "FISH"
        ))
        self.assertTrue(ingredient_matches_allergen(
            "D\u1ea7u \u0111\u1eadu n\u00e0nh tinh luy\u1ec7n 4,5% kh\u1ed1i l\u01b0\u1ee3ng",
            "SOY",
        ))
        self.assertFalse(ingredient_matches_allergen("misc\u00e1blend", "FISH"))

    def test_vietnamese_product_match_wins_over_unsupported_ingredient(self):
        ingredients = [
            "C\u00e1 tr\u00edch 52% kh\u1ed1i l\u01b0\u1ee3ng",
            "N\u01b0\u1edbc s\u1ed1t",
            "D\u1ea7u \u0111\u1eadu n\u00e0nh tinh luy\u1ec7n 4,5% kh\u1ed1i l\u01b0\u1ee3ng",
            "m\u1ed9t ch\u1ea5t ph\u1ee5 gia ch\u01b0a map",
        ]
        matches = check_product_ingredients(ingredients, ["FISH", "SOY"])
        self.assertEqual({item["tag"] for item in matches}, {"FISH", "SOY"})
        self.assertFalse(should_mark_allergen_result_unknown(
            ["FISH", "SOY"], product_ingredients=ingredients, matches=matches
        ))

    def test_english_almond_flour_and_soybean_oil_phrase_regressions(self):
        self.assertTrue(ingredient_matches_allergen("Almond flour", "TREE_NUTS"))
        self.assertTrue(ingredient_matches_allergen("Soybean oil", "SOY"))

    def test_tree_nut_profile_and_english_and_off_aliases_share_canonical_id(self):
        values = (
            "H\u1ea1t c\u00e2y",
            "en:nuts",
            "en:tree-nuts",
            "en:almond",
            "almond",
            "almonds",
            "h\u1ea1t h\u1ea1nh nh\u00e2n",
            "en:cashew",
            "cashew",
            "cashews",
            "h\u1ea1t \u0111i\u1ec1u",
            "walnut",
            "qu\u1ea3 \u00f3c ch\u00f3",
            "hazelnuts",
            "h\u1ea1t ph\u1ec9",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(normalize_allergen_tag(value), "TREE_NUTS")

    def test_off_sesame_and_sulphite_leaf_tags_map_to_canonical_ids(self):
        self.assertEqual(normalize_allergen_tag("M\u00e8"), "SESAME")
        self.assertIsNone(normalize_allergen_tag("me"))
        self.assertEqual(normalize_allergen_tag("en:sesame-seeds"), "SESAME")
        self.assertEqual(normalize_allergen_tag("Sulfit"), "SULPHITES")
        self.assertEqual(
            normalize_allergen_tag("en:sulphur-dioxide-and-sulphites"),
            "SULPHITES",
        )
        sesame_match = check_product_ingredients(
            [], ["M\u00e8"], ["en:sesame-seeds"]
        )
        sulphite_match = check_product_ingredients(
            [], ["Sulfit"], ["en:sulphur-dioxide-and-sulphites"]
        )
        self.assertEqual([item["tag"] for item in sesame_match], ["SESAME"])
        self.assertEqual([item["tag"] for item in sulphite_match], ["SULPHITES"])
        self.assertEqual(
            [item["tag"] for item in check_product_ingredients(["m\u00e8 rang"], ["M\u00e8"])],
            ["SESAME"],
        )

    def test_peanut_and_milk_vietnamese_profile_labels_match_english_ingredients(self):
        peanut = check_product_ingredients(["peanut"], ["\u0110\u1eadu ph\u1ed9ng"])
        milk = check_product_ingredients(["milk"], ["S\u1eefa"])
        self.assertEqual([item["tag"] for item in peanut], ["PEANUT"])
        self.assertEqual([item["tag"] for item in milk], ["MILK"])

    def test_normalize_allergen_tags_accepts_scalar_and_collections(self):
        self.assertEqual(normalize_allergen_tags("en:almond"), {"TREE_NUTS"})
        self.assertEqual(
            normalize_allergen_tags(["H\u1ea1t c\u00e2y", "en:sesame-seeds", "unknown"]),
            {"TREE_NUTS", "SESAME"},
        )

    def test_pumpkin_seed_is_not_mapped_to_tree_nuts(self):
        self.assertIsNone(normalize_allergen_tag("h\u1ea1t b\u00ed xanh"))
        self.assertFalse(has_unsupported_allergen_tags(["h\u1ea1t c\u00e2y"]))
        self.assertEqual(
            check_product_ingredients(
                ["h\u1ea1t b\u00ed xanh", "y\u1ebfn m\u1ea1ch"],
                ["H\u1ea1t c\u00e2y"],
            ),
            [],
        )

    def test_granola_tree_nut_ingredients_match_and_are_not_unknown(self):
        user_profile = ["H\u1ea1t c\u00e2y"]
        ingredients = [
            "h\u1ea1t h\u1ea1nh nh\u00e2n",
            "h\u1ea1t \u0111i\u1ec1u",
            "h\u1ea1t b\u00ed xanh",
            "y\u1ebfn m\u1ea1ch",
        ]
        matches = check_product_ingredients(ingredients, user_profile)
        self.assertTrue(any(item["tag"] == "TREE_NUTS" for item in matches))
        self.assertFalse(should_mark_allergen_result_unknown(
            user_profile,
            product_ingredients=ingredients,
            matches=matches,
        ))

    def test_known_match_wins_over_unmapped_profile_and_product_allergen_values(self):
        profile = ["TREE_NUTS", "en:future-allergen"]
        ingredients = ["almond", "oats"]
        matches = check_product_ingredients(ingredients, profile)
        self.assertTrue(has_unsupported_allergen_tags(profile))
        self.assertFalse(should_mark_allergen_result_unknown(
            profile,
            product_ingredients=ingredients,
            product_allergen_tags=["en:future-product-allergen"],
            matches=matches,
        ))

    def test_unmapped_values_remain_unsupported_when_no_known_match_exists(self):
        self.assertTrue(has_unsupported_allergen_tags(["en:future-allergen"]))
        self.assertTrue(should_mark_allergen_result_unknown(
            ["TREE_NUTS", "en:future-allergen"],
            product_ingredients=["oats"],
            matches=[],
        ))

    def test_oats_are_a_confident_no_match_for_tree_nut_profile(self):
        matches = check_product_ingredients(["oats"], ["H\u1ea1t c\u00e2y"])
        self.assertEqual(matches, [])
        self.assertFalse(should_mark_allergen_result_unknown(
            ["H\u1ea1t c\u00e2y"],
            product_ingredients=["oats"],
            matches=matches,
        ))

    def test_missing_profile_or_missing_product_evidence_is_unknown(self):
        self.assertTrue(should_mark_allergen_result_unknown([], ["almond"]))
        self.assertTrue(should_mark_allergen_result_unknown(["TREE_NUTS"]))
        self.assertTrue(should_mark_allergen_result_unknown(
            ["TREE_NUTS"],
            product_ingredients=[],
            product_allergen_tags=[],
            gemini_allergens=[],
            may_contain_allergens=[],
        ))


if __name__ == "__main__":
    unittest.main()
