"""Readers and their fine balance."""

import sqlite3

from library import amounts, validation
from library.errors import InvalidData, NotFound, RuleViolation
from library.protocol import HttpRequest, Response, json_response


def create(request: HttpRequest) -> Response:
    data = request.json_object()
    name = validation.non_empty_string(data, "name")
    email = _email_address(data)
    if _email_taken(request.connection, email):
        raise RuleViolation("email_taken")
    cursor = request.connection.execute(
        "INSERT INTO readers (name, email, email_normalized) VALUES (?, ?, ?)",
        (name, email, _normalized(email)),
    )
    return json_response(201, find(request.connection, cursor.lastrowid))


def get(request: HttpRequest) -> Response:
    (reader_id,) = request.identifiers
    return json_response(200, find(request.connection, reader_id))


def payment(request: HttpRequest) -> Response:
    (reader_id,) = request.identifiers
    cents = amounts.positive_cents(request.json_object().get("amount"))
    if cents > balance_cents(request.connection, reader_id):
        raise RuleViolation("overpayment")
    change_balance(request.connection, reader_id, -cents)
    return json_response(200, find(request.connection, reader_id))


def change_balance(connection: sqlite3.Connection, reader_id: int, cents: int) -> None:
    connection.execute(
        "UPDATE readers SET fine_balance_cents = fine_balance_cents + ? WHERE id = ?",
        (cents, reader_id),
    )


def find(connection: sqlite3.Connection, reader_id: int) -> dict:
    row = connection.execute(
        "SELECT id, name, email, fine_balance_cents FROM readers WHERE id = ?",
        (reader_id,),
    ).fetchone()
    if row is None:
        raise NotFound()
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "fine_balance": amounts.from_cents(row["fine_balance_cents"]),
    }


def balance_cents(connection: sqlite3.Connection, reader_id: int) -> int:
    row = connection.execute(
        "SELECT fine_balance_cents FROM readers WHERE id = ?", (reader_id,)
    ).fetchone()
    if row is None:
        raise NotFound()
    return row["fine_balance_cents"]


def _email_address(data: dict) -> str:
    email = data.get("email")
    if not isinstance(email, str) or "@" not in email:
        raise InvalidData()
    return email


def _normalized(email: str) -> str:
    return email.casefold()


def _email_taken(connection: sqlite3.Connection, email: str) -> bool:
    row = connection.execute(
        "SELECT id FROM readers WHERE email_normalized = ?",
        (_normalized(email),),
    ).fetchone()
    return row is not None
