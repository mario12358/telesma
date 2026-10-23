"""Application errors mapped to HTTP responses of the form {"error": code}."""


class AppError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


class InvalidData(AppError):
    def __init__(self) -> None:
        super().__init__(400, "invalid_data")


class NotFound(AppError):
    def __init__(self) -> None:
        super().__init__(404, "not_found")


class RuleViolation(AppError):
    def __init__(self, code: str) -> None:
        super().__init__(409, code)
