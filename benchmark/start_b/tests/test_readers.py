import unittest

from helpers import TestWithService

VALID = {"name": "Anna Smith", "email": "anna@example.com"}


class TestReaderCreation(TestWithService):
    def test_create_valid_data_returns_201_and_full_reader(self):
        response = self.request("POST", "/readers", data=VALID)

        self.assertEqual(response.status, 201)
        self.assertEqual(
            response.json(),
            {"id": 1, "name": "Anna Smith", "email": "anna@example.com", "fine_balance": 0.0},
        )

    def test_create_email_comes_back_in_original_case(self):
        reader = self.add_reader(email="Anna.Smith@Example.COM")

        self.assertEqual(reader["email"], "Anna.Smith@Example.COM")

    def test_create_subsequent_readers_get_ascending_ids_from_1(self):
        first = self.add_reader(email="a@example.com")
        second = self.add_reader(email="b@example.com")

        self.assertEqual((first["id"], second["id"]), (1, 2))

    def test_create_invalid_field_returns_400(self):
        bad_fields = (
            ("name", ""), ("name", "  "), ("name", 5), ("name", None),
            ("email", "anna.example.com"), ("email", ""), ("email", 5), ("email", None),
            ("email", ["anna@example.com"]),
        )
        for field, value in bad_fields:
            with self.subTest(field=field, value=value):
                response = self.request("POST", "/readers", data={**VALID, field: value})
                self.assert_error(response, 400, "invalid_data")

    def test_create_missing_required_field_returns_400(self):
        for field in VALID:
            with self.subTest(missing=field):
                data = {key: value for key, value in VALID.items() if key != field}
                self.assert_error(self.request("POST", "/readers", data=data), 400, "invalid_data")

    def test_create_invalid_json_returns_400(self):
        self.assert_error(self.request("POST", "/readers", body=b"name=Anna"), 400, "invalid_data")


class TestDuplicateEmail(TestWithService):
    def test_create_same_email_returns_409_email_taken(self):
        self.add_reader(name="Anna", email="anna@example.com")

        response = self.request("POST", "/readers", data={"name": "Another Anna", "email": "anna@example.com"})

        self.assert_error(response, 409, "email_taken")

    def test_create_email_differing_in_case_returns_409(self):
        self.add_reader(name="Anna", email="Anna@Example.com")

        for email in ("anna@example.com", "ANNA@EXAMPLE.COM", "aNNa@exAMPLE.Com"):
            with self.subTest(email=email):
                response = self.request("POST", "/readers", data={"name": "Copy", "email": email})
                self.assert_error(response, 409, "email_taken")

    def test_create_email_with_non_ascii_characters_differing_in_case_returns_409(self):
        self.add_reader(name="Élodie", email="élodie@example.com")

        response = self.request("POST", "/readers", data={"name": "Copy", "email": "ÉLODIE@example.com"})

        self.assert_error(response, 409, "email_taken")

    def test_create_duplicate_creates_no_reader_and_another_email_passes(self):
        self.add_reader(email="anna@example.com")
        self.request("POST", "/readers", data={"name": "Copy", "email": "ANNA@example.com"})

        another = self.add_reader(name="John", email="john@example.com")

        self.assertEqual(self.request("GET", "/readers/1").json()["name"], "Anna Smith")
        self.assertEqual(self.request("GET", f"/readers/{another['id']}").json()["email"], "john@example.com")
        self.assert_error(self.request("GET", f"/readers/{another['id'] + 1}"), 404, "not_found")

    def test_create_invalid_data_takes_precedence_over_duplicate(self):
        self.add_reader(email="anna@example.com")

        response = self.request("POST", "/readers", data={"name": "", "email": "anna@example.com"})

        self.assert_error(response, 400, "invalid_data")


class TestReaderRead(TestWithService):
    def test_get_existing_reader_returns_200_with_balance(self):
        self.add_reader(name="Anna", email="anna@example.com")
        self.add_reader(name="John", email="john@example.com")

        response = self.request("GET", "/readers/2")

        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.json(),
            {"id": 2, "name": "John", "email": "john@example.com", "fine_balance": 0.0},
        )

    def test_get_nonexistent_id_returns_404(self):
        self.add_reader()

        for path in ("/readers/2", "/readers/0", "/readers/abc", "/readers"):
            with self.subTest(path=path):
                self.assert_error(self.request("GET", path), 404, "not_found")


if __name__ == "__main__":
    unittest.main()
