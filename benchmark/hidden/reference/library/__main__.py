"""REFERENCE implementation of the benchmark — it exists so that the hidden tests have something
to prove their own correctness on. Telesma never sees it (the harness copies into the workspace
only `benchmark/project/` and `benchmark/changes/`).

`--stage A` = the specification alone, `--stage B` (default) = specification + four change requests.
The `REFERENCE_FAULT` variable switches on deliberate faults — the judge's tests must CATCH them
(`check_judge.py`): that is the proof that the judge catches the defect classes it was built for.
"""
import argparse
import csv
import datetime
import io
import json
import os
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAULTS = set(filter(None, os.environ.get("REFERENCE_FAULT", "").split(",")))
DAYS = {"book": 14, "film": 3, "audiobook": 7}
RATE = {"book": 1.0, "film": 2.0, "audiobook": 0.5}
LOCK = threading.Lock()

DDL = """
CREATE TABLE IF NOT EXISTS system (name TEXT PRIMARY KEY, value TEXT);
INSERT OR IGNORE INTO system VALUES ('day', '2026-01-01');
CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, type TEXT,
    copies INTEGER);
CREATE TABLE IF NOT EXISTS readers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,
    email TEXT, fine_balance REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS loans (id INTEGER PRIMARY KEY AUTOINCREMENT, reader_id INT,
    item_id INT, loan_date TEXT, due_date TEXT, return_date TEXT, fine REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, reader_id INT,
    kind TEXT, loan_id INT, date TEXT, UNIQUE(kind, loan_id));
CREATE TABLE IF NOT EXISTS reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, reader_id INT,
    item_id INT, state TEXT, date TEXT, valid_until TEXT);
"""


