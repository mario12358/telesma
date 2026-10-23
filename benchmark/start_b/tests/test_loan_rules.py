import unittest

from helpers import TestWithService


class TestLoanRules(TestWithService):
    """The start day is 2026-01-01: a book is due 2026-01-15, a film 2026-01-04."""

    def setUp(self):
        super().setUp()
        self.anna = self.add_reader(name="Anna", email="anna@example.com")["id"]
        self.john = self.add_reader(name="John", email="john@example.com")["id"]
        self.books = [
            self.add_item(title=f"Volume {number}", type="book", copies=5)["id"]
            for number in range(1, 5)
        ]
        self.film = self.add_item(title="Casablanca", type="film", copies=5)["id"]
        self.only_copy = self.add_item(title="Rare Edition", type="book", copies=1)["id"]

    def loans_in_db(self) -> int:
        latest = self.borrow(self.john, self.books[0])
        return latest["id"] - 1


class TestFineBlock(TestLoanRules):
    def test_create_balance_equal_to_10_returns_409_fine_block(self):
        self.set_balance_in_db(self.anna, 1000)

        self.assert_error(self.try_borrow(self.anna, self.film), 409, "fine_block")
        self.assertEqual(self.loans_in_db(), 0)

    def test_create_balance_just_below_10_allows_borrowing(self):
        self.set_balance_in_db(self.anna, 999)

        self.assertEqual(self.try_borrow(self.anna, self.film).status, 201)

    def test_create_block_applies_only_to_the_indebted_reader(self):
        self.set_balance_in_db(self.anna, 2500)

        self.assert_error(self.try_borrow(self.anna, self.film), 409, "fine_block")
        self.assertEqual(self.try_borrow(self.john, self.film).status, 201)


class TestOverdue(TestLoanRules):
    def test_create_on_due_date_there_is_no_overdue(self):
        self.borrow(self.anna, self.film)
        self.set_day("2026-01-04")

        self.assertEqual(self.try_borrow(self.anna, self.books[0]).status, 201)

    def test_create_day_after_due_date_returns_409_has_overdue(self):
        self.borrow(self.anna, self.film)
        self.set_day("2026-01-05")

        self.assert_error(self.try_borrow(self.anna, self.books[0]), 409, "has_overdue")

    def test_create_one_overdue_among_timely_ones_is_enough(self):
        self.borrow(self.anna, self.books[0])
        self.borrow(self.anna, self.film)
        self.set_day("2026-01-10")

        self.assert_error(self.try_borrow(self.anna, self.books[1]), 409, "has_overdue")

    def test_create_another_readers_overdue_does_not_block(self):
        self.borrow(self.anna, self.film)
        self.set_day("2026-01-05")

        self.assertEqual(self.try_borrow(self.john, self.film).status, 201)


class TestLoanLimit(TestLoanRules):
    def test_create_third_loan_is_allowed_fourth_returns_409(self):
        for item_id in self.books[:3]:
            self.borrow(self.anna, item_id)

        self.assert_error(self.try_borrow(self.anna, self.books[3]), 409, "loan_limit")

    def test_create_limit_counts_loans_not_distinct_items(self):
        for _ in range(3):
            self.borrow(self.anna, self.books[0])

        self.assert_error(self.try_borrow(self.anna, self.books[0]), 409, "loan_limit")

    def test_create_one_readers_limit_does_not_block_another(self):
        for item_id in self.books[:3]:
            self.borrow(self.anna, item_id)

        self.assertEqual(self.try_borrow(self.john, self.books[3]).status, 201)


class TestNoCopies(TestLoanRules):
    def test_create_last_copy_on_loan_returns_409_no_copies(self):
        self.borrow(self.anna, self.only_copy)

        self.assert_error(self.try_borrow(self.john, self.only_copy), 409, "no_copies")
        item = self.request("GET", f"/items/{self.only_copy}").json()
        self.assertEqual(item["available"], 0)

    def test_create_another_item_stays_available(self):
        self.borrow(self.anna, self.only_copy)

        self.assertEqual(self.try_borrow(self.john, self.film).status, 201)


class TestRuleOrder(TestLoanRules):
    def make_overdue(self):
        self.borrow(self.anna, self.film)
        self.set_day("2026-01-05")

    def exhaust_limit_without_overdue(self):
        for item_id in self.books[:3]:
            self.borrow(self.anna, item_id)

    def take_the_only_copy(self):
        self.borrow(self.john, self.only_copy)

    def test_fine_block_wins_over_overdue(self):
        self.make_overdue()
        self.set_balance_in_db(self.anna, 1000)

        self.assert_error(self.try_borrow(self.anna, self.books[0]), 409, "fine_block")

    def test_fine_block_wins_over_limit_and_no_copies(self):
        self.exhaust_limit_without_overdue()
        self.take_the_only_copy()
        self.set_balance_in_db(self.anna, 1000)

        self.assert_error(self.try_borrow(self.anna, self.only_copy), 409, "fine_block")

    def test_overdue_wins_over_limit(self):
        self.exhaust_limit_without_overdue()
        self.set_day("2026-01-16")

        self.assert_error(self.try_borrow(self.anna, self.books[3]), 409, "has_overdue")

    def test_overdue_wins_over_no_copies(self):
        self.take_the_only_copy()
        self.make_overdue()

        self.assert_error(self.try_borrow(self.anna, self.only_copy), 409, "has_overdue")

    def test_limit_wins_over_no_copies(self):
        self.exhaust_limit_without_overdue()
        self.take_the_only_copy()

        self.assert_error(self.try_borrow(self.anna, self.only_copy), 409, "loan_limit")

    def test_missing_resource_wins_over_rule(self):
        self.set_balance_in_db(self.anna, 1000)

        self.assert_error(self.try_borrow(self.anna, 999), 404, "not_found")


if __name__ == "__main__":
    unittest.main()
