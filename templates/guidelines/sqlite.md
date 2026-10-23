---
tag: sqlite
keywords: sqlite, sqlite3, better-sqlite3, libsql, turso, wal, pragma, embedded database, local database, file database, in-memory, litestream, rusqlite, sqlx
---

# Guidelines: SQLite

Only what differs from the generic `sql` guidelines — tag a SQLite task `(tech: sqlite, sql)`.

## Style

- Every connection runs the same pragmas right after opening, in this order: `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000; PRAGMA temp_store=MEMORY;` — `foreign_keys` and `busy_timeout` are per-connection and OFF by default
- `CREATE TABLE ... STRICT` on every table: column types are enforced (`INT`, `INTEGER`, `REAL`, `TEXT`, `BLOB`, `ANY`); without `STRICT` a `TEXT` column happily stores `42` and an `INTEGER` column stores `'abc'`
- PK: `id INTEGER PRIMARY KEY` (alias for rowid — the cheapest key); `AUTOINCREMENT` only when ids must never be reused after deletes; UUIDs as `TEXT` or 16-byte `BLOB`
- No date or boolean types: timestamps as `TEXT` ISO-8601 UTC (`strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`) or `INTEGER` unix epoch — one convention for the whole schema; booleans `INTEGER NOT NULL CHECK (col IN (0, 1))`
- Money as `INTEGER` minor units; never `REAL`
- `WITHOUT ROWID` only for small-row tables with a natural composite key
- Named placeholders (`:name`, `@name`, `$name`) for statements with more than three parameters, `?` otherwise
- One connection per thread/worker; `better-sqlite3` is synchronous so one connection per process is correct and fastest

## Project structure

- One database file per application with its path from config; `*.db`, `*.db-wal`, `*.db-shm` in `.gitignore`; the file lives on local disk — never on NFS/SMB or a macOS Docker bind mount (file locking breaks silently)
- Migrations as numbered SQL files `migrations/0001_<description>.sql`; the migrator reads `PRAGMA user_version`, applies files above it, bumps the version — all inside one transaction per file (SQLite DDL is transactional)
- `ALTER TABLE` only does ADD/RENAME/DROP COLUMN; anything else is the documented recipe: `PRAGMA foreign_keys=OFF` → create the new table → copy → drop old → rename → recreate indexes → `PRAGMA foreign_key_check` → `PRAGMA foreign_keys=ON`
- Driver: `better-sqlite3` or `node:sqlite` (Node), `sqlite3` stdlib with `isolation_level=None` and explicit `BEGIN` (Python), `rusqlite`/`sqlx` (Rust), `modernc.org/sqlite` (Go, no cgo)
- Prepared statements created once at module load and reused; a `db.ts`/`db.py` module exposes the connection factory that applies the pragmas and runs the migrator

## Concurrency and the single writer

- WAL = many concurrent readers plus exactly one writer; a second writer waits `busy_timeout` and then fails with `SQLITE_BUSY` — that is a design problem (shorten transactions, funnel writes through one worker), not a retry case
- A write transaction starts with `BEGIN IMMEDIATE`, not plain `BEGIN`: it takes the write lock up front instead of failing on the read→write upgrade in the middle
- Batch writes: thousands of inserts inside one transaction, not one transaction per row (each commit is an fsync)
- Long-lived read transactions block WAL checkpoints and the `-wal` file grows; close read transactions promptly, run `PRAGMA wal_checkpoint(TRUNCATE)` from a maintenance job for long-running processes
- `PRAGMA optimize` on connection close and after large data changes keeps the planner statistics fresh

## When SQLite, when not

- Right choice: CLI/desktop/mobile apps, embedded devices, tests, local-first apps, single-server web apps with mostly reads (comfortably thousands of requests per second), replacing a folder of JSON/CSV files
- Wrong choice: several application servers writing to one database, write-heavy multi-tenant SaaS, a need for roles/RLS/network access, or data beyond hundreds of GB — then PostgreSQL
- Backups: Litestream for continuous replication, or `VACUUM INTO '/backups/app-<date>.db'` / the online backup API on a schedule; copying the `.db` file while open is corrupt unless the WAL was checkpointed first
- `libsql`/Turso when the embedded model is wanted but replicas on several machines are required

## Tests

- In-memory database per test from the same connection factory as production (pragmas, `STRICT`, migrations included): `:memory:`, or `file:test?mode=memory&cache=shared` when the code under test opens several connections
- A file database in a temp directory for anything about concurrency, WAL, `busy_timeout` or backups — `:memory:` has no locking to test
- Test the failure modes: an FK violation raises (proves `foreign_keys=ON`), `STRICT` rejects a wrong type, a `UNIQUE` conflict maps to a domain error, a second writer receives `SQLITE_BUSY` within `busy_timeout`
- Test the migration path: open a fixture at `user_version` N-1, migrate, assert the schema via `PRAGMA table_info(t)` and that `PRAGMA foreign_key_check` returns no rows
- Runner: the ecosystem's default (`vitest`/`jest`, `pytest`); the database is built in `beforeEach`/a function-scoped fixture, never shared at module level

## What to avoid

- Forgetting `PRAGMA foreign_keys=ON` — constraints declared and never enforced
- Non-`STRICT` tables, `REAL` money, mixed TEXT/INTEGER dates, `datetime('now')` without the `Z`/UTC convention
- Plain `BEGIN` for read-then-write transactions; `synchronous=OFF` outside tests; `journal_mode=DELETE` for a server process
- A new connection per query (pragmas lost, statement cache lost, lock churn); one connection shared across threads
- Storing files/images as `BLOB` rows — store a path or object key
- `VACUUM` inside request handlers (rewrites the whole file under the write lock)
- Postgres/MySQL idioms the engine does not have: `ILIKE`, `SERIAL`, `ON UPDATE CURRENT_TIMESTAMP`, `ALTER COLUMN`, `TRUNCATE` (use `DELETE FROM t` — `RETURNING` and `UPSERT` do exist)
- `LIKE` on a column with a non-ASCII collation expecting case-insensitivity — SQLite's `LIKE` is ASCII-only case-insensitive