class Error(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def parse_date(s):
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise Error(400, "invalid_data")
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        raise Error(400, "invalid_data")


class App:
    def __init__(self, path, stage):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(DDL)
        self.b = stage == "B"

    # --- helpers
    def today(self):
        return datetime.date.fromisoformat(
            self.db.execute("SELECT value FROM system WHERE name='day'").fetchone()[0])

    def one(self, table, ident):
        r = self.db.execute(f"SELECT * FROM {table} WHERE id=?", [ident]).fetchone()
        if not r:
            raise Error(404, "not_found")
        return r

    def set_aside(self, iid):
        return self.db.execute("SELECT COUNT(*) FROM reservations WHERE item_id=? AND "
                               "state='ready_for_pickup'", [iid]).fetchone()[0]

    def free(self, i):
        """Copies not on loan (including the ones set aside)."""
        taken = self.db.execute("SELECT COUNT(*) FROM loans WHERE item_id=? AND "
                                "return_date IS NULL", [i["id"]]).fetchone()[0]
        return i["copies"] - taken

    def item(self, i):
        if i["type"] == "audiobook":
            return dict(id=i["id"], title=i["title"], type=i["type"], copies=None, available=None)
        return dict(id=i["id"], title=i["title"], type=i["type"], copies=i["copies"],
                    available=self.free(i) - self.set_aside(i["id"]))

    @staticmethod
    def reader(r):
        return dict(id=r["id"], name=r["name"], email=r["email"],
                    fine_balance=round(r["fine_balance"], 2))

    @staticmethod
    def loan(w):
        return dict(id=w["id"], reader_id=w["reader_id"], item_id=w["item_id"],
                    loan_date=w["loan_date"], due_date=w["due_date"],
                    return_date=w["return_date"], fine=round(w["fine"], 2))

    @staticmethod
    def reservation(r):
        return dict(id=r["id"], reader_id=r["reader_id"], item_id=r["item_id"],
                    state=r["state"], date=r["date"], valid_until=r["valid_until"])

    def types(self):
        return ("book", "film", "audiobook") if self.b else ("book", "film")

    # --- system
    def set_day(self, body):
        new = parse_date(body.get("date"))
        old = self.today()
        if new < old:
            raise Error(400, "date_in_past")
        self.db.execute("UPDATE system SET value=? WHERE name='day'", [new.isoformat()])
        if self.b and new > old:
            if "reminders_not_wired" not in FAULTS:
                self.reminders(new)
            if "expiry_not_wired" not in FAULTS:
                self.expiry(new)
        return 200, {"date": new.isoformat()}

    def reminders(self, today):
        for w in self.db.execute("SELECT * FROM loans WHERE return_date IS NULL").fetchall():
            due = datetime.date.fromisoformat(w["due_date"])
            kind = "past_due" if today > due else \
                "due_tomorrow" if (due - today).days == 1 else None
            if kind:
                self.db.execute("INSERT OR IGNORE INTO notifications (reader_id, kind, "
                                "loan_id, date) VALUES (?,?,?,?)",
                                [w["reader_id"], kind, w["id"], today.isoformat()])

    def pass_copy_on(self, iid, today):
        nxt = self.db.execute("SELECT id FROM reservations WHERE item_id=? AND state='waiting' "
                              "ORDER BY id LIMIT 1", [iid]).fetchone()
        if nxt:
            self.db.execute("UPDATE reservations SET state='ready_for_pickup', valid_until=? WHERE id=?",
                            [(today + datetime.timedelta(days=2)).isoformat(), nxt["id"]])

    def expiry(self, today):
        for r in self.db.execute("SELECT * FROM reservations WHERE state='ready_for_pickup' ORDER BY id"
                                 ).fetchall():
            if today > datetime.date.fromisoformat(r["valid_until"]):
                self.db.execute("UPDATE reservations SET state='expired' WHERE id=?", [r["id"]])
                self.pass_copy_on(r["item_id"], today)

    # --- items and readers
    def new_item(self, c):
        title, typ, copies = c.get("title"), c.get("type"), c.get("copies")
        if not isinstance(title, str) or not title.strip() or typ not in self.types():
            raise Error(400, "invalid_data")
        if typ == "audiobook":
            copies = None
        elif not isinstance(copies, int) or isinstance(copies, bool) or copies < 1:
            raise Error(400, "invalid_data")
        ident = self.db.execute("INSERT INTO items (title, type, copies) VALUES (?,?,?)",
                                [title, typ, copies]).lastrowid
        return 201, self.item(self.one("items", ident))

    def item_list(self, q):
        typ = q.get("type")
        if typ is not None and typ not in self.types():
            raise Error(400, "invalid_data")
        if typ == "audiobook" and "audiobook_missing_from_filter" in FAULTS:
            raise Error(400, "invalid_data")
        rows = self.db.execute("SELECT * FROM items" + (" WHERE type=?" if typ else "")
                               + " ORDER BY id", [typ] if typ else []).fetchall()
        return 200, {"items": [self.item(i) for i in rows]}

    def new_reader(self, c):
        name, email = c.get("name"), c.get("email")
        if not isinstance(name, str) or not name.strip() or not isinstance(email, str) \
                or "@" not in email:
            raise Error(400, "invalid_data")
        if self.db.execute("SELECT 1 FROM readers WHERE lower(email)=lower(?)", [email]).fetchone():
            raise Error(409, "email_taken")
        ident = self.db.execute("INSERT INTO readers (name, email) VALUES (?,?)",
                                [name, email]).lastrowid
        return 201, self.reader(self.one("readers", ident))

    def payment(self, ident, c):
        rd = self.one("readers", ident)
        amount = c.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
            raise Error(400, "invalid_data")
        if amount > round(rd["fine_balance"], 2):
            raise Error(409, "overpayment")
        self.db.execute("UPDATE readers SET fine_balance=fine_balance-? WHERE id=?", [amount, ident])
        return 200, self.reader(self.one("readers", ident))

    # --- loans
    def borrow(self, c):
        rid, iid = c.get("reader_id"), c.get("item_id")
        if not isinstance(rid, int) or not isinstance(iid, int):
            raise Error(400, "invalid_data")
        rd, i = self.one("readers", rid), self.one("items", iid)
        today = self.today()
        active = self.db.execute("SELECT * FROM loans WHERE reader_id=? AND "
                                 "return_date IS NULL", [rid]).fetchall()
        if round(rd["fine_balance"], 2) >= 10.0:
            raise Error(409, "fine_block")
        if any(today > datetime.date.fromisoformat(w["due_date"]) for w in active):
            raise Error(409, "has_overdue")
        counted = active
        if "limit_without_audiobook" in FAULTS:
            types = {x["id"]: x["type"] for x in self.db.execute("SELECT id, type FROM items")}
            counted = [w for w in active if types[w["item_id"]] != "audiobook"]
        if len(counted) >= 3:
            raise Error(409, "loan_limit")
        mine = None
        if i["type"] == "audiobook":
            if any(w["item_id"] == iid for w in active):
                raise Error(409, "already_borrowed")
        else:
            mine = self.db.execute("SELECT id FROM reservations WHERE item_id=? AND reader_id=? "
                                   "AND state='ready_for_pickup'", [iid, rid]).fetchone()
            free = self.free(i)
            if not mine:
                if free - self.set_aside(iid) <= 0:
                    raise Error(409, "reserved" if free > 0 else "no_copies")
        ident = self.db.execute(
            "INSERT INTO loans (reader_id, item_id, loan_date, due_date) "
            "VALUES (?,?,?,?)", [rid, iid, today.isoformat(),
                                 (today + datetime.timedelta(days=DAYS[i["type"]])).isoformat()]).lastrowid
        if mine:
            self.db.execute("UPDATE reservations SET state='fulfilled' WHERE id=?", [mine["id"]])
        return 201, self.loan(self.one("loans", ident))

    def give_back(self, ident):
        w = self.one("loans", ident)
        if w["return_date"]:
            raise Error(409, "already_returned")
        i, today = self.one("items", w["item_id"]), self.today()
        days = max(0, (today - datetime.date.fromisoformat(w["due_date"])).days)
        if self.b:
            days = max(0, days - 1)
        fine = days * RATE[i["type"]]
        self.db.execute("UPDATE loans SET return_date=?, fine=? WHERE id=?",
                        [today.isoformat(), fine, ident])
        self.db.execute("UPDATE readers SET fine_balance=fine_balance+? WHERE id=?",
                        [fine, w["reader_id"]])
        if self.b and i["type"] != "audiobook":
            self.pass_copy_on(i["id"], today)
        return 200, self.loan(self.one("loans", ident))

    def reader_loans(self, ident, q):
        self.one("readers", ident)
        state = q.get("state", "active")
        if state not in ("active", "all"):
            raise Error(400, "invalid_data")
        rows = self.db.execute(
            "SELECT * FROM loans WHERE reader_id=?"
            + (" AND return_date IS NULL" if state == "active" else "") + " ORDER BY id", [ident])
        return 200, {"loans": [self.loan(w) for w in rows.fetchall()]}

    # --- reports
    def overdue(self):
        today, out = self.today(), []
        for w in self.db.execute("SELECT w.*, i.title, i.type FROM loans w JOIN items i "
                                 "ON i.id=w.item_id WHERE w.return_date IS NULL ORDER BY w.id"):
            days = (today - datetime.date.fromisoformat(w["due_date"])).days
            if days > 0 and not (w["type"] == "audiobook" and "audiobook_missing_from_report" in FAULTS):
                out.append(dict(loan_id=w["id"], reader_id=w["reader_id"],
                                item_id=w["item_id"], title=w["title"], type=w["type"],
                                due_date=w["due_date"], days_overdue=days))
        return 200, {"overdue": out}

    def export(self):
        buf = io.StringIO()
        k = csv.writer(buf, lineterminator="\n")
        k.writerow(["id", "reader", "title", "type", "loan_date", "due_date",
                    "return_date", "fine"])
        for w in self.db.execute("SELECT w.*, i.title, i.type, r.name FROM loans w JOIN "
                                 "items i ON i.id=w.item_id JOIN readers r ON "
                                 "r.id=w.reader_id ORDER BY w.id"):
            k.writerow([w["id"], w["name"], w["title"], w["type"], w["loan_date"],
                        w["due_date"], w["return_date"] or "", f"{w['fine']:.2f}"])
        return 200, buf.getvalue()

    # --- stage B: notifications and reservations
    def notifications(self, ident):
        self.one("readers", ident)
        rows = self.db.execute("SELECT n.*, i.title FROM notifications n JOIN loans w ON "
                               "w.id=n.loan_id JOIN items i ON i.id=w.item_id "
                               "WHERE n.reader_id=? ORDER BY n.id", [ident]).fetchall()
        return 200, {"notifications": [dict(id=n["id"], kind=n["kind"], title=n["title"],
                                            loan_id=n["loan_id"], date=n["date"])
                                       for n in rows]}

    def reserve(self, c):
        rid, iid = c.get("reader_id"), c.get("item_id")
        if not isinstance(rid, int) or not isinstance(iid, int):
            raise Error(400, "invalid_data")
        self.one("readers", rid)
        i = self.one("items", iid)
        if i["type"] == "audiobook" or self.free(i) - self.set_aside(iid) > 0:
            raise Error(409, "available")
        if self.db.execute("SELECT 1 FROM reservations WHERE reader_id=? AND item_id=? AND "
                           "state IN ('waiting','ready_for_pickup')", [rid, iid]).fetchone():
            raise Error(409, "already_reserved")
        ident = self.db.execute("INSERT INTO reservations (reader_id, item_id, state, date) "
                                "VALUES (?,?,'waiting',?)", [rid, iid, self.today().isoformat()]
                                ).lastrowid
        return 201, self.reservation(self.one("reservations", ident))

    def cancel(self, ident):
        r = self.one("reservations", ident)
        if r["state"] not in ("waiting", "ready_for_pickup"):
            raise Error(409, "inactive")
        self.db.execute("UPDATE reservations SET state='cancelled' WHERE id=?", [ident])
        if r["state"] == "ready_for_pickup":
            self.pass_copy_on(r["item_id"], self.today())
        return 200, self.reservation(self.one("reservations", ident))

    def item_reservations(self, ident):
        self.one("items", ident)
        return 200, {"reservations": [self.reservation(r) for r in self.db.execute(
            "SELECT * FROM reservations WHERE item_id=? ORDER BY id", [ident]).fetchall()]}

    # --- routing
    def handle(self, method, path, q, body):
        def m(pattern):
            d = re.fullmatch(pattern, path)
            return [int(x) for x in d.groups()] if d else None
        if (method, path) == ("GET", "/health"):
            return 200, {"ok": True}
        if path == "/system/day":
            return (200, {"date": self.today().isoformat()}) if method == "GET" else \
                self.set_day(body)
        if path == "/items":
            return self.item_list(q) if method == "GET" else self.new_item(body)
        if (a := m(r"/items/(\d+)")) and method == "GET":
            return 200, self.item(self.one("items", a[0]))
        if (method, path) == ("POST", "/readers"):
            return self.new_reader(body)
        if (a := m(r"/readers/(\d+)")) and method == "GET":
            return 200, self.reader(self.one("readers", a[0]))
        if (a := m(r"/readers/(\d+)/payment")) and method == "POST":
            return self.payment(a[0], body)
        if (a := m(r"/readers/(\d+)/loans")) and method == "GET":
            return self.reader_loans(a[0], q)
        if (method, path) == ("POST", "/loans"):
            return self.borrow(body)
        if (a := m(r"/loans/(\d+)")) and method == "GET":
            return 200, self.loan(self.one("loans", a[0]))
        if (a := m(r"/loans/(\d+)/return")) and method == "POST":
            return self.give_back(a[0])
        if (method, path) == ("GET", "/reports/overdue"):
            return self.overdue()
        if (method, path) == ("GET", "/reports/loans.csv"):
            return self.export()
        if self.b:
            if (a := m(r"/readers/(\d+)/notifications")) and method == "GET":
                return self.notifications(a[0])
            if (method, path) == ("POST", "/reservations"):
                return self.reserve(body)
            if (a := m(r"/reservations/(\d+)")) and method == "DELETE":
                return self.cancel(a[0])
            if (a := m(r"/items/(\d+)/reservations")) and method == "GET":
                return self.item_reservations(a[0])
        raise Error(404, "not_found")


def server(app, port):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _handle(self):
            path, _, query = self.path.partition("?")
            q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw) if raw else {}
                except ValueError:
                    raise Error(400, "invalid_data")
                if not isinstance(body, dict):
                    raise Error(400, "invalid_data")
                with LOCK:
                    status, result = app.handle(self.command, path, q, body)
                    app.db.commit()
            except Error as e:
                app.db.rollback()
                status, result = e.status, {"error": e.code}
            content = result.encode() if isinstance(result, str) else json.dumps(result).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/csv; charset=utf-8" if isinstance(result, str)
                             else "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_GET = do_POST = do_DELETE = _handle

    return ThreadingHTTPServer(("127.0.0.1", port), H)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--stage", default=os.environ.get("REFERENCE_STAGE", "B"), choices=["A", "B"])
    a = ap.parse_args()
    server(App(a.db, a.stage), a.port).serve_forever()
