"""Starting a real service process for the tests."""

import http.client
import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ADDRESS = "127.0.0.1"
STARTUP_TIMEOUT = 10.0


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind((ADDRESS, 0))
        return sock.getsockname()[1]


@dataclass(frozen=True)
class ServiceResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body.decode("utf-8"))


def send(port: int, method: str, path: str, data=None, body: bytes | None = None):
    if data is not None:
        body = json.dumps(data).encode("utf-8")
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection = http.client.HTTPConnection(ADDRESS, port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return ServiceResponse(
            response.status, dict(response.getheaders()), response.read()
        )
    finally:
        connection.close()


class ServiceProcess:
    def __init__(self, db_path: Path, log: Path) -> None:
        self.db_path = db_path
        self.port = free_port()
        self._log = log
        self._process: subprocess.Popen | None = None

    def start(self) -> None:
        with self._log.open("ab") as output:
            self._process = subprocess.Popen(
                [sys.executable, "-m", "library",
                 "--port", str(self.port), "--db", str(self.db_path)],
                cwd=ROOT_DIR, stdout=output, stderr=output,
            )
        self._wait_until_ready()

    def stop(self) -> None:
        if self._process is None:
            return
        self._process.terminate()
        self._process.wait(timeout=10)
        self._process = None

    def request(self, method: str, path: str, data=None, body: bytes | None = None):
        return send(self.port, method, path, data, body)

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                break
            try:
                send(self.port, "GET", "/health")
                return
            except OSError:
                time.sleep(0.02)
        self.stop()
        raise RuntimeError(f"the service did not start: {self._log.read_text()}")


class TestWithService(unittest.TestCase):
    """Every test gets its own service process on a fresh database."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.service = ServiceProcess(self.directory / "db.sqlite", self.directory / "service.log")
        self.service.start()
        self.addCleanup(self.service.stop)

    def request(self, method: str, path: str, data=None, body: bytes | None = None):
        return self.service.request(method, path, data, body)

    def add_item(self, title: str = "The Doll", type: str = "book", copies: int = 1) -> dict:
        response = self.request(
            "POST", "/items", data={"title": title, "type": type, "copies": copies}
        )
        self.assertEqual(response.status, 201, response.body)
        return response.json()

    def add_reader(self, name: str = "Anna Smith", email: str = "anna@example.com") -> dict:
        response = self.request("POST", "/readers", data={"name": name, "email": email})
        self.assertEqual(response.status, 201, response.body)
        return response.json()

    def borrow(self, reader_id: int, item_id: int) -> dict:
        response = self.try_borrow(reader_id, item_id)
        self.assertEqual(response.status, 201, response.body)
        return response.json()

    def try_borrow(self, reader_id: int, item_id: int) -> ServiceResponse:
        return self.request(
            "POST", "/loans", data={"reader_id": reader_id, "item_id": item_id}
        )

    def give_back(self, loan_id: int) -> dict:
        response = self.request("POST", f"/loans/{loan_id}/return")
        self.assertEqual(response.status, 200, response.body)
        return response.json()

    def balance(self, reader_id: int) -> float:
        return self.request("GET", f"/readers/{reader_id}").json()["fine_balance"]

    def set_day(self, date: str) -> None:
        response = self.request("POST", "/system/day", data={"date": date})
        self.assertEqual(response.status, 200, response.body)

    def set_balance_in_db(self, reader_id: int, cents: int) -> None:
        """Balance without going through returns: the service commits every request, so the file is free."""
        connection = sqlite3.connect(self.service.db_path)
        try:
            with connection:
                connection.execute(
                    "UPDATE readers SET fine_balance_cents = ? WHERE id = ?", (cents, reader_id)
                )
        finally:
            connection.close()

    def assert_error(self, response: ServiceResponse, status: int, code: str) -> None:
        self.assertEqual((response.status, response.json()), (status, {"error": code}))
