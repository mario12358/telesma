---
tag: python
keywords: python, pytest, pep8, typing, uv, poetry, pip, venv, async, ruff, pyproject, mypy, dataclass
---

# Guidelines: Python

## Style

- PEP 8 (4 spaces, `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE` for constants)
- Type hints on public functions, modern syntax: `def foo(x: int | None = None) -> list[str]:` (not `Optional`, `List`)
- `ruff format` + `ruff check --fix` (replaces black, isort, flake8) — run them; do not argue with them
- A type checker (`mypy` or `pyright`) in CI; `# type: ignore` only with a reason
- f-strings instead of `.format()` and `%`
- `pathlib.Path` instead of `os.path`
- `@dataclass(frozen=True)` (or pydantic at the boundary) for structured data — not dicts with magic keys

## Project structure

- `src/<package>/` + `tests/`
- `pyproject.toml` (`uv` preferred; poetry acceptable) instead of `setup.py` / `requirements.txt`; lockfile committed
- `__init__.py` exports the package's public API
- Always a virtualenv (`uv sync` / `.venv`) — never install into the system Python

## Tests

- pytest (not unittest); `tests/test_<module>.py`, run one with `pytest tests/test_x.py::test_name`
- fixtures > `setUp`/`tearDown`; `conftest.py` for shared fixtures
- `@pytest.mark.parametrize` for multiple variants
- Mocks: `unittest.mock.patch` or `pytest-mock`; `pytest-asyncio` for `async def` tests
- Test name: `test_<function>_<condition>_<expectation>`

## Imports

- Absolute imports (`from myapp.models import User`)
- Order: stdlib → third-party → local (blank line between groups) — `ruff` sorts them

## Async

- `async def` only when you really need I/O concurrency
- Do not mix sync/async without a reason — pick one style per module
- `asyncio.TaskGroup` (or `gather`) for parallelism, not `create_task` + `await` in a loop
- Never call blocking I/O inside `async def` — `asyncio.to_thread` for sync libraries

## What to avoid

- `import *`
- Mutable default arguments (`def f(x=[]):`)
- Bare `except:` without an exception type
- Logic in `if __name__ == "__main__":` beyond simple scripts
- `global` — prefer a class or a parameter
