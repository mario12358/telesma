"""Stage B judge — the four change requests from `benchmark/changes/`. Run TOGETHER with the
stage A tests (regression): a change must not break what used to work.

Three defect classes the change requests were built around (patterns from the first retro session):
  * mechanism built but not wired to its entry point     → Reminders, Expiry
  * rule added in one place out of N                      → Audiobook (7 places)
  * test data in its simplest shape hides a branch        → a queue with 2+ reservations,
                                                            a jump of several days
"""
import unittest

from base import TestHTTP


class Reminders(TestHTTP):
    def notifications(self, r):
        return self.ok("GET", f"/readers/{r['id']}/notifications")["notifications"]

    def test_due_tomorrow_created_on_day_change(self):
        r = self.reader()
        loan = self.borrow(r, self.item("The Doll"))     # due 01-15
        self.assertEqual(self.notifications(r), [])
        self.day("2026-01-13")
        self.assertEqual(self.notifications(r), [])
        self.day("2026-01-14")
        self.assertEqual(self.notifications(r), [
            {"id": 1, "kind": "due_tomorrow", "loan_id": loan["id"], "title": "The Doll",
             "date": "2026-01-14"}])

    def test_past_due_only_once_despite_further_days(self):
        r = self.reader()
        self.borrow(r, self.item())
        for d in ("2026-01-14", "2026-01-15", "2026-01-16", "2026-01-17", "2026-01-20"):
            self.day(d)
        self.assertEqual([(n["kind"], n["date"]) for n in self.notifications(r)],
                         [("due_tomorrow", "2026-01-14"), ("past_due", "2026-01-16")])

    def test_jump_of_several_days_gives_only_past_due(self):
        r = self.reader()
        self.borrow(r, self.item())
        self.day("2026-01-19")
        self.assertEqual([n["kind"] for n in self.notifications(r)], ["past_due"])

    def test_same_date_and_returned_create_nothing(self):
        r = self.reader()
        loan = self.borrow(r, self.item())
        self.day("2026-01-14")
        self.day("2026-01-14")
        self.assertEqual(len(self.notifications(r)), 1)
        self.give_back(loan)
        self.day("2026-02-01")
        self.assertEqual([n["kind"] for n in self.notifications(r)], ["due_tomorrow"])

    def test_each_reader_sees_their_own(self):
        a, b = self.reader(), self.reader()
        self.borrow(a, self.item("A", "film"))           # due 01-04
        self.borrow(b, self.item("B", "book"))           # due 01-15
        self.day("2026-01-05")
        self.assertEqual([n["title"] for n in self.notifications(a)], ["A"])
        self.assertEqual(self.notifications(b), [])
        self.error("GET", "/readers/9/notifications", None, 404, "not_found")


class Audiobook(TestHTTP):
    def test_create_without_copies(self):
        a = self.item("Solaris", "audiobook", None)
        self.assertEqual(a, {"id": 1, "title": "Solaris", "type": "audiobook", "copies": None,
                             "available": None})
        b = self.item("Other", "audiobook", 5)
        self.assertEqual((b["copies"], b["available"]), (None, None))

    def test_type_filter(self):
        self.item("B", "book")
        self.item("A", "audiobook", None)
        self.assertEqual([i["title"] for i in self.ok("GET", "/items?type=audiobook")["items"]], ["A"])
        self.assertEqual(len(self.ok("GET", "/items")["items"]), 2)

    def test_many_readers_at_once_but_not_twice_the_same(self):
        a = self.item("Solaris", "audiobook", None)
        r1, r2 = self.reader(), self.reader()
        loan = self.borrow(r1, a)
        self.borrow(r2, a)
        self.assertEqual(loan["due_date"], "2026-01-08")
        self.error("POST", "/loans", {"reader_id": r1["id"], "item_id": a["id"]},
                   409, "already_borrowed")
        self.give_back(loan)
        self.borrow(r1, a)

    def test_counts_towards_limit(self):
        r = self.reader()
        for n in range(3):
            self.borrow(r, self.item(f"A{n}", "audiobook", None))
        b = self.item("B")
        self.error("POST", "/loans", {"reader_id": r["id"], "item_id": b["id"]},
                   409, "loan_limit")

    def test_fine_of_half_with_grace_day(self):
        r = self.reader()
        loan = self.borrow(r, self.item("A", "audiobook", None))   # due 01-08
        self.day("2026-01-12")                                     # 4 days late → 3 paid × 0.5
        self.assertEqual(self.give_back(loan)["fine"], 1.5)
        self.assertEqual(self.ok("GET", f"/readers/{r['id']}")["fine_balance"], 1.5)

    def test_in_overdue_report_export_and_notifications(self):
        r = self.reader("Eve")
        loan = self.borrow(r, self.item("Solaris", "audiobook", None))
        self.day("2026-01-10")
        o = self.ok("GET", "/reports/overdue")["overdue"]
        self.assertEqual([(x["loan_id"], x["type"], x["days_overdue"]) for x in o],
                         [(loan["id"], "audiobook", 2)])
        self.assertEqual(self.csv()[1][:4], ["1", "Eve", "Solaris", "audiobook"])
        n = self.ok("GET", f"/readers/{r['id']}/notifications")["notifications"]
        self.assertEqual([(x["kind"], x["title"]) for x in n], [("past_due", "Solaris")])

    def test_cannot_be_reserved(self):
        a, r = self.item("A", "audiobook", None), self.reader()
        self.error("POST", "/reservations", {"reader_id": r["id"], "item_id": a["id"]}, 409, "available")


