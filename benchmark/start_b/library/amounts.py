"""Amounts: integer cents in the database, a number with two decimal places in JSON."""

import math
from decimal import Decimal

from library.errors import InvalidData


def from_cents(cents: int) -> float:
    return cents / 100


def with_two_decimals(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def positive_cents(value: object) -> int:
    # In Python bool is a subtype of int, and JSON true is not an amount.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidData()
    if not math.isfinite(value) or value <= 0:
        raise InvalidData()
    # str() gives the shortest float representation, so 2.35 is exactly 235 cents, not 234.99...
    cents = Decimal(str(value)) * 100
    if cents != cents.to_integral_value():
        raise InvalidData()
    return int(cents)
