# PROJECT_CONTEXT.md

This file keeps the project context that survives `/compact`.

## Tech stack

- Language: Python 3.11+ (3.13 locally), standard library ONLY
- Framework: none — `http.server.ThreadingHTTPServer`
- Database: SQLite (`sqlite3`), one file from `--db`
- Tests: `unittest` (`python3 -m unittest discover -s tests -v`), every test = its own service process on a fresh database

## Architecture

Package `library/` in the root directory, start: `python3 -m library --port N --db FILE`.

| Module | Role |
|--------|------|
| `__main__.py`, `cli.py` | argparse (`--port`, `--db` required) → `db.open_db` → `LibraryServer.serve_forever` |
| `server.py` | `RequestHandler` (reads the body, sends a `Response`), `Application.handle(method, target, body)` — routing, transaction, turning `AppError` into `{"error": code}`, an unknown exception → 500 `internal_error` + traceback on stderr |
| `routes.py` | `ROUTES` — a tuple of `Route(method, pattern_regex, handler)`; ids in the path via the `ID` constant; no match (also a wrong method) → 404 |
| `protocol.py` | `HttpRequest(connection, identifiers, params, body)` + `json_object()` (lazy parsing, 400 when not an object), `Response(status, body, content_type)`, `json_response` |
| `errors.py` | `InvalidData` (400), `NotFound` (404), `RuleViolation(code)` (409) |
| `db.py` + `migrations/*.sql` | connection (`row_factory=Row`, `foreign_keys=ON`), migrations tracked in the `migrations` table; each has a `.down.sql` pair |
| `system.py` | handlers `/health` (later `/system/day`) |
| resources (later tasks) | `items.py`, `readers.py`, `loans.py`, `reports.py` — handler `(HttpRequest) -> Response` + SQL in one module |

Schema (migration `20260919120000_create_schema`, all tables at once): `settings(name, value)` with the row `day=2026-01-01`; `items(id, title, type, copies)`; `readers(id, name, email, email_normalized UNIQUE, fine_balance_cents)`; `loans(id, reader_id, item_id, loan_date, due_date, state, return_date, fine_cents)` with `state IN ('on_loan','returned')`. Dates as TEXT `YYYY-MM-DD` (lexicographic comparisons). `available` computed by a query, not stored.

Tests: `tests/helpers.py` — `TestWithService` (setUp starts a process on a free port, `self.request(...)`, `self.assert_error(resp, status, code)`), `ServiceProcess.stop()/start()` for restart tests, `send(port, ...)`.

## Key decisions

<!-- The table grows with every session, and the file goes in full into the startup prompt, so   -->
<!-- telesma.sh keeps its 40 latest rows — older ones go to telesma/state/CONTEXT_ARCHIVE.md          -->
<!-- (write-only). Mark a decision that is STILL BINDING — one whose violation would break the    -->
<!-- project — with 📌 in the Decision column: a row with 📌 never rotates.                        -->

| Date | Decision | Reason |
|------|----------|--------|
| 2026-09-19 | 📌 The spec wins over `python.md`: `unittest` instead of pytest, package in the root directory instead of `src/`, no pyproject/venv | Spec §1 (standard library only) + the test command in config.md + AC 1.1 — the user settled it in the state files |
| 2026-09-19 | 📌 Amounts as integer cents in the database (`*_cents`), as the number `cents / 100` in JSON | No floating-point errors at the 10.0 threshold or when adding up fines |
| 2026-09-19 | 📌 Error order: path 404 → data-shape 400 → resource 404 → rule 409 | Spec §3; the body is parsed lazily only in the handler, so an unknown path with bad JSON is a 404 |
| 2026-09-19 | 📌 Requests handled one at a time (lock in `Application`), one SQLite connection, handler = one transaction | Limit/copies rules without races; an exception in a handler = rollback |
| 2026-09-19 | No `created_at`/`updated_at` and no soft delete despite `sql.md` | Spec §2: the system does not read the clock; the service deletes nothing |
| 2026-09-19 | `loans.state` next to `return_date` (a CHECK keeps them consistent) | `sql.md`: NULL is not a business state; queries filter on `state` |
| 2026-09-19 | `email_normalized` (Python `casefold`) with UNIQUE | `lower()`/NOCASE in SQLite only work for ASCII |
| 2026-09-19 | A payment with more than 2 decimal places (e.g. `1.005`) → 400; conversion `Decimal(str(amount)) * 100` in `amounts.positive_cents` | Spec §1: amounts have 2-decimal precision; no silent rounding of money |
| 2026-09-19 | `POST .../return` ignores the request body | Spec §6: a return has «no body», so we do not parse one |
| 2026-09-19 | CSV via `csv.writer` with the default dialect (QUOTE_MINIMAL, line ending `\r\n`); `fine` formatted from cents (`amounts.with_two_decimals`) | Spec §7: quoting «as the csv module does it», fine always with two decimal places |
| 2026-09-19 | JSON response `Content-Type` is exactly `application/json` | Spec §1 gives this form without `charset` |

## Known problems and solutions

<!-- Known pitfalls: distilled from the Problem log at the end-of-phase checkpoint (section 7  -->
<!-- of the instructions). Only RECURRING patterns — a one-off mistake stays in the Problem    -->
<!-- log in REPORT.md. One row = one pitfall, on ONE line and concise: the file goes           -->
<!-- in full into the prompt of every session.                                                 -->
<!-- telesma.sh keeps the 30 latest rows here, older ones → telesma/state/CONTEXT_ARCHIVE.md.      -->
<!-- Mark a pitfall that COMES BACK despite being written down (repeated ≥2 times) with 📌 —   -->
<!-- such a row never rotates. Leave a one-off slip without a marker.                          -->

| Problem | Solution |
|---------|----------|
| | |

## Component dependencies

`RequestHandler` → `Application.handle` → `find_route` → resource handler → SQL on `request.connection`. A new endpoint = a handler in the resource module + an entry in `routes.ROUTES`. `Application(connection, routes=...)` accepts its own route table (used in the HTTP-layer tests). A schema change = a new file in `migrations/` + `.down.sql`, never an edit of an old one.

## Current state

<!-- CURRENT STATE — OVERWRITE. This is meant to answer "where are we TODAY", not to be a       -->
<!-- chronicle of turns: task history has its own place in REPORT.md and rotates there, while   -->
<!-- nothing rotates here. Appending paragraphs like "turn of 19.08 closed" turns this section    -->
<!-- into a second, unbounded report in the prompt of every session.                             -->

- Last completed task: 4.2 CSV export — all phases 1–4 closed (tags `telesma/phase-1..4`), `docs/RUNBOOK.md` generated
- Next task: none — plan completed; further scope through `telesma/changes/`
- Blockers: none
