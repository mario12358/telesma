"""Stage A judge — the specification `telesma/spec/library.md` alone. Every assertion follows from its text.

Tests marked `stage_a_only` describe behaviour that the stage B change requests deliberately change
(fine computation) — in stage B they are replaced by their counterparts in `test_stage_b.py`.
"""
import unittest

from base import STAGE, TestHTTP

stage_a_only = unittest.skipIf(STAGE == "B", "behaviour changed by a stage B change request")


class System(TestHTTP):
    def test_health_and_start_day(self):
        self.assertEqual(self.ok("GET", "/health"), {"ok": True})
        self.assertEqual(self.ok("GET", "/system/day"), {"date": "2026-01-01"})

    def test_day_change_and_same_date(self):
        self.assertEqual(self.day("2026-01-05"), {"date": "2026-01-05"})
        self.assertEqual(self.day("2026-01-05"), {"date": "2026-01-05"})
        self.assertEqual(self.ok("GET", "/system/day"), {"date": "2026-01-05"})

    def test_date_in_past_and_bad_date(self):
        self.day("2026-01-05")
        self.error("POST", "/system/day", {"date": "2026-01-04"}, 400, "date_in_past")
        self.error("POST", "/system/day", {"date": "January 5"}, 400, "invalid_data")
        self.error("POST", "/system/day", {}, 400, "invalid_data")
        self.assertEqual(self.ok("GET", "/system/day"), {"date": "2026-01-05"})

    def test_unknown_path_and_bad_json(self):
        self.error("GET", "/no-such-path", None, 404, "not_found")
        status, _, content = self.raw("POST", "/items", text="{not json")
        self.assertEqual(status, 400, content)
        self.assertIn("invalid_data", content)


class Items(TestHTTP):
    def test_create_and_read(self):
        i = self.item("The Doll", "book", 2)
        self.assertEqual(i, {"id": 1, "title": "The Doll", "type": "book", "copies": 2,
                             "available": 2})
        self.assertEqual(self.ok("GET", "/items/1"), i)
        self.error("GET", "/items/99", None, 404, "not_found")

    def test_validation(self):
        for body in ({"type": "book", "copies": 1}, {"title": "", "type": "book", "copies": 1},
                     {"title": "X", "type": "newspaper", "copies": 1},
                     {"title": "X", "type": "film", "copies": 0},
                     {"title": "X", "type": "film", "copies": "two"},
                     {"title": "X", "type": "film"}):
            self.error("POST", "/items", body, 400, "invalid_data")

    def test_list_and_type_filter(self):
        self.item("A", "book")
        self.item("B", "film")
        self.item("C", "book")
        self.assertEqual([i["title"] for i in self.ok("GET", "/items")["items"]], ["A", "B", "C"])
        self.assertEqual([i["title"] for i in self.ok("GET", "/items?type=book")["items"]], ["A", "C"])
        self.assertEqual([i["title"] for i in self.ok("GET", "/items?type=film")["items"]], ["B"])
        self.error("GET", "/items?type=newspaper", None, 400, "invalid_data")

    def test_available_drops_and_comes_back(self):
        i, r = self.item(copies=2), self.reader()
        loan = self.borrow(r, i)
        self.assertEqual(self.ok("GET", "/items/1")["available"], 1)
        self.give_back(loan)
        self.assertEqual(self.ok("GET", "/items/1")["available"], 2)


class Readers(TestHTTP):
    def test_create_and_read(self):
        r = self.reader("John Reed", "john@example.com")
        self.assertEqual(r, {"id": 1, "name": "John Reed", "email": "john@example.com", "fine_balance": 0.0})
        self.assertEqual(self.ok("GET", "/readers/1"), r)
        self.error("GET", "/readers/7", None, 404, "not_found")

    def test_validation_and_email_taken(self):
        self.error("POST", "/readers", {"name": "X", "email": "no-at-sign"}, 400, "invalid_data")
        self.error("POST", "/readers", {"email": "a@example.com"}, 400, "invalid_data")
        self.reader("John", "John@Example.com")
        self.error("POST", "/readers", {"name": "Other", "email": "john@example.COM"}, 409, "email_taken")


