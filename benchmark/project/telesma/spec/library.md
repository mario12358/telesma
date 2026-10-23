# Library — specification

An HTTP service for a small lending library: items (books, films), readers, loans with due
dates, late fines and reports. One process, one SQLite database, no user login — it is an
internal system operated by a staff member.

## 1. Technical requirements

- Python 3.11+, **standard library only** (`http.server`, `sqlite3`, `json`, `csv`,
  `unittest`). No packages from PyPI.
- The package is called `library` and lives in the repository root.
- Start: `python3 -m library --port <number> --db <path to SQLite file>`.
  The process listens on `127.0.0.1:<port>`, creates the database schema if the file is empty or
  does not exist, and runs until interrupted. Both parameters are required.
- Tests: `python3 -m unittest discover -s tests -v` from the root directory.
- All requests and responses are JSON in UTF-8 (`Content-Type: application/json`), except the
  CSV report (section 7).
- Amounts are numbers with two decimal places of precision (e.g. `2.5`, `10.0`). Dates are
  strings `YYYY-MM-DD`. Identifiers are integers assigned in ascending order starting at 1.

## 2. System time

The system does not read the clock. "Today" is a value stored in the database.

- `GET /system/day` → `200 {"date": "YYYY-MM-DD"}`. In a new database today is `2026-01-01`.
- `POST /system/day` with `{"date": "YYYY-MM-DD"}` sets today → `200 {"date": …}`.
  A date earlier than the current one → `400 {"error": "date_in_past"}`. The same date as the
  current one is allowed and changes nothing. A malformed date → `400 {"error": "invalid_data"}`.
- `GET /health` → `200 {"ok": true}`.

## 3. Errors

Every error response has the form `{"error": "<code>"}`.

| Situation | Status | Code |
|---|---|---|
| Missing required field, wrong type, wrong value, invalid JSON | 400 | `invalid_data` |
| No resource with the given id, or no such path | 404 | `not_found` |
| Business rule violation | 409 | the rule's code (sections below) |

When a request violates several rules at once, the checking order given with the rules applies.

## 4. Items

An item has `id`, `title` (non-empty string), `type` (`book` or `film`) and `copies`
(integer ≥ 1 — how many copies the library owns).

- `POST /items` with `{"title", "type", "copies"}` → `201` and the full item with the field
  `available` (the number of copies that can be borrowed right now).
- `GET /items/{id}` → `200` and the item with the current `available`.
- `GET /items` → `200 {"items": [...]}` in ascending `id` order. The parameter `?type=book` narrows
  the list to one type; an unknown type → `400 invalid_data`.

## 5. Readers

A reader has `id`, `name` (non-empty string), `email` (a string containing `@`) and
`fine_balance` (an amount, `0.0` at the start).

- `POST /readers` with `{"name", "email"}` → `201` and the full reader. A second reader with the
  same e-mail address (case-insensitive) → `409 {"error": "email_taken"}`.
- `GET /readers/{id}` → `200` and the reader with the current `fine_balance`.
- `POST /readers/{id}/payment` with `{"amount"}` (a number > 0) decreases `fine_balance` →
  `200` and the reader. An amount larger than the balance → `409 {"error": "overpayment"}`.

## 6. Loans

A loan has `id`, `reader_id`, `item_id`, `loan_date`, `due_date`,
`return_date` (`null` until returned) and `fine` (an amount, `0.0` until returned).

- `POST /loans` with `{"reader_id", "item_id"}` → `201` and the loan.
  `loan_date` = today. `due_date` = today + 14 days for a book, + 3 days for a film.
  A non-existent reader or item → `404 not_found`.
- Rules, checked in this order:
  1. the reader's `fine_balance` ≥ 10.0 → `409 fine_block`
  2. the reader has at least one unreturned loan past its due date (today > `due_date`)
     → `409 has_overdue`
  3. the reader already has 3 unreturned loans → `409 loan_limit`
  4. the item has no available copies → `409 no_copies`
- `POST /loans/{id}/return` (no body) → `200` and the loan with `return_date` =
  today and the computed `fine`. Fine = number of days past the due date × rate: 1.0 per day for
  a book, 2.0 per day for a film. A return on time → fine `0.0`. The fine is added to the
  reader's `fine_balance`. A repeated return → `409 {"error": "already_returned"}`.
- `GET /loans/{id}` → `200` and the loan.
- `GET /readers/{id}/loans` → `200 {"loans": [...]}` in ascending `id` order.
  By default only unreturned ones; `?state=all` also returns returned ones. Any other `state`
  value → `400 invalid_data`.

## 7. Reports

- `GET /reports/overdue` → `200 {"overdue": [...]}`: unreturned loans past their
  due date, in ascending `id` order. Each entry: `loan_id`, `reader_id`, `item_id`,
  `title`, `type`, `due_date`, `days_overdue` (today − due date, in days).
- `GET /reports/loans.csv` → `200`, `Content-Type: text/csv; charset=utf-8`. The first
  row is the header `id,reader,title,type,loan_date,due_date,return_date,fine`.
  Then one row per loan (returned ones too), in ascending `id` order.
  `reader` is the reader's name, `return_date` is empty for unreturned loans, `fine`
  always has two decimal places (`0.00`). The separator is a comma; fields containing
  a comma or a double quote are quoted as the `csv` module does it.
