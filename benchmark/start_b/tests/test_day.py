import unittest

from helpers import TestWithService


class TestSystemDay(TestWithService):
    def set(self, date):
        return self.request("POST", "/system/day", data={"date": date})

    def assert_day(self, expected: str):
        response = self.request("GET", "/system/day")
        self.assertEqual((response.status, response.json()), (200, {"date": expected}))

    def test_get_day_new_db_returns_2026_01_01(self):
        self.assert_day("2026-01-01")

    def test_set_day_later_date_changes_day(self):
        response = self.set("2026-03-15")

        self.assertEqual((response.status, response.json()), (200, {"date": "2026-03-15"}))
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assert_day("2026-03-15")

    def test_set_day_earlier_date_returns_400_date_in_past(self):
        self.set("2026-03-15")

        self.assert_error(self.set("2026-03-14"), 400, "date_in_past")
        self.assert_day("2026-03-15")

    def test_set_day_a_year_back_despite_later_day_of_month(self):
        self.assert_error(self.set("2025-12-31"), 400, "date_in_past")

    def test_set_day_same_date_is_allowed(self):
        self.set("2026-03-15")

        response = self.set("2026-03-15")

        self.assertEqual((response.status, response.json()), (200, {"date": "2026-03-15"}))
        self.assert_day("2026-03-15")

    def test_set_day_malformed_date_returns_400(self):
        bad_dates = (
            "2026-13-01", "2026-02-30", "2026-1-5", "20260301", "2026-W10-1",
            "15-03-2026", "2026-03-15T00:00:00", " 2026-03-15", "", "tomorrow",
            20260315, None, True, ["2026-03-15"],
        )
        for date in bad_dates:
            with self.subTest(date=date):
                self.assert_error(self.set(date), 400, "invalid_data")
        self.assert_day("2026-01-01")

    def test_set_day_missing_date_field_returns_400(self):
        response = self.request("POST", "/system/day", data={"day": "2026-03-15"})

        self.assert_error(response, 400, "invalid_data")

    def test_set_day_invalid_json_returns_400(self):
        for body in (b'{"date": ', b"", b'["2026-03-15"]'):
            with self.subTest(body=body):
                response = self.request("POST", "/system/day", body=body)
                self.assert_error(response, 400, "invalid_data")

    def test_day_survives_process_restart_on_same_file(self):
        self.set("2026-07-04")

        self.service.stop()
        self.service.start()

        self.assert_day("2026-07-04")


if __name__ == "__main__":
    unittest.main()
