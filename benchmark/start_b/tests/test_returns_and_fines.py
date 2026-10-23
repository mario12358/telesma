import unittest

from helpers import TestWithService


class TestWithBookAndFilm(TestWithService):
    """The start day is 2026-01-01: a book is due 2026-01-15, a film 2026-01-04."""

    def setUp(self):
        super().setUp()
        self.anna = self.add_reader(name="Anna", email="anna@example.com")["id"]
        self.john = self.add_reader(name="John", email="john@example.com")["id"]
        self.book = self.add_item(title="The Doll", type="book", copies=4)["id"]
        self.film = self.add_item(title="Casablanca", type="film", copies=1)["id"]

    def indebt_anna_with_film(self, return_day: str) -> dict:
        loan = self.borrow(self.anna, self.film)
        self.set_day(return_day)
        return self.give_back(loan["id"])

    def pay(self, reader_id: int, amount):
        return self.request("POST", f"/readers/{reader_id}/payment", data={"amount": amount})


class TestReturn(TestWithBookAndFilm):
    def test_return_on_time_returns_200_with_return_date_and_zero_fine(self):
        loan = self.borrow(self.anna, self.book)
        self.set_day("2026-01-15")

        response = self.request("POST", f"/loans/{loan['id']}/return")

        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.json(),
            {**loan, "return_date": "2026-01-15", "fine": 0.0},
        )
        self.assertEqual(self.balance(self.anna), 0.0)

    def test_return_book_late_charges_1_per_day(self):
        loan = self.borrow(self.anna, self.book)
        self.set_day("2026-01-18")

        returned = self.give_back(loan["id"])

        self.assertEqual((returned["return_date"], returned["fine"]), ("2026-01-18", 3.0))
        self.assertEqual(self.balance(self.anna), 3.0)
        self.assertEqual(self.balance(self.john), 0.0)

    def test_return_film_late_charges_2_per_day(self):
        returned = self.indebt_anna_with_film("2026-01-07")

        self.assertEqual(returned["fine"], 6.0)
        self.assertEqual(self.balance(self.anna), 6.0)

    def test_return_day_after_due_date_is_one_day_of_fine(self):
        self.assertEqual(self.indebt_anna_with_film("2026-01-05")["fine"], 2.0)

    def test_return_fines_from_several_loans_add_up_in_balance(self):
        book = self.borrow(self.anna, self.book)
        film = self.borrow(self.anna, self.film)
        self.set_day("2026-01-17")

        self.give_back(book["id"])
        self.give_back(film["id"])

        self.assertEqual(self.balance(self.anna), 2.0 + 26.0)

    def test_return_is_visible_when_reading_the_loan(self):
        returned = self.indebt_anna_with_film("2026-01-07")

        self.assertEqual(self.request("GET", f"/loans/{returned['id']}").json(), returned)

    def test_return_repeated_returns_409_and_does_not_charge_twice(self):
        returned = self.indebt_anna_with_film("2026-01-07")
        self.set_day("2026-01-20")

        response = self.request("POST", f"/loans/{returned['id']}/return")

        self.assert_error(response, 409, "already_returned")
        self.assertEqual(self.balance(self.anna), 6.0)
        self.assertEqual(self.request("GET", f"/loans/{returned['id']}").json(), returned)

    def test_return_nonexistent_loan_returns_404(self):
        self.assert_error(self.request("POST", "/loans/99/return"), 404, "not_found")

    def test_return_increases_available_and_lets_another_reader_borrow(self):
        loan = self.borrow(self.anna, self.film)
        self.assert_error(self.try_borrow(self.john, self.film), 409, "no_copies")

        self.give_back(loan["id"])

        self.assertEqual(self.request("GET", f"/items/{self.film}").json()["available"], 1)
        self.assertEqual(self.try_borrow(self.john, self.film).status, 201)

    def test_return_frees_a_slot_in_the_limit(self):
        loans = [self.borrow(self.anna, self.book) for _ in range(3)]
        self.assert_error(self.try_borrow(self.anna, self.book), 409, "loan_limit")

        self.give_back(loans[0]["id"])

        self.assertEqual(self.try_borrow(self.anna, self.book).status, 201)

    def test_return_of_overdue_loan_removes_overdue(self):
        loan = self.borrow(self.anna, self.book)
        self.set_day("2026-01-16")
        self.assert_error(self.try_borrow(self.anna, self.book), 409, "has_overdue")

        self.give_back(loan["id"])

        self.assertEqual(self.try_borrow(self.anna, self.book).status, 201)

    def test_return_and_balance_survive_restart(self):
        returned = self.indebt_anna_with_film("2026-01-07")

        self.service.stop()
        self.service.start()

        self.assertEqual(self.request("GET", f"/loans/{returned['id']}").json(), returned)
        self.assertEqual(self.balance(self.anna), 6.0)