class GraceDay(TestHTTP):
    def test_first_day_free(self):
        r = self.reader()
        b = self.borrow(r, self.item("B", "book"))       # due 01-15
        f = self.borrow(r, self.item("F", "film"))       # due 01-04
        self.day("2026-01-05")
        self.assertEqual(self.give_back(f)["fine"], 0.0)
        self.day("2026-01-17")
        self.assertEqual(self.give_back(b)["fine"], 1.0)
        self.assertEqual(self.ok("GET", f"/readers/{r['id']}")["fine_balance"], 1.0)

    def test_grace_applies_to_money_not_due_date(self):
        r = self.reader()
        loan = self.borrow(r, self.item("B"))
        other = self.item("Other")
        self.day("2026-01-16")
        self.error("POST", "/loans", {"reader_id": r["id"], "item_id": other["id"]},
                   409, "has_overdue")
        o = self.ok("GET", "/reports/overdue")["overdue"]
        self.assertEqual([(x["loan_id"], x["days_overdue"]) for x in o], [(loan["id"], 1)])
        n = self.ok("GET", f"/readers/{r['id']}/notifications")["notifications"]
        self.assertEqual([x["kind"] for x in n], ["past_due"])

    def test_fine_block_the_new_way(self):
        r = self.reader()
        f = self.borrow(r, self.item("F", "film"))       # due 01-04
        self.day("2026-01-10")                           # 6 days → 5 paid × 2.0 = 10.0
        self.assertEqual(self.give_back(f)["fine"], 10.0)
        i = self.item("B")
        self.error("POST", "/loans", {"reader_id": r["id"], "item_id": i["id"]},
                   409, "fine_block")
        self.assertEqual(self.ok("POST", f"/readers/{r['id']}/payment", {"amount": 0.5})["fine_balance"], 9.5)
        self.borrow(r, i)


