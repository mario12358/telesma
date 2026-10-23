import sqlite3
import subprocess
import sys
import threading
import unittest

from helpers import ROOT_DIR, ServiceProcess, TestWithService, send
from library import db
from library.protocol import json_response
from library.routes import Route
from library.server import Application, LibraryServer

SCHEMA_TABLES = {"settings", "items", "readers", "loans"}


def tables(db_path) -> set[str]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {row[0] for row in rows}
    finally:
        connection.close()


class TestStartup(TestWithService):
    def test_health_running_service_returns_200_ok(self):
        response = self.request("GET", "/health")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(response.headers["Content-Type"], "application/json")

    def test_start_nonexistent_db_file_creates_schema(self):
        self.assertLessEqual(SCHEMA_TABLES, tables(self.service.db_path))

    def test_start_empty_db_file_creates_schema(self):
        path = self.directory / "empty.sqlite"
        path.touch()
        service = ServiceProcess(path, self.directory / "empty.log")
        service.start()
        self.addCleanup(service.stop)

        self.assertLessEqual(SCHEMA_TABLES, tables(path))

    def test_restart_on_the_same_db_does_not_break_schema(self):
        self.service.stop()
        self.service.start()

        self.assertEqual(self.request("GET", "/health").status, 200)

    def test_unknown_path_returns_404_not_found(self):
        self.assert_error(self.request("GET", "/not-here"), 404, "not_found")

    def test_known_path_other_method_returns_404_not_found(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                self.assert_error(self.request(method, "/health"), 404, "not_found")

    def test_health_with_query_params_returns_200(self):
        self.assertEqual(self.request("GET", "/health?x=1").status, 200)


class TestStartupParameters(unittest.TestCase):
    def test_start_without_required_parameter_exits_with_error(self):
        for arguments in (["--port", "8000"], ["--db", "db.sqlite"], []):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, "-m", "library", *arguments],
                    cwd=ROOT_DIR, capture_output=True, timeout=10,
                )
                self.assertEqual(result.returncode, 2)


def echo(request):
    return json_response(200, request.json_object())


class TestRequestBody(unittest.TestCase):
    """JSON parsing checked over HTTP on a route injected into the Application."""

    def setUp(self):
        connection = db.open_db(":memory:")
        self.addCleanup(connection.close)
        application = Application(connection, routes=(Route("POST", r"/echo", echo),))
        server = LibraryServer(0, application)
        self.port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def assert_invalid_data(self, body: bytes):
        response = send(self.port, "POST", "/echo", body=body)
        self.assertEqual((response.status, response.json()), (400, {"error": "invalid_data"}))

    def test_json_object_valid_object_reaches_handler(self):
        response = send(self.port, "POST", "/echo", data={"title": "Crème brûlée"})

        self.assertEqual((response.status, response.json()), (200, {"title": "Crème brûlée"}))

    def test_json_object_invalid_json_returns_400(self):
        self.assert_invalid_data(b'{"title": ')

    def test_json_object_empty_body_returns_400(self):
        self.assert_invalid_data(b"")

    def test_json_object_value_other_than_object_returns_400(self):
        for body in (b"[1, 2]", b'"string"', b"7", b"null"):
            with self.subTest(body=body):
                self.assert_invalid_data(body)

    def test_json_object_non_utf8_bytes_returns_400(self):
        self.assert_invalid_data(b'{"title": "\xff"}')

    def test_unknown_path_with_invalid_json_returns_404(self):
        response = send(self.port, "POST", "/other", body=b"{")

        self.assertEqual((response.status, response.json()), (404, {"error": "not_found"}))


if __name__ == "__main__":
    unittest.main()
