---
tag: mysql
keywords: mysql, mariadb, innodb, utf8mb4, mysql2, pymysql, mysqlclient, aiomysql, mysqldump, binlog, replication, auto_increment, percona, vitess
---

# Guidelines: MySQL / MariaDB

Only what differs from the generic `sql` guidelines — tag a MySQL task `(tech: mysql, sql)`.

## Style

- `ENGINE=InnoDB` on every table; never MyISAM (no transactions, no foreign keys, table-level locks)
- Charset at the database level: `CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci` (MySQL) or `utf8mb4_unicode_ci` (MariaDB); `utf8` is 3-byte in MySQL and breaks on emoji — never use it
- Strict mode is mandatory, in the server config AND in the connection options: `sql_mode='STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,ONLY_FULL_GROUP_BY'` — without it a too-long string is silently truncated and a missing default becomes `''`
- Lowercase `snake_case` identifiers and `lower_case_table_names=1` — table names are case-sensitive on Linux and not on macOS/Windows
- PK: `id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT`, or `BINARY(16)` for UUIDs (`UUID_TO_BIN(uuid, 1)` makes them time-ordered); never `CHAR(36)` as the clustered key — every secondary index carries the PK
- Timestamps as `DATETIME(6)` in UTC with `time_zone='+00:00'` on every connection; `TIMESTAMP` ends in 2038 and converts by session zone
- Booleans `TINYINT(1)`; money `DECIMAL(19,4)`; never `FLOAT`/`DOUBLE` for anything compared or summed
- Avoid reserved words as identifiers (`order`, `key`, `rank`, `group`) instead of backticking them everywhere
- `_ci` collations compare case-insensitively: `WHERE token = 'Ab'` matches `ab` — use `utf8mb4_bin` on columns where case matters (tokens, slugs, hashes)

## Project structure

- `db/migrations/<timestamp>_<description>.sql` driven by exactly one tool (Flyway, dbmate, golang-migrate, Alembic, Prisma Migrate, Knex); one DDL statement per file — MySQL DDL is not transactional, a failed multi-statement migration leaves a half-applied schema
- Every migration re-runnable: `CREATE TABLE IF NOT EXISTS`, `DROP INDEX IF EXISTS`, column changes guarded by a check against `information_schema`
- Two database users from env: a migration user (DDL) and an application user (`SELECT, INSERT, UPDATE, DELETE` only); the application never connects as `root`
- Driver: `mysql2/promise` (Node), `PyMySQL` or `mysqlclient` behind SQLAlchemy (Python), `go-sql-driver/mysql` (Go); placeholders are positional `?` — never interpolate
- One pool per process: `connectionLimit`/`pool_size` 5–20, `pool_recycle` shorter than the server's `wait_timeout`, `connectTimeout` a few seconds — the "MySQL server has gone away" error means recycling is missing
- Set `sql_mode`, `time_zone` and `charset` in the pool's init options so every connection is identical

## Indexing

- A composite index `(a, b, c)` serves `WHERE a = ?` and `WHERE a = ? AND b = ?`, not `WHERE b = ?` — leftmost prefix; order columns equality → range → sort
- Covering index for hot queries: every selected column inside the index → `Using index` in `EXPLAIN`
- `UNIQUE` on long text: a prefix index `(email(32))` is not unique-safe — add a `SHA2(col, 256)` generated column and make that unique
- `EXPLAIN ANALYZE` / `EXPLAIN FORMAT=TREE`; red flags `type: ALL`, `Using filesort`, `Using temporary`, `rows` far above the result size
- A function or implicit cast around an indexed column disables the index: `WHERE DATE(created_at) = ?` → `WHERE created_at >= ? AND created_at < ?`; `WHERE varchar_col = 123` → pass a string
- Online schema change: `ALTER TABLE ... , ALGORITHM=INPLACE, LOCK=NONE` so the statement fails fast instead of locking a big table; gh-ost or pt-online-schema-change when it is not online-capable
- `JSON` column only for genuinely variable attributes; query with `col->>'$.key'`; index through a generated column: `ADD COLUMN sku VARCHAR(64) AS (attrs->>'$.sku') STORED, ADD INDEX (sku)`; multi-valued index for arrays
- Pagination by keyset `WHERE (created_at, id) < (?, ?) ORDER BY created_at DESC, id DESC LIMIT ?` — `OFFSET` scans everything it skips
- Not available (unlike Postgres): partial indexes, `DISTINCT ON`, arrays, `SERIAL`; `ENUM` alterations rewrite the table — prefer a lookup table or `CHECK`

## Transactions and locking

- InnoDB defaults to REPEATABLE READ with gap locks; use `READ COMMITTED` for OLTP unless one consistent snapshot across statements is needed — fewer deadlocks
- Deadlocks (error 1213) and lock wait timeouts (1205) are normal: retry the whole transaction with bounded attempts and jitter, never a single statement
- Read-then-write locks the row: `SELECT ... FOR UPDATE` (or `FOR UPDATE SKIP LOCKED` for job queues); a plain `SELECT` reads a snapshot and the later `UPDATE` races
- Upsert: `INSERT ... ON DUPLICATE KEY UPDATE col = new.col` (`AS new` alias; `VALUES()` is deprecated); never `REPLACE INTO` — it deletes and re-inserts, firing cascades and burning auto-increment values
- `innodb_lock_wait_timeout` 5–10 s on the application session, not the 50 s default; DDL auto-commits — never inside a data transaction
- No `RETURNING` in MySQL: read `insertId` from the driver result on the same connection (MariaDB 10.5+ has `RETURNING`)

## Tests

- A real server per test run: Testcontainers (`mysql` / `mariadb` image) or a compose service with the production `sql_mode`, charset and time zone; never SQLite standing in for MySQL, never a mocked query layer
- Schema built by the real migration chain, not by an ORM `sync`/`create_all` — the migrations are under test too
- Isolation: a database per worker (`app_test_<worker>`) and `TRUNCATE` all tables in setup with `SET FOREIGN_KEY_CHECKS=0` around the reset only; or a transaction per test rolled back at the end for code that does not commit
- Test the failure modes: duplicate key (1062) mapped to a domain conflict, deadlock retry succeeds on the second attempt, strict mode rejects an over-long string, a 4-byte character round-trips, `ON DUPLICATE KEY UPDATE` does not change `created_at`
- An `EXPLAIN` assertion on the hot queries (`type != 'ALL'`) catches a dropped index in CI

## What to avoid

- `utf8`, MyISAM, `TIMESTAMP` for business dates, `FLOAT` money, `CHAR(36)` UUID primary keys
- `LIKE '%term'`, `ORDER BY RAND()`, `SELECT COUNT(*)` to test existence (use `EXISTS` / `LIMIT 1`), `OFFSET` deep pagination
- Relying on `AUTO_INCREMENT` being gapless, or on row order without `ORDER BY`
- Multi-statement migrations, migrations run by the application user, migrations at application start
- `LOCK TABLES`, long transactions holding gap locks, `autocommit=0` sessions left open in a pool
- `mysqldump` on production without `--single-transaction`
- Disabling strict mode or `ONLY_FULL_GROUP_BY` to make a query "work"
