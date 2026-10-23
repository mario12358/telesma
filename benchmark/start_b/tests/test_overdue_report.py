import unittest

from helpers import TestWithService


class TestOverdueReport(TestWithService):
    """The start day is 2026-01-01: a book is due 2026-01-15, a film 2026-01-04."""

    def setUp(self):
        super().setUp()
        self.anna = self.add_reader(name="Anna", email="anna@example.com")["id"]
        self.john = self.add_reader(name="John", email="john@example.com")["id"]
        self.book = self.add_item(title="The Doll", type="book", copies=5)["id"]
        self.film = self.add_item(title="Casablanca, or «the film»", type="film", copies=5)["id"]

    def report(self) -> list[dict]:
        response = self.request("GET", "/reports/overdue")
        self.assertEqual(response.status, 200, response.body)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assertEqual(list(response.json()), ["overdue"])
        return response.json()["overdue"]

    def test_report_without_loans_is_empty(self):
        self.assertEqual(self.report(), [])

    def test_report_on_due_date_is_empty(self):
        self.borrow(self.anna, self.film)
        self.set_day("2026-01-04")

        self.assertEqual(self.report(), [])

    def test_report_one_overdue_loan_has_all_fields(self):
        loan = self.borrow(self.anna, self.film)
        self.set_day("2026-01-05")

        self.assertEqual(
            self.report(),
            [{
                "loan_id": loan["id"], "reader_id": self.anna,
                "item_id": self.film, "title": "Casablanca, or «the film»", "type": "film",
                "due_date": "2026-01-04", "days_overdue": 1,
            }],
        )

    def test_report_many_overdue_in_ascending_id_order_with_own_days(self):
        annas_book = self.borrow(self.anna, self.book)
        johns_film = self.borrow(self.john, self.film)
        self.set_day("2026-01-10")
        eve = self.add_reader(name="Eve", email="eve@example.com")["id"]
        eves_book = self.borrow(eve, self.book)
        self.set_day("2026-02-01")

        report = self.report()

        self.assertEqual(
            [(entry["loan_id"], entry["reader_id"], entry["type"], entry["days_overdue"]) for entry in report],
            [
                (annas_book["id"], self.anna, "book", 17),
                (johns_film["id"], self.john, "film", 28),
                (eves_book["id"], eve, "book", 8),
            ],
        )

    def test_report_skips_timely_among_overdue(self):
        self.borrow(self.anna, self.book)
        film = self.borrow(self.anna, self.film)
        self.set_day("2026-01-10")

        self.assertEqual([entry["loan_id"] for entry in self.report()], [film["id"]])

    def test_report_overdue_disappears_after_return(self):
        film = self.borrow(self.anna, self.film)
        book = self.borrow(self.john, self.book)
        self.set_day("2026-01-20")
        self.assertEqual(len(self.report()), 2)

        self.give_back(film["id"])

        self.assertEqual([entry["loan_id"] for entry in self.report()], [book["id"]])


if __name__ == "__main__":
    unittest.main()