class Loans(TestHTTP):
    def test_due_dates_of_book_and_film(self):
        self.day("2026-03-10")
        r = self.reader()
        b = self.borrow(r, self.item("B", "book"))
        f = self.borrow(r, self.item("F", "film"))
        self.assertEqual((b["loan_date"], b["due_date"]), ("2026-03-10", "2026-03-24"))
        self.assertEqual(f["due_date"], "2026-03-13")
        self.assertEqual((b["return_date"], b["fine"]), (None, 0.0))
        self.assertEqual(self.ok("GET", f"/loans/{b['id']}"), b)

    def test_nonexistent_and_bad_data(self):
        r, i = self.reader(), self.item()
        self.error("POST", "/loans", {"reader_id": 9, "item_id": i["id"]}, 404, "not_found")
        self.error("POST", "/loans", {"reader_id": r["id"], "item_id": 9}, 404, "not_found")
        self.error("POST", "/loans", {"reader_id": r["id"]}, 400, "invalid_data")
        self.error("GET", "/loans/5", None, 404, "not_found")
        self.error("POST", "/loans/5/return", None, 404, "not_found")

    def test_no_copies(self):
        i = self.item(copies=1)
        loan = self.borrow(self.reader(), i)
        second = self.reader()
        self.error("POST", "/loans", {"reader_id": second["id"], "item_id": i["id"]},
                   409, "no_copies")
        self.give_back(loan)
        self.borrow(second, i)

    def test_limit_of_three_exactly_at_the_boundary(self):
        r = self.reader()
        loans = [self.borrow(r, self.item(f"I{n}")) for n in range(3)]
        fourth = self.item("I4")
        self.error("POST", "/loans", {"reader_id": r["id"], "item_id": fourth["id"]},
                   409, "loan_limit")
        self.give_back(loans[0])
        self.borrow(r, fourth)

    def test_overdue_blocks_from_first_day_past_due(self):
        r = self.reader()
        loan = self.borrow(r, self.item("B"))            # due 2026-01-15
        other = self.item("Other")
        self.day("2026-01-15")
        self.give_back(self.borrow(r, other))            # still allowed on the due date
        self.day("2026-01-16")
        self.error("POST", "/loans", {"reader_id": r["id"], "item_id": other["id"]},
                   409, "has_overdue")
        self.give_back(loan)
        self.borrow(r, other)

    def test_rule_order_overdue_before_limit_and_no_copies(self):
        r = self.reader()
        for n in range(3):
            self.borrow(r, self.item(f"I{n}"))
        taken = self.item("Taken", copies=1)
        self.borrow(self.reader(), taken)
        body = {"reader_id": r["id"], "item_id": taken["id"]}
        self.error("POST", "/loans", body, 409, "loan_limit")
        self.day("2026-02-01")
        self.error("POST", "/loans", body, 409, "has_overdue")

    @stage_a_only
    def test_fine_book_and_film(self):
        r = self.reader()
        b = self.borrow(r, self.item("B", "book"))       # due 01-15
        f = self.borrow(r, self.item("F", "film"))       # due 01-04
        self.day("2026-01-06")
        self.assertEqual(self.give_back(f)["fine"], 4.0)
        self.day("2026-01-18")
        rb = self.give_back(b)
        self.assertEqual((rb["fine"], rb["return_date"]), (3.0, "2026-01-18"))
        self.assertEqual(self.ok("GET", f"/readers/{r['id']}")["fine_balance"], 7.0)

    def test_return_on_time_without_fine_and_repeated_return(self):
        r = self.reader()
        loan = self.borrow(r, self.item())
        self.day("2026-01-15")
        self.assertEqual(self.give_back(loan)["fine"], 0.0)
        self.error("POST", f"/loans/{loan['id']}/return", None, 409, "already_returned")
        self.assertEqual(self.ok("GET", f"/readers/{r['id']}")["fine_balance"], 0.0)

    @stage_a_only
    def test_fine_block_from_ten_and_payment(self):
        r = self.reader()
        f = self.borrow(r, self.item("F", "film"))       # due 01-04
        self.day("2026-01-09")                           # 5 days × 2.0 = 10.0
        self.assertEqual(self.give_back(f)["fine"], 10.0)
        i = self.item("B")
        body = {"reader_id": r["id"], "item_id": i["id"]}
        self.error("POST", "/loans", body, 409, "fine_block")
        self.error("POST", f"/readers/{r['id']}/payment", {"amount": 10.5}, 409, "overpayment")
        self.error("POST", f"/readers/{r['id']}/payment", {"amount": 0}, 400, "invalid_data")
        self.assertEqual(self.ok("POST", f"/readers/{r['id']}/payment", {"amount": 0.5})["fine_balance"], 9.5)
        self.ok("POST", "/loans", body, 201)

    def test_reader_loan_list(self):
        r = self.reader()
        a = self.borrow(r, self.item("A"))
        b = self.borrow(r, self.item("B"))
        self.give_back(a)
        path = f"/readers/{r['id']}/loans"
        self.assertEqual([x["id"] for x in self.ok("GET", path)["loans"]], [b["id"]])
        self.assertEqual([x["id"] for x in self.ok("GET", path + "?state=all")["loans"]],
                         [a["id"], b["id"]])
        self.error("GET", path + "?state=old", None, 400, "invalid_data")
        self.error("GET", "/readers/9/loans", None, 404, "not_found")


