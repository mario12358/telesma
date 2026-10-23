import unittest

from helpers import TestWithService


class TestReaderLoanList(TestWithService):
    def setUp(self):
        super().setUp()
        self.anna = self.add_reader(name="Anna", email="anna@example.com")["id"]
        self.john = self.add_reader(name="John", email="john@example.com")["id"]
        self.book = self.add_item(title="The Doll", type="book", copies=9)["id"]
        self.film = self.add_item(title="Casablanca", type="film", copies=9)["id"]
        self.first = self.borrow(self.anna, self.book)
        self.someone_elses = self.borrow(self.john, self.book)
        self.second = self.borrow(self.anna, self.film)
        self.third = self.borrow(self.anna, self.book)
        self.set_day("2026-01-06")
        self.returned = self.give_back(self.second["id"])

    def loans(self, reader_id: int, query: str = "") -> list[dict]:
        response = self.request("GET", f"/readers/{reader_id}/loans{query}")
        self.assertEqual(response.status, 200, response.body)
        self.assertEqual(list(response.json()), ["loans"])
        return response.json()["loans"]

    def test_list_by_default_only_unreturned_in_ascending_id_order(self):
        self.assertEqual(self.loans(self.anna), [self.first, self.third])

    def test_list_state_all_also_contains_returned_with_fine(self):
        everything = self.loans(self.anna, "?state=all")

        self.assertEqual(everything, [self.first, self.returned, self.third])
        self.assertEqual((everything[1]["return_date"], everything[1]["fine"]), ("2026-01-06", 4.0))

    def test_list_does_not_contain_another_readers_loans(self):
        self.assertEqual(self.loans(self.john), [self.someone_elses])
        self.assertEqual(self.loans(self.john, "?state=all"), [self.someone_elses])

    def test_list_reader_without_loans_gets_empty_list(self):
        new = self.add_reader(name="Eve", email="eve@example.com")["id"]

        self.assertEqual(self.loans(new), [])
        self.assertEqual(self.loans(new, "?state=all"), [])

    def test_list_after_returning_everything_empty_by_default(self):
        self.give_back(self.someone_elses["id"])

        self.assertEqual(self.loans(self.john), [])
        self.assertEqual(len(self.loans(self.john, "?state=all")), 1)

    def test_list_other_state_value_returns_400(self):
        for query in ("?state=returned", "?state=unreturned", "?state=", "?state=ALL"):
            with self.subTest(query=query):
                response = self.request("GET", f"/readers/{self.anna}/loans{query}")
                self.assert_error(response, 400, "invalid_data")

    def test_list_nonexistent_reader_returns_404(self):
        for query in ("", "?state=all"):
            with self.subTest(query=query):
                response = self.request("GET", f"/readers/99/loans{query}")
                self.assert_error(response, 404, "not_found")


if __name__ == "__main__":
    unittest.main()