class Reservations(TestHTTP):
    def taken(self, copies=1):
        i = self.item("Dune", "book", copies)
        return i, [self.borrow(self.reader(), i) for _ in range(copies)]

    def reserve(self, r, i):
        return self.ok("POST", "/reservations", {"reader_id": r["id"], "item_id": i["id"]}, 201)

    def states(self, i):
        return [x["state"] for x in self.ok("GET", f"/items/{i['id']}/reservations")["reservations"]]

    def test_creating_and_rules(self):
        i, _ = self.taken()
        r = self.reader()
        res = self.reserve(r, i)
        self.assertEqual(res, {"id": 1, "reader_id": r["id"], "item_id": i["id"],
                               "state": "waiting", "date": "2026-01-01", "valid_until": None})
        body = {"reader_id": r["id"], "item_id": i["id"]}
        self.error("POST", "/reservations", body, 409, "already_reserved")
        free = self.item("Free")
        self.error("POST", "/reservations", {"reader_id": r["id"], "item_id": free["id"]}, 409, "available")
        self.error("POST", "/reservations", {"reader_id": 99, "item_id": i["id"]}, 404, "not_found")
        self.error("POST", "/reservations", {"reader_id": r["id"]}, 400, "invalid_data")

    def test_return_sets_copy_aside_for_first_in_queue(self):
        i, (loan,) = self.taken()
        first, second = self.reader(), self.reader()
        self.reserve(first, i)
        self.reserve(second, i)
        self.day("2026-01-05")
        self.give_back(loan)
        res = self.ok("GET", f"/items/{i['id']}/reservations")["reservations"]
        self.assertEqual([(x["state"], x["valid_until"]) for x in res],
                         [("ready_for_pickup", "2026-01-07"), ("waiting", None)])
        self.assertEqual(self.ok("GET", f"/items/{i['id']}")["available"], 0)
        body = {"reader_id": second["id"], "item_id": i["id"]}
        self.error("POST", "/loans", body, 409, "reserved")
        stranger = self.reader()
        self.error("POST", "/loans", {"reader_id": stranger["id"], "item_id": i["id"]},
                   409, "reserved")
        self.borrow(first, i)
        self.assertEqual(self.states(i), ["fulfilled", "waiting"])
        self.error("POST", "/loans", body, 409, "no_copies")

    def test_expiry_on_day_change_passes_it_on(self):
        i, (loan,) = self.taken()
        a, b = self.reader(), self.reader()
        self.reserve(a, i)
        self.reserve(b, i)
        self.day("2026-01-05")
        self.give_back(loan)                             # a: ready_for_pickup until 01-07
        self.day("2026-01-07")
        self.assertEqual(self.states(i), ["ready_for_pickup", "waiting"])
        self.day("2026-01-08")
        res = self.ok("GET", f"/items/{i['id']}/reservations")["reservations"]
        self.assertEqual([(x["state"], x["valid_until"]) for x in res],
                         [("expired", "2026-01-07"), ("ready_for_pickup", "2026-01-10")])
        self.error("POST", "/loans", {"reader_id": a["id"], "item_id": i["id"]},
                   409, "reserved")
        self.borrow(b, i)

    def test_expiry_with_empty_queue_releases_copy(self):
        i, (loan,) = self.taken()
        self.reserve(self.reader(), i)
        self.give_back(loan)
        self.assertEqual(self.ok("GET", f"/items/{i['id']}")["available"], 0)
        self.day("2026-01-04")
        self.assertEqual(self.states(i), ["expired"])
        self.assertEqual(self.ok("GET", f"/items/{i['id']}")["available"], 1)
        self.borrow(self.reader(), i)

    def test_cancelling(self):
        i, (loan,) = self.taken()
        a, b = self.reader(), self.reader()
        ra, rb = self.reserve(a, i), self.reserve(b, i)
        self.give_back(loan)
        self.assertEqual(self.ok("DELETE", f"/reservations/{ra['id']}")["state"], "cancelled")
        self.assertEqual(self.states(i), ["cancelled", "ready_for_pickup"])
        self.error("DELETE", f"/reservations/{ra['id']}", None, 409, "inactive")
        self.error("DELETE", "/reservations/77", None, 404, "not_found")
        self.reserve(a, i)                               # after cancelling, joining again is allowed
        self.assertEqual(self.ok("DELETE", f"/reservations/{rb['id']}")["state"], "cancelled")
        self.assertEqual(self.states(i), ["cancelled", "cancelled", "ready_for_pickup"])

    def test_two_copies_one_set_aside_the_other_free(self):
        i, (l1, l2) = self.taken(2)
        r = self.reader()
        self.reserve(r, i)
        self.give_back(l1)                               # set aside for r
        self.give_back(l2)                               # this one is free for everybody
        self.assertEqual(self.ok("GET", f"/items/{i['id']}")["available"], 1)
        self.borrow(self.reader(), i)
        self.error("POST", "/loans", {"reader_id": self.reader()["id"],
                                      "item_id": i["id"]}, 409, "reserved")
        self.borrow(r, i)

    def test_reserving_reader_is_subject_to_other_rules(self):
        i, (loan,) = self.taken()
        r = self.reader()
        old = self.borrow(r, self.item("Old", "film"))   # due 01-04
        self.reserve(r, i)
        self.day("2026-01-05")
        self.give_back(loan)
        self.error("POST", "/loans", {"reader_id": r["id"], "item_id": i["id"]},
                   409, "has_overdue")
        self.give_back(old)
        self.borrow(r, i)


if __name__ == "__main__":
    unittest.main()
