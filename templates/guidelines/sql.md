---
tag: sql
keywords: sql, database, db, mysql, sqlite, migration, schema, query, index, orm, transaction, constraint, join
---

# Guidelines: SQL / Database

## Schema

- `snake_case` for tables and columns
- Plural table names (`users`, not `user`)
- `id` as PRIMARY KEY (identity / auto-increment integer — `GENERATED ALWAYS AS IDENTITY` where supported, not `SERIAL` — or UUID)
- `created_at`, `updated_at` as `TIMESTAMP WITH TIME ZONE DEFAULT NOW()`
- Foreign key: `<table>_id` (e.g. `user_id`) + `FOREIGN KEY (...) REFERENCES ...`

## Migrations

- Every schema change = a new migration, never edit old ones
- A migration is idempotent or safely re-runnable
- Name: `<timestamp>_<description>.sql` (e.g. `20250417120000_add_users_table.sql`)
- ALWAYS provide a rollback/down
- Destructive migrations (DROP, ALTER with data loss) — separately, after review

## Queries

- Explicit column list (NOT `SELECT *` in production code)
- `JOIN ... ON`, not `WHERE` (old style)
- **Parameterised queries** always — never string interpolation (SQL injection); with an ORM, raw-SQL escape hatches take bound parameters too
- Indexes for columns in `WHERE` / `JOIN` / `ORDER BY` — especially FKs
- `EXPLAIN ANALYZE` for slow queries
- Pagination by keyset (`WHERE id > ? ORDER BY id LIMIT n`), not `OFFSET`, for large tables
- Load related rows in one query or one `IN (...)` batch — never a query per row (N+1)

## Transactions

- A transaction when several changes must succeed together
- Short transactions — avoid long-held locks
- Isolation: READ COMMITTED by default, SERIALIZABLE only when needed

## Integrity

- Constraints in the database (`NOT NULL`, `UNIQUE`, `CHECK`, `FK`) — do not rely on application validation alone
- Enum → a separate dictionary table or `CHECK (status IN (...))` / an enum type (Postgres)

## What to avoid

- `NULL` as a meaningful business state (use an enum / status column)
- Denormalisation without a performance reason
- Triggers for business logic (logic → application; triggers for audit/constraints)
- Hard delete for entities with history — soft delete (`deleted_at TIMESTAMP`)
- Storing passwords in plain text — always a hash (argon2id, or bcrypt)
- Running migrations automatically at application start — an explicit deployment step
