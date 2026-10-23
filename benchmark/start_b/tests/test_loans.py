import unittest

from helpers import TestWithService


class TestLoans(TestWithService):
    def setUp(self):
        super().setUp()
        self.reader = self.add_reader()
        self.book = self.add_item(title="The Doll", type="book", copies=2)
        self.film = self.add_item(title="Casablanca", type="film", copies=1)

    def available(self, item: dict) -> int:
        return self.request("GET", f"/items/{item['id']}").json()["available"]

    def test_create_book_returns_201_with_due_date_in_14_days(self):
        response = self.try_borrow(self.reader["id"], self.book["id"])

        self.assertEqual(response.status, 201)
        self.assertEqual(
            response.json(),
            {
                "id": 1, "reader_id": 1, "item_id": 1,
                "loan_date": "2026-01-01", "due_date": "2026-01-15",
                "return_date": None, "fine": 0.0,
            },
        )

    def test_create_film_has_due_date_in_3_days(self):
        loan = self.borrow(self.reader["id"], self.film["id"])

        self.assertEqual(loan["loan_date"], "2026-01-01")
        self.assertEqual(loan["due_date"], "2026-01-04")

    def test_create_due_date_counts_from_system_day_across_month_boundary(self):
        self.set_day("2028-02-27")

        book = self.borrow(self.reader["id"], self.book["id"])
        film = self.borrow(self.reader["id"], self.film["id"])

        self.assertEqual((book["loan_date"], book["due_date"]), ("2028-02-27", "2028-03-12"))
        self.assertEqual((film["loan_date"], film["due_date"]), ("2028-02-27", "2028-03-01"))

    def test_create_decreases_available_only_for_borrowed_item(self):
        self.borrow(self.reader["id"], self.book["id"])

        self.assertEqual(self.available(self.book), 1)
        self.assertEqual(self.available(self.film), 1)
        items = self.request("GET", "/items").json()["items"]
        self.assertEqual([item["available"] for item in items], [1, 1])
        self.assertEqual([item["copies"] for item in items], [2, 1])

    def test_create_nonexistent_reader_or_item_returns_404(self):
        for reader_id, item_id in ((99, 1), (1, 99), (99, 99), (0, 1), (1, -1)):
            with self.subTest(reader_id=reader_id, item_id=item_id):
                response = self.try_borrow(reader_id, item_id)
                self.assert_error(response, 404, "not_found")
        self.assertEqual(self.available(self.book), 2)

    def test_create_invalid_data_returns_400(self):
        bad_data = (
            {}, {"reader_id": 1}, {"item_id": 1},
            {"reader_id": "1", "item_id": 1}, {"reader_id": 1, "item_id": 1.0},
            {"reader_id": True, "item_id": 1}, {"reader_id": None, "item_id": 1},
            {"reader_id": 1, "item_id": [1]},
        )
        for data in bad_data:
            with self.subTest(data=data):
                self.assert_error(self.request("POST", "/loans", data=data), 400, "invalid_data")
        self.assert_error(self.request("POST", "/loans", body=b"{"), 400, "invalid_data")

    def test_create_wrong_field_type_takes_precedence_over_missing_resource(self):
        response = self.request("POST", "/loans", data={"reader_id": 99, "item_id": "1"})

        self.assert_error(response, 400, "invalid_data")

    def test_get_existing_loan_returns_200(self):
        self.borrow(self.reader["id"], self.book["id"])
        created = self.borrow(self.reader["id"], self.film["id"])

        response = self.request("GET", "/loans/2")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.json(), created)
        self.assertEqual(response.json()["item_id"], self.film["id"])

    def test_get_nonexistent_loan_returns_404(self):
        self.borrow(self.reader["id"], self.book["id"])

        for path in ("/loans/2", "/loans/0", "/loans/x"):
            with self.subTest(path=path):
                self.assert_error(self.request("GET", path), 404, "not_found")


if __name__ == "__main__":
    unittest.main()
