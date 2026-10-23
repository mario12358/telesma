"""Shared part of the hidden tests: a fresh server and a fresh database for EVERY test, HTTP only.

The judge imports nothing from the project under evaluation — it only knows the contract from the
specification (`python3 -m library --port N --db FILE`). That way it measures what a user would
see, not what the author of the code considered worth testing.

  BENCH_PROJECT  directory the `library` package is started from
  BENCH_STAGE    A | B
"""
import csv
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

PROJECT = os.environ.get("BENCH_PROJECT", ".")
STAGE = os.environ.get("BENCH_STAGE", "A")
START_S = 15


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.port = free_port()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "library", "--port", str(self.port),
             "--db", os.path.join(self.tmp.name, "db.sqlite")],
            cwd=PROJECT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + START_S
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self.fail("the server exited right after start")
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1)
                return
            except OSError:
                time.sleep(0.05)
        self.fail(f"the server does not answer /health after {START_S} s")

    def tearDown(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.tmp.cleanup()

    # --- HTTP
    def raw(self, method, path, body=None, text=None):
        data = text.encode() if text is not None else \
            json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                     method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type", ""), e.read().decode("utf-8")

    def http(self, method, path, body=None):
        status, _, content = self.raw(method, path, body)
        try:
            return status, json.loads(content) if content else None
        except ValueError:
            self.fail(f"{method} {path}: the response is not JSON: {content[:200]!r}")

    def ok(self, method, path, body=None, status=200):
        s, j = self.http(method, path, body)
        self.assertEqual(s, status, f"{method} {path} → {s} {j}")
        return j

    def error(self, method, path, body, status, code):
        s, j = self.http(method, path, body)
        self.assertEqual((s, (j or {}).get("error")), (status, code), f"{method} {path} → {s} {j}")

    # --- domain shortcuts
    def day(self, date):
        return self.ok("POST", "/system/day", {"date": date})

    def item(self, title="The Doll", type="book", copies=1):
        body = {"title": title, "type": type}
        if copies is not None:
            body["copies"] = copies
        return self.ok("POST", "/items", body, 201)

    def reader(self, name="Anna Smith", email=None):
        self._n = getattr(self, "_n", 0) + 1
        return self.ok("POST", "/readers",
                       {"name": name, "email": email or f"r{self._n}@example.com"}, 201)

    def borrow(self, r, i):
        return self.ok("POST", "/loans", {"reader_id": r["id"], "item_id": i["id"]}, 201)

    def give_back(self, loan):
        return self.ok("POST", f"/loans/{loan['id']}/return")

    def csv(self):
        status, ctype, content = self.raw("GET", "/reports/loans.csv")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("text/csv"), ctype)
        return list(csv.reader(io.StringIO(content)))
