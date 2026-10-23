import csv
import io
import unittest

from helpers import TestWithService

HEADER = "id,reader,title,type,loan_date,due_date,return_date,fine"


class TestCsvExport(TestWithService):
    def export(self) -> str:
        response = self.request("GET", "/reports/loans.csv")
        self.assertEqual(response.status, 200, response.body)
        self.assertEqual(response.headers["Content-Type"], "text/csv; charset=utf-8")
        return response.body.decode("utf-8")

    def rows(self) -> list[list[str]]:
        return list(csv.reader(io.StringIO(self.export(), newline="")))

    def test_export_without_loans_contains_only_header(self):
        self.assertEqual(self.export().splitlines(), [HEADER])

    def test_export_unreturned_row_has_empty_return_date_and_fine_0_00(self):
        reader = self.add_reader(name="Anna Smith")["id"]
        item = self.add_item(title="The Doll", type="book")["id"]
        self.borrow(reader, item)

        self.assertEqual(
            self.export().splitlines(),
            [HEADER, "1,Anna Smith,The Doll,book,2026-01-01,2026-01-15,,0.00"],
        )

    def test_export_returned_row_has_return_date_and_fine_with_two_decimals(self):
        reader = self.add_reader(name="Anna Smith")["id"]
        film = self.add_item(title="Casablanca", type="film")["id"]
        loan = self.borrow(reader, film)
        self.set_day("2026-01-10")
        self.give_back(loan["id"])

        self.assertEqual(
            self.export().splitlines()[1],
            "1,Anna Smith,Casablanca,film,2026-01-01,2026-01-04,2026-01-10,12.00",
        )

    def test_export_covers_all_loans_in_ascending_id_order(self):
        anna = self.add_reader(name="Anna", email="anna@example.com")["id"]
        john = self.add_reader(name="John", email="john@example.com")["id"]
        book = self.add_item(title="The Doll", type="book", copies=3)["id"]
        film = self.add_item(title="Casablanca", type="film", copies=3)["id"]
        self.borrow(john, film)
        annas_first = self.borrow(anna, book)
        self.borrow(john, book)
        self.give_back(annas_first["id"])

        rows = self.rows()[1:]

        self.assertEqual(
            [(row[0], row[1], row[2], row[6]) for row in rows],
            [("1", "John", "Casablanca", ""), ("2", "Anna", "The Doll", "2026-01-01"), ("3", "John", "The Doll", "")],
        )

    def test_export_quotes_fields_with_comma_and_double_quote(self):
        reader = self.add_reader(name="Smith, Anna")["id"]
        item = self.add_item(title='Film "Casablanca", version 2', type="film")["id"]
        self.borrow(reader, item)

        self.assertEqual(
            self.export().splitlines()[1],
            '1,"Smith, Anna","Film ""Casablanca"", version 2",film,2026-01-01,2026-01-04,,0.00',
        )
        self.assertEqual(self.rows()[1][1:3], ["Smith, Anna", 'Film "Casablanca", version 2'])

    def test_export_keeps_non_ascii_characters_in_utf8(self):
        reader = self.add_reader(name="Zoë Brontë")["id"]
        item = self.add_item(title="Señor Müller's Café")["id"]
        self.borrow(reader, item)

        self.assertEqual(self.rows()[1][1:3], ["Zoë Brontë", "Señor Müller's Café"])


if __name__ == "__main__":
    unittest.main()