class Reports(TestHTTP):
    def test_overdue(self):
        r = self.reader()
        b = self.borrow(r, self.item("Book", "book"))      # due 01-15
        f = self.borrow(r, self.item("Film", "film"))      # due 01-04
        self.assertEqual(self.ok("GET", "/reports/overdue"), {"overdue": []})
        self.day("2026-01-06")
        self.assertEqual(self.ok("GET", "/reports/overdue")["overdue"], [
            {"loan_id": f["id"], "reader_id": r["id"], "item_id": f["item_id"],
             "title": "Film", "type": "film", "due_date": "2026-01-04", "days_overdue": 2}])
        self.day("2026-01-20")
        self.give_back(f)
        o = self.ok("GET", "/reports/overdue")["overdue"]
        self.assertEqual([(x["loan_id"], x["days_overdue"]) for x in o], [(b["id"], 5)])

    def test_csv_header_rows_and_quoting(self):
        r = self.reader('Smith, "John"')
        a = self.borrow(r, self.item("Moby-Dick, or The Whale", "book"))
        self.borrow(r, self.item("Film", "film"))
        self.day("2026-01-10")
        self.give_back(a)
        rows = self.csv()
        self.assertEqual(rows[0], ["id", "reader", "title", "type", "loan_date",
                                   "due_date", "return_date", "fine"])
        self.assertEqual(rows[1], ["1", 'Smith, "John"', "Moby-Dick, or The Whale",
                                   "book", "2026-01-01", "2026-01-15", "2026-01-10", "0.00"])
        self.assertEqual(rows[2], ["2", 'Smith, "John"', "Film", "film", "2026-01-01",
                                   "2026-01-04", "", "0.00"])
        self.assertEqual(len(rows), 3)

    def test_data_survives_restart(self):
        """The database is a file — after starting again on the same file the state must remain."""
        import os
        import subprocess
        import sys
        import time
        import urllib.request
        from base import PROJECT, free_port
        self.item("Durable")
        self.day("2026-04-01")
        self.proc.terminate()
        self.proc.wait(timeout=5)
        self.port = free_port()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "library", "--port", str(self.port),
             "--db", os.path.join(self.tmp.name, "db.sqlite")],
            cwd=PROJECT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(200):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1)
                break
            except OSError:
                time.sleep(0.05)
        self.assertEqual(self.ok("GET", "/items/1")["title"], "Durable")
        self.assertEqual(self.ok("GET", "/system/day"), {"date": "2026-04-01"})


if __name__ == "__main__":
    unittest.main()
