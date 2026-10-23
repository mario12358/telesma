"""Route table: method + path pattern -> handler."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from library import items, loans, readers, reports, system
from library.errors import NotFound
from library.protocol import HttpRequest, Response

Handler = Callable[[HttpRequest], Response]

# Bounded length: int() rejects strings longer than a few thousand digits.
ID = r"([0-9]{1,19})"
# SQLite stores ids as a signed 64-bit integer; larger ones cannot exist.
LARGEST_IDENTIFIER = 2**63 - 1


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str
    handler: Handler

    def match(self, method: str, path: str) -> tuple[int, ...] | None:
        if method != self.method:
            return None
        found = re.fullmatch(self.pattern, path)
        if found is None:
            return None
        return tuple(int(group) for group in found.groups())


ROUTES: tuple[Route, ...] = (
    Route("GET", r"/health", system.health),
    Route("GET", r"/system/day", system.get_day),
    Route("POST", r"/system/day", system.set_day),
    Route("POST", r"/items", items.create),
    Route("GET", r"/items", items.list_items),
    Route("GET", rf"/items/{ID}", items.get),
    Route("POST", r"/readers", readers.create),
    Route("GET", rf"/readers/{ID}", readers.get),
    Route("POST", r"/loans", loans.create),
    Route("GET", rf"/loans/{ID}", loans.get),
    Route("POST", rf"/loans/{ID}/return", loans.give_back),
    Route("POST", rf"/readers/{ID}/payment", readers.payment),
    Route("GET", rf"/readers/{ID}/loans", loans.reader_list),
    Route("GET", r"/reports/overdue", reports.overdue),
    Route("GET", r"/reports/loans\.csv", reports.csv_export),
)


def find_route(
    routes: Sequence[Route], method: str, path: str
) -> tuple[Handler, tuple[int, ...]]:
    for route in routes:
        identifiers = route.match(method, path)
        if identifiers is None:
            continue
        if any(number > LARGEST_IDENTIFIER for number in identifiers):
            raise NotFound()
        return route.handler, identifiers
    raise NotFound()
