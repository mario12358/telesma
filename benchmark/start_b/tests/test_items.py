import unittest

from helpers import TestWithService

VALID = {"title": "The Doll", "type": "book", "copies": 2}


class TestItemCreation(TestWithService):
    def test_create_valid_data_returns_201_and_full_item(self):
        response = self.request("POST", "/items", data=VALID)

        self.assertEqual(response.status, 201)
        self.assertEqual(
            response.json(),
            {"id": 1, "title": "The Doll", "type": "book", "copies": 2, "available": 2},
        )

    def test_create_subsequent_items_get_ascending_ids_from_1(self):
        identifiers = [self.add_item(title=f"Volume {number}")["id"] for number in range(3)]

        self.assertEqual(identifiers, [1, 2, 3])

    def test_create_title_with_non_ascii_characters_comes_back_unchanged(self):
        item = self.add_item(title="Crème brûlée à la française", type="film")

        self.assertEqual(item["title"], "Crème brûlée à la française")
        self.assertEqual(self.request("GET", "/items/1").json()["title"], "Crème brûlée à la française")

    def test_create_invalid_field_returns_400_and_creates_no_item(self):
        bad_fields = (
            ("title", ""), ("title", "   "), ("title", 7), ("title", None),
            ("type", "game"), ("type", "Book"), ("type", ""), ("type", 1), ("type", None),
            ("copies", 0), ("copies", -1), ("copies", 1.5), ("copies", 2.0),
            ("copies", "2"), ("copies", True), ("copies", None),
            ("copies", 2**63),
        )
        for field, value in bad_fields:
            with self.subTest(field=field, value=value):
                response = self.request("POST", "/items", data={**VALID, field: value})
                self.assert_error(response, 400, "invalid_data")
        self.assertEqual(self.request("GET", "/items").json(), {"items": []})

    def test_create_missing_required_field_returns_400(self):
        for field in VALID:
            with self.subTest(missing=field):
                data = {key: value for key, value in VALID.items() if key != field}
                self.assert_error(self.request("POST", "/items", data=data), 400, "invalid_data")

    def test_create_invalid_json_returns_400(self):
        self.assert_error(self.request("POST", "/items", body=b"{title}"), 400, "invalid_data")


class TestItemRead(TestWithService):
    def test_get_existing_item_returns_200_with_available(self):
        self.add_item(title="The Doll", copies=3)
        self.add_item(title="Casablanca", type="film", copies=1)

        response = self.request("GET", "/items/2")

        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.json(),
            {"id": 2, "title": "Casablanca", "type": "film", "copies": 1, "available": 1},
        )

    def test_get_nonexistent_id_returns_404(self):
        self.add_item()

        for path in ("/items/2", "/items/0", "/items/99999999999999999999",
                     "/items/abc", "/items/-1", "/items/1/", "/items/"):
            with self.subTest(path=path):
                self.assert_error(self.request("GET", path), 404, "not_found")


class TestItemList(TestWithService):
    def setUp(self):
        super().setUp()
        self.add_item(title="The Doll", type="book")
        self.add_item(title="Casablanca", type="film")
        self.add_item(title="Ulysses", type="book")
        self.add_item(title="Vertigo", type="film")

    def identifiers(self, path: str) -> list[int]:
        response = self.request("GET", path)
        self.assertEqual(response.status, 200)
        return [item["id"] for item in response.json()["items"]]

    def test_list_without_filter_returns_all_in_ascending_id_order(self):
        self.assertEqual(self.identifiers("/items"), [1, 2, 3, 4])

    def test_list_contains_full_items_with_available(self):
        first = self.request("GET", "/items").json()["items"][0]

        self.assertEqual(
            first,
            {"id": 1, "title": "The Doll", "type": "book", "copies": 1, "available": 1},
        )

    def test_list_type_filter_narrows_to_one_type(self):
        self.assertEqual(self.identifiers("/items?type=book"), [1, 3])
        self.assertEqual(self.identifiers("/items?type=film"), [2, 4])

    def test_list_unknown_type_in_filter_returns_400(self):
        for path in ("/items?type=game", "/items?type=", "/items?type=FILM"):
            with self.subTest(path=path):
                self.assert_error(self.request("GET", path), 400, "invalid_data")


if __name__ == "__main__":
    unittest.main()
