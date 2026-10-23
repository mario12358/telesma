"""Validation of JSON object fields at the service boundary."""

from library.errors import InvalidData

LARGEST_SQLITE_INTEGER = 2**63 - 1


def non_empty_string(data: dict, field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise InvalidData()
    return value


def integer(data: dict, field: str, minimum: int) -> int:
    value = data.get(field)
    # In Python bool is a subtype of int, and JSON true is not a number.
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidData()
    if not minimum <= value <= LARGEST_SQLITE_INTEGER:
        raise InvalidData()
    return value


def identifier(data: dict, field: str) -> int:
    # An integer outside the range of assigned ids is a valid shape: the resource simply does not exist.
    return integer(data, field, minimum=-LARGEST_SQLITE_INTEGER)


def one_of(value: object, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InvalidData()
    return value
