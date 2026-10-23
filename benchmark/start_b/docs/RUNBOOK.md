# RUNBOOK — Library

HTTP service of a small lending library (items, readers, loans, fines, reports).
One process, one SQLite database, no user login. Contract: `telesma/spec/library.md`.

## Requirements

- Python 3.11+ (developed and tested on 3.13).
- No dependencies from PyPI — standard library only. There is nothing to install,
  no `requirements.txt` and no virtualenv.

## Environment variables

None. The whole configuration is two required command-line parameters.

## Running

From the repository root:

```bash
python3 -m library --port 8000 --db data/library.sqlite
```

- Listens only on `127.0.0.1:<port>`; runs until interrupted (Ctrl+C / SIGTERM).
- The database file's directory must exist; the file itself may be missing or empty — the schema is created at start.
- A missing `--port` or `--db` exits the process with code 2 and an argparse message.
- The request log goes to stderr; an unhandled exception gives `500 {"error": "internal_error"}` and a traceback on stderr.

Quick check:

```bash
curl -s http://127.0.0.1:8000/health          # {"ok": true}
curl -s http://127.0.0.1:8000/system/day      # {"date": "2026-01-01"} in a new database
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

- 117 tests, about 8 s. Every test starts its own service process on a free port and a fresh database
  in a temporary directory (`tests/helpers.py`), so the tests never touch any data in the repo.
- A single file: `python3 -m unittest discover -s tests -p "test_returns*"`.

## Database

- SQLite, the file given by `--db`. Every HTTP request is one transaction; requests are handled one at a time.
- Migrations: files `library/migrations/<timestamp>_<description>.sql`, applied automatically at start
  in name order; applied versions are in the `migrations` table. Every migration has a `.down.sql` pair
  (rollback is manual: `sqlite3 FILE < ...down.sql` + deleting the row from `migrations`).
- A schema change = a new migration file; existing ones are never edited.
- There is no seeding. The only start value is the system day `2026-01-01` (table `settings`).
- Amounts are stored as integer cents (`fine_balance_cents`, `fine_cents`).
- Backup: copy the database file with the service stopped, or use `sqlite3 FILE ".backup copy.sqlite"`.

## System time

The service does not read the clock. "Today" is a value in the database, moved forward only:

```bash
curl -s -X POST http://127.0.0.1:8000/system/day -d '{"date": "2026-02-01"}'
```

Due dates, overdue loans and fines depend on this value — after deployment someone (a person or cron) has to
move it every day, otherwise no fines will be charged.

## Endpoints

| Method and path | Description |
|---|---|
| `GET /health` | service health |
| `GET`/`POST /system/day` | read / set the system day |
| `POST /items`, `GET /items[?type=book\|film]`, `GET /items/{id}` | items with the `available` field |
| `POST /readers`, `GET /readers/{id}` | readers with `fine_balance` |
| `POST /readers/{id}/payment` | paying off fines |
| `GET /readers/{id}/loans[?state=all]` | a reader's loans |
| `POST /loans`, `GET /loans/{id}` | loan (rules: `fine_block`, `has_overdue`, `loan_limit`, `no_copies`) |
| `POST /loans/{id}/return` | return with the fine computed |
| `GET /reports/overdue` | unreturned past their due date |
| `GET /reports/loans.csv` | export of all loans |

Errors always have the form `{"error": "<code>"}` with status 400 / 404 / 409.

## Test accounts

None — the service has no login. It is meant to run behind a trusted internal network
(listening on loopback only).
