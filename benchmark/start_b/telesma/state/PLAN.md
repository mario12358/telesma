# telesma/state/PLAN.md — Library

### Phase 1: Skeleton

- [x] Task 1.1: Architecture skeleton and conventions — package `library` started with `python3 -m library --port --db`, module map, error format `{"error": code}`, SQLite schema; outcome into PROJECT_CONTEXT.md (spec: library.md) (tech: python, sql)
  - AC: `python3 -m library --port N --db FILE` listens on 127.0.0.1:N and creates the schema in an empty file
  - AC: `GET /health` → 200 `{"ok": true}`; unknown path → 404 `not_found`; invalid JSON → 400 `invalid_data`
- [x] Test: server start on a free port, `/health`, 404 and 400
- [x] Task 1.2: System time — `GET`/`POST /system/day`, value in the database, start `2026-01-01` (requires: 1.1) (spec: library.md) (tech: python, sql)
  - AC: a date earlier than the current one → 400 `date_in_past`; the same date allowed; malformed → 400 `invalid_data`
  - AC: the day survives a process restart on the same database file
- [x] Test: day change, date in the past, malformed date, persistence after restart

### Phase 2: Items and readers

- [x] Task 2.1: Items — `POST /items`, `GET /items/{id}`, `GET /items` with the `?type=` filter (requires: 1.1) (spec: library.md) (tech: python, sql)
  - AC: validation of `title` (non-empty), `type` (`book`|`film`), `copies` (integer ≥ 1) → 400 `invalid_data`
  - AC: the response contains `available`; list in ascending `id` order; unknown type in the filter → 400
- [x] Test: creation, read, validation, filter
- [x] Task 2.2: Readers — `POST /readers`, `GET /readers/{id}`, `fine_balance` (requires: 1.1) (spec: library.md) (tech: python, sql)
  - AC: the e-mail must contain `@`; a duplicate e-mail regardless of letter case → 409 `email_taken`
- [x] Test: creation, read, validation, duplicate e-mail

### Phase 3: Loans

- [x] Task 3.1: Loan — `POST /loans`, `GET /loans/{id}`, due dates 14/3 days, item `available` (requires: 1.2, 2.1, 2.2) (spec: library.md) (tech: python, sql)
  - AC: `due_date` = today + 14 days (book) / + 3 days (film); non-existent reader or item → 404
  - AC: `available` decreases after a loan
- [x] Test: due dates of both types, 404, drop in `available`
- [x] Task 3.2: Loan rules in the order from the spec — `fine_block`, `has_overdue`, `loan_limit`, `no_copies` (requires: 3.1) (spec: library.md) (tech: python, sql)
  - AC: checking order as in section 6 of the spec when a request violates several rules at once
  - AC: the limit is 3 unreturned; overdue = today > `due_date` of at least one unreturned loan
- [x] Test: each rule separately, boundary values, order with two violations
- [x] Task 3.3: Return and fines — `POST /loans/{id}/return`, fine 1.0/2.0 per day, added to `fine_balance`, `POST /readers/{id}/payment` (requires: 3.2) (spec: library.md) (tech: python, sql)
  - AC: return on time → fine `0.0`; repeated return → 409 `already_returned`; `available` increases
  - AC: payment > balance → 409 `overpayment`; amount ≤ 0 → 400; balance ≥ 10.0 blocks loans
- [x] Test: book and film fine, return on time, repeated return, block at the 10.0 boundary, payment
- [x] Task 3.4: Reader's loan list — `GET /readers/{id}/loans` with `?state=` (requires: 3.3) (spec: library.md) (tech: python, sql)
  - AC: by default only unreturned; `?state=all` also returned; any other value → 400
- [x] Test: both states, wrong value, non-existent reader

### Phase 4: Reports

- [x] Task 4.1: Overdue report — `GET /reports/overdue` (requires: 3.3) (spec: library.md) (tech: python, sql)
  - AC: only unreturned past their due date, in ascending `id` order, with `days_overdue`
- [x] Test: empty report, one overdue loan, disappearing after return
- [x] Task 4.2: CSV export — `GET /reports/loans.csv` (requires: 3.3) (spec: library.md) (tech: python)
  - AC: header and column order as in the spec; `fine` with two decimal places; empty `return_date` for unreturned loans
  - AC: fields with a comma or double quote quoted as the `csv` module does it; `Content-Type: text/csv; charset=utf-8`
- [x] Test: header, returned and unreturned row, quoting

## Spec coverage

| File | Section | Tasks |
|------|---------|-------|
| library.md | 1. Technical requirements | 1.1 |
| library.md | 2. System time | 1.2 |
| library.md | 3. Errors | 1.1, 2.1, 2.2, 3.2 |
| library.md | 4. Items | 2.1, 3.1 |
| library.md | 5. Readers | 2.2, 3.3 |
| library.md | 6. Loans | 3.1, 3.2, 3.3, 3.4 |
| library.md | 7. Reports | 4.1, 4.2 |
