---
tag: postgres
keywords: postgres, postgresql, rls, roles, permissions, grant, security definer, audit, pgtap, queue, skip locked, tenant, isolation, migration
---

# Guidelines: PostgreSQL as the foundation

The "database as the foundation" approach: PostgreSQL is responsible not only for data integrity,
but also for the security boundary (roles, RLS) and for those domain rules that naturally
belong to the data model. The application cannot bypass these mechanisms — a bug in the
backend code must not grant wider access to data. This file is self-contained — tag the task
`(tech: postgres)` without `sql` (`sql.md` describes the classic split with logic in the application).

## Schema and migrations

- `snake_case`, plural table names; PK `id BIGINT GENERATED ALWAYS AS IDENTITY` or UUID
- `created_at`, `updated_at` as `timestamptz DEFAULT now()`
- Constraints in the database: `NOT NULL`, `UNIQUE`, `CHECK`, FK — they are the source of integrity; application validation is only UX
- Every schema change = a new migration (never edit old ones), versioned in the repo
- A migration is compatible with the current AND the previous version of the application — otherwise rolling back to an earlier image stops being possible
- Destructive changes (DROP, data loss) — a separate, later deployment step
- Migrations run as an explicit deployment step, not automatically at application start

## Roles and permissions

- The application NEVER runs as superuser or as schema owner
- Least privilege: a role gets only the GRANTs it needs to work (per table, per operation)
- No application role with `BYPASSRLS`; `REVOKE ALL ... FROM PUBLIC` on the schema and functions
- Separate roles for separate contexts (application, migrations, analytical reads)

## RLS

- RLS limits WHICH rows an organisation, user or context sees/modifies — the last boundary of data access
- RLS does NOT implement detailed business rules (whether an appointment can be cancelled, state transitions, who may perform an operation) — those belong to the domain layer, database functions or constraints, depending on the nature of the rule
- `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` — policies apply to the table owner as well
- Policies per operation (SELECT/INSERT/UPDATE/DELETE), with explicit `USING` and `WITH CHECK`
- The user/tenant identity goes to the database ONLY in transaction scope: `SET LOCAL app.user_id = ...` — never as session/connection state (the connection pool will carry it between requests)

## Database functions

- A domain rule goes where it is natural: invariants → constraints; operations needing atomicity and elevated privileges → a database function; orchestration → the application
- `SECURITY DEFINER` only when necessary; then mandatory: `SET search_path` in the definition, fully qualified object references, `REVOKE ALL FROM PUBLIC` + an explicit `GRANT EXECUTE`
- A function validates its input and state — it does not assume the application did it

## Audit

- Audit events → a dedicated append-only journal, logically separate from application logs
- Minimum: user/session, kind of operation, time, object of the operation
- Application roles: only `INSERT` (no UPDATE/DELETE) on audit tables
- Audited reads of sensitive data → through a controlled path (function/endpoint) that records them — triggers do not catch SELECT

## Queue in PostgreSQL

- Simple async jobs: a jobs table + `SELECT ... FOR UPDATE SKIP LOCKED LIMIT n`
- Job status as a column (pending/processing/done/failed) + attempt counter + processing time
- A separate message broker only once it solves a specific, measured problem

## Access from the application

- No heavy ORM — parameterised queries through the driver (never string interpolation)
- Explicit column list (not `SELECT *`); short transactions
- The number of queries per operation matters — do not generate N+1; load related rows with a JOIN or one `= ANY($1)` batch

## Tests

- pgTAP for the database layer: constraints, functions, permissions, RLS policies
- CI builds a fresh database from migrations from scratch — that is also a test of the schema
- MANDATORY negative tests: a user/tenant can NOT read or modify someone else's data; the test passes when the operation is rejected or returns 0 rows
- Isolation tests run as the application role, not as the database owner

## What to avoid

- Authorisation only in the backend "because it is faster" — the database is the access boundary
- Session-level `SET` to pass identity — only `SET LOCAL` inside a transaction
- An application role owning tables without `FORCE ROW LEVEL SECURITY`
- Business logic crammed into RLS policies
- Triggers as a mechanism for auditing reads (they do not fire on SELECT)
- `SELECT *`, string interpolation in SQL, long transactions holding locks
