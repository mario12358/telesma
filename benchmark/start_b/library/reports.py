"""Reports: overdue loans and the loan export."""

import csv
import io
import sqlite3
from datetime import date

from library import amounts, system
from library.protocol import HttpRequest, Response, json_response

CSV_TYPE = "text/csv; charset=utf-8"
CSV_HEADER = (
    "id", "reader", "title", "type", "loan_date", "due_date", "return_date", "fine",
)


def overdue(request: HttpRequest) -> Response:
    today = system.today(request.connection)
    rows = request.connection.execute(
        "SELECT l.id AS loan_id, l.reader_id, l.item_id, i.title, i.type, l.due_date"
        " FROM loans AS l JOIN items AS i ON i.id = l.item_id"
        " WHERE l.state = 'on_loan' AND l.due_date < ?"
        " ORDER BY l.id",
        (today.isoformat(),),
    )
    return json_response(200, {"overdue": [_overdue_entry(row, today) for row in rows]})


def csv_export(request: HttpRequest) -> Response:
    rows = request.connection.execute(
        "SELECT l.id, r.name, i.title, i.type, l.loan_date, l.due_date,"
        " l.return_date, l.fine_cents"
        " FROM loans AS l"
        " JOIN readers AS r ON r.id = l.reader_id"
        " JOIN items AS i ON i.id = l.item_id"
        " ORDER BY l.id"
    )
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    writer.writerows(_csv_row(row) for row in rows)
    return Response(200, buffer.getvalue().encode("utf-8"), CSV_TYPE)


def _csv_row(row: sqlite3.Row) -> tuple:
    return (
        row["id"], row["name"], row["title"], row["type"],
        row["loan_date"], row["due_date"], row["return_date"] or "",
        amounts.with_two_decimals(row["fine_cents"]),
    )


def _overdue_entry(row: sqlite3.Row, today: date) -> dict:
    days_overdue = (today - date.fromisoformat(row["due_date"])).days
    return {**dict(row), "days_overdue": days_overdue}