class TestBlockAfterFines(TestWithBookAndFilm):
    def test_balance_exactly_10_after_return_blocks_loans(self):
        self.indebt_anna_with_film("2026-01-09")

        self.assertEqual(self.balance(self.anna), 10.0)
        self.assert_error(self.try_borrow(self.anna, self.book), 409, "fine_block")

    def test_balance_8_after_return_does_not_block(self):
        self.indebt_anna_with_film("2026-01-08")

        self.assertEqual(self.balance(self.anna), 8.0)
        self.assertEqual(self.try_borrow(self.anna, self.book).status, 201)

    def test_payment_of_one_cent_below_threshold_unblocks(self):
        self.indebt_anna_with_film("2026-01-09")

        self.assertEqual(self.pay(self.anna, 0.01).json()["fine_balance"], 9.99)

        self.assertEqual(self.try_borrow(self.anna, self.book).status, 201)


class TestPayment(TestWithBookAndFilm):
    def setUp(self):
        super().setUp()
        self.indebt_anna_with_film("2026-01-07")

    def test_partial_payment_decreases_balance_and_returns_reader(self):
        response = self.pay(self.anna, 2.5)

        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.json(),
            {"id": self.anna, "name": "Anna", "email": "anna@example.com", "fine_balance": 3.5},
        )
        self.assertEqual(self.balance(self.anna), 3.5)

    def test_payment_successive_cents_do_not_lose_precision(self):
        for amount in (0.1, 0.2, 2.35, 1):
            self.assertEqual(self.pay(self.anna, amount).status, 200)

        self.assertEqual(self.balance(self.anna), 2.35)

    def test_payment_of_whole_balance_zeroes_it(self):
        self.assertEqual(self.pay(self.anna, 6.0).json()["fine_balance"], 0.0)

    def test_payment_larger_than_balance_returns_409_overpayment(self):
        self.assert_error(self.pay(self.anna, 6.01), 409, "overpayment")
        self.assertEqual(self.balance(self.anna), 6.0)

    def test_payment_with_zero_balance_returns_409_overpayment(self):
        self.assert_error(self.pay(self.john, 0.01), 409, "overpayment")

    def test_payment_invalid_amount_returns_400(self):
        for amount in (0, -1, -0.01, 0.0, "2.5", None, True, [1], 1.005, 0.001):
            with self.subTest(amount=amount):
                self.assert_error(self.pay(self.anna, amount), 400, "invalid_data")
        self.assertEqual(self.balance(self.anna), 6.0)

    def test_payment_missing_amount_or_bad_json_returns_400(self):
        path = f"/readers/{self.anna}/payment"

        self.assert_error(self.request("POST", path, data={}), 400, "invalid_data")
        self.assert_error(self.request("POST", path, body=b""), 400, "invalid_data")
        self.assert_error(self.request("POST", path, body=b'{"amount": NaN}'), 400, "invalid_data")
        self.assert_error(self.request("POST", path, body=b'{"amount": 1e400}'), 400, "invalid_data")

    def test_payment_nonexistent_reader_returns_404(self):
        self.assert_error(self.pay(99, 1.0), 404, "not_found")


if __name__ == "__main__":
    unittest.main()
