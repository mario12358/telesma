"""Loans: due dates, returns and fines."""

import sqlite3
from datetime import date, timedelta

from library import amounts, items, readers, system, validation
from library.errors import NotFound, RuleViolation
from library.protocol import HttpRequest, Response, json_response

DAYS_UNTIL_DUE = {"book": 14, "film": 3}
DAILY_RATE_CENTS = {"book": 100, "film": 200}
BLOCK_THRESHOLD_CENTS = 1000
LOAN_LIMIT = 3
STATE_ALL = "all"


def create(request: HttpRequest) -> Response:
    data = request.json_object()
    reader_id = validation.identifier(data, "reader_id")
    item_id = validation.identifier(data, "item_id")
    connection = request.connection
    balance = readers.balance_cents(connection, reader_id)
    item = items.find(connection, item_id)
    today = system.today(connection)
    _check_rules(connection, reader_id, balance, item, today)
    due_date = today + timedelta(days=DAYS_UNTIL_DUE[item["type"]])
    cursor = connection.execute(
        "INSERT INTO loans (reader_id, item_id, loan_date, due_date)"
        " VALUES (?, ?, ?, ?)",
        (reader_id, item["id"], today.isoformat(), due_date.isoformat()),
    )
    return json_response(201, find(connection, cursor.lastrowid))


def _check_rules(
    connection: sqlite3.Connection, reader_id: int, balance: int, item: dict, today: date
) -> None:
    # The order is part of the contract: with several violations the first rule wins.
    if balance >= BLOCK_THRESHOLD_CENTS:
        raise RuleViolation("fine_block")
    if _unreturned_count(connection, reader_id, due_before=today) > 0:
        raise RuleViolation("has_overdue")
    if _unreturned_count(connection, reader_id) >= LOAN_LIMIT:
        raise RuleViolation("loan_limit")
    if item["available"] < 1:
        raise RuleViolation("no_copies")


def _unreturned_count(
    connection: sqlite3.Connection, reader_id: int, due_before: date | None = None
) -> int:
    cutoff = due_before.isoformat() if due_before else None
    row = connection.execute(
        "SELECT COUNT(id) AS count FROM loans"
        " WHERE reader_id = :reader_id AND state = 'on_loan'"
        " AND (:cutoff IS NULL OR due_date < :cutoff)",
        {"reader_id": reader_id, "cutoff": cutoff},
    ).fetchone()
    return row["count"]


def give_back(request: HttpRequest) -> Response:
    (loan_id,) = request.identifiers
    connection = request.connection
    row = _unreturned(connection, loan_id)
    today = system.today(connection)
    fine = _fine_cents(row["type"], date.fromisoformat(row["due_date"]), today)
    connection.execute(
        "UPDATE loans SET state = 'returned', return_date = ?, fine_cents = ?"
        " WHERE id = ?",
        (today.isoformat(), fine, loan_id),
    )
    readers.change_balance(connection, row["reader_id"], fine)
    return json_response(200, find(connection, loan_id))


def _unreturned(connection: sqlite3.Connection, loan_id: int) -> sqlite3.Row:
    row = connection.execute(
        "SELECT l.reader_id, l.due_date, l.state, i.type FROM loans AS l"
        " JOIN items AS i ON i.id = l.item_id WHERE l.id = ?",
        (loan_id,),
    ).fetchone()
    if row is None:
        raise NotFound()
    if row["state"] == "returned":
        raise RuleViolation("already_returned")
    return row


def _fine_cents(item_type: str, due_date: date, today: date) -> int:
    days_overdue = max(0, (today - due_date).days)
    return days_overdue * DAILY_RATE_CENTS[item_type]


def reader_list(request: HttpRequest) -> Response:
    (reader_id,) = request.identifiers
    with_returned = False
    if "state" in request.params:
        validation.one_of(request.params["state"], (STATE_ALL,))
        with_returned = True
    readers.find(request.connection, reader_id)
    rows = request.connection.execute(
        "SELECT id, reader_id, item_id, loan_date, due_date, return_date,"
        " fine_cents FROM loans"
        " WHERE reader_id = :reader_id AND (:with_returned OR state = 'on_loan')"
        " ORDER BY id",
        {"reader_id": reader_id, "with_returned": with_returned},
    )
    return json_response(200, {"loans": [as_json(row) for row in rows]})


def get(request: HttpRequest) -> Response:
    (loan_id,) = request.identifiers
    return json_response(200, find(request.connection, loan_id))


def find(connection: sqlite3.Connection, loan_id: int) -> dict:
    row = connection.execute(
        "SELECT id, reader_id, item_id, loan_date, due_date, return_date,"
        " fine_cents FROM loans WHERE id = ?",
        (loan_id,),
    ).fetchone()
    if row is None:
        raise NotFound()
    return as_json(row)


def as_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "reader_id": row["reader_id"],
        "item_id": row["item_id"],
        "loan_date": row["loan_date"],
        "due_date": row["due_date"],
        "return_date": row["return_date"],
        "fine": amounts.from_cents(row["fine_cents"]),
    }
