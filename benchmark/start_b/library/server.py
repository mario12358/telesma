"""HTTP layer: turns a request into a handler call, and the result into bytes."""

import sqlite3
import sys
import threading
import traceback
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from library.errors import AppError, InvalidData
from library.protocol import HttpRequest, Response, json_response
from library.routes import ROUTES, Route, find_route

ADDRESS = "127.0.0.1"


class Application:
    def __init__(
        self, connection: sqlite3.Connection, routes: Sequence[Route] = ROUTES
    ) -> None:
        self._connection = connection
        self._routes = routes
        # One SQLite connection and rules such as the limit require handling requests one at a time.
        self._lock = threading.Lock()

    def handle(self, method: str, target: str, body: bytes) -> Response:
        try:
            with self._lock:
                return self._execute(method, target, body)
        except AppError as error:
            return json_response(error.status, {"error": error.code})
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return json_response(500, {"error": "internal_error"})

    def _execute(self, method: str, target: str, body: bytes) -> Response:
        url = urlsplit(target)
        handler, identifiers = find_route(self._routes, method, url.path)
        params = dict(parse_qsl(url.query, keep_blank_values=True))
        request = HttpRequest(self._connection, identifiers, params, body)
        with self._connection:
            return handler(request)


class LibraryServer(ThreadingHTTPServer):
    def __init__(self, port: int, application: Application) -> None:
        super().__init__((ADDRESS, port), RequestHandler)
        self.application = application


class RequestHandler(BaseHTTPRequestHandler):
    server: LibraryServer

    def _handle(self) -> None:
        try:
            body = self._read_body()
        except InvalidData as error:
            self._send(json_response(error.status, {"error": error.code}))
            return
        self._send(self.server.application.handle(self.command, self.path, body))

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as error:
            raise InvalidData() from error
        if length < 0:
            raise InvalidData()
        return self.rfile.read(length)

    def _send(self, response: Response) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        self.wfile.write(response.body)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle
