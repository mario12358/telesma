"""Types exchanged between the HTTP layer and the resource handlers."""

import json
import sqlite3
from dataclasses import dataclass, field

from library.errors import InvalidData

JSON_TYPE = "application/json"


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    content_type: str = JSON_TYPE


def json_response(status: int, data: dict) -> Response:
    return Response(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))


@dataclass(frozen=True)
class HttpRequest:
    connection: sqlite3.Connection
    identifiers: tuple[int, ...] = ()
    params: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def json_object(self) -> dict:
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidData() from error
        if not isinstance(data, dict):
            raise InvalidData()
        return data
