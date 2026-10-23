"""System resources: service health and the system day stored in the database."""

import re
import sqlite3
from datetime import date

from library.errors import AppError, InvalidData
from library.protocol import HttpRequest, Response, json_response

DAY_KEY = "day"
# date.fromisoformat also accepts forms without dashes and week dates.
DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def health(request: HttpRequest) -> Response:
    return json_response(200, {"ok": True})


def today(connection: sqlite3.Connection) -> date:
    row = connection.execute(
        "SELECT value FROM settings WHERE name = ?", (DAY_KEY,)
    ).fetchone()
    return date.fromisoformat(row["value"])


def get_day(request: HttpRequest) -> Response:
    return json_response(200, {"date": today(request.connection).isoformat()})


def set_day(request: HttpRequest) -> Response:
    new_day = _read_date(request.json_object().get("date"))
    if new_day < today(request.connection):
        raise AppError(400, "date_in_past")
    request.connection.execute(
        "UPDATE settings SET value = ? WHERE name = ?",
        (new_day.isoformat(), DAY_KEY),
    )
    return json_response(200, {"date": new_day.isoformat()})


def _read_date(value: object) -> date:
    if not isinstance(value, str) or DATE_PATTERN.fullmatch(value) is None:
        raise InvalidData()
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise InvalidData() from error
