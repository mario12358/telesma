"""Library items: books and films with a number of copies."""

import sqlite3

from library import validation
from library.errors import NotFound
from library.protocol import HttpRequest, Response, json_response

TYPES = ("book", "film")

# available follows from unreturned loans, so it cannot drift away from their state.
ITEM_QUERY = """
    SELECT i.id, i.title, i.type, i.copies,
           i.copies - COUNT(l.id) AS available
    FROM items AS i
    LEFT JOIN loans AS l ON l.item_id = i.id AND l.state = 'on_loan'
    WHERE (:id IS NULL OR i.id = :id) AND (:type IS NULL OR i.type = :type)
    GROUP BY i.id
    ORDER BY i.id
"""


def create(request: HttpRequest) -> Response:
    data = request.json_object()
    title = validation.non_empty_string(data, "title")
    item_type = validation.one_of(data.get("type"), TYPES)
    copies = validation.integer(data, "copies", minimum=1)
    cursor = request.connection.execute(
        "INSERT INTO items (title, type, copies) VALUES (?, ?, ?)",
        (title, item_type, copies),
    )
    return json_response(201, find(request.connection, cursor.lastrowid))


def get(request: HttpRequest) -> Response:
    (item_id,) = request.identifiers
    return json_response(200, find(request.connection, item_id))


def list_items(request: HttpRequest) -> Response:
    item_type = None
    if "type" in request.params:
        item_type = validation.one_of(request.params["type"], TYPES)
    rows = request.connection.execute(ITEM_QUERY, {"id": None, "type": item_type})
    return json_response(200, {"items": [dict(row) for row in rows]})


def find(connection: sqlite3.Connection, item_id: int) -> dict:
    row = connection.execute(
        ITEM_QUERY, {"id": item_id, "type": None}
    ).fetchone()
    if row is None:
        raise NotFound()
    return dict(row)
