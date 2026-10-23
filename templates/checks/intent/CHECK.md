---
kind: rule
run: python3 run.py
check: python3 run.py --check
when: commit, phase, ci
scope: changed
on_failure: block
---

# Check: intent

The other checks read a line of code: they catch an injection typed in a hurry, they do not catch
a **missing** check. Missing authorization (OWASP A01) is the costliest class in the hub:
"doctor A1 admitted a patient from A2's queue" and "the signing screen opened for anyone who knew
the address" went through green tests. This check compares code against a **declaration of
intent** — `telesma/state/SECURITY_MAP.md` (the attack surface map, format in `MAP_TEMPLATE.md` next to
this file) — so a new route without a named role and a route that lost its guard do not pass
silently.

**Route window.** The check does not understand the authentication framework and does not need
to. For every route it takes the text where the guards stand: decorators and the function
signature together with the router definition (`APIRouter(dependencies=…)`) in Python, call
arguments before the handler and `x.use(prefix, …)` in JS, `@UseGuards` / `@Roles` of the method
and the class in Nest. The map says which text stands for a given role (the "Guard in code"
column). A sub-app mounted in another file (`app.route("/doctor", createDoctorRoutes(…))`,
`teamRoutes(routes, …)`) gets its prefix and guards from the mount site — up to three levels,
via `git grep`; without this, on a Hono/Deno medical project `GET /` appeared 10 times as one
route, and 83 of 235 routes looked unprotected. Recognized: FastAPI, Flask, Starlette-like
(`@x.get(` / `@x.route(`), Express, Hono, Fastify, Koa-router (the file must import the
framework — otherwise `api.get('/x')` is an axios client), Nest. Other frameworks (Django URLconf,
Rails, Spring) — the check stays silent.

**"New"** = absent from that file at the reference point: at `commit` in HEAD, at `phase` in the
last `telesma/phase-*` tag, in CI — `TELESMA_SINCE`. The map is read from disk, so a row added in the
same commit as the route counts.

| Rule | Severity | What |
|---|---|---|
| `route-outside-map` | **block** | a new route without a row in `## Routes`. The fix is cheap — add the row — and that is the point: the row requires naming the roles and the ownership, just as `AC: entry` requires naming the entry point. A route from before the change without a row — warns |
| `guard-mismatch` | **block** | in a changed file, a route with a role other than `anonymous` whose window holds no guard from that role's column. Catches both a new route without a guard and a guard removed from an existing one |
| `new-public-route` | warn | a new route with the role `anonymous` — sometimes legitimate (a signed webhook, health), but always worth a line in the report |
| `role-undecided` | warn | routes with the role `?` in a changed file (the skeleton did not recognize a guard): public, or is a guard missing? |
| `role-unknown` / `role-without-guard` | warn | a role from `## Routes` without a row in `## Roles` / without a "Guard in code" — routes of that role are not checked |
| `route-gone` | warn | a map row for a route that is no longer in the code |
| `host-outside-map` | warn | a new `https?://<host>` in code (outside tests, comments, `localhost`, `example.*`) without a `host` row — exfiltration, SSRF, an instruction injected through `telesma/changes/`. A subdomain of a host in the map passes |
| `secret-outside-map` | warn | a new read of an environment variable whose name contains `KEY` / `SECRET` / `TOKEN` / `PASSWORD` / `DSN`… without an `env` row |
| `db-privilege` | warn | in migrations and `.sql`: `GRANT`, `SECURITY DEFINER`, `BYPASSRLS`, `DISABLE ROW LEVEL SECURITY`, `DROP POLICY`, `ALTER ROLE` without a `db` row whose value is a fragment of that line |
| `encoded-blob` | warn | a base64/hex literal longer than 200 characters in new lines (except `data:image/`) — a hidden payload or an embedded key |
| `map-missing` | warn | routes changed and there is no map — none of the above is checked |

What it does **not** do: it does not judge whether the guard is the *right* one for the resource
(doctor A1 vs patient A2) — that is an ownership boundary, and only a test with two accounts
checks it. That is what the `red-team` check is for.

**Skeleton.** `python3 run.py --skeleton` (telesma.sh does this itself at startup when the
map is missing and the project has routes) writes the map from the whole repository: all routes,
candidate roles from names in the window (`current_active_user`, `require_org_admin`,
`requireAuth`…), `?` wherever nothing was recognized, Ownership `?` on a path with a parameter,
hosts and secrets from the environment. The heuristic works **only** for the skeleton — the
check takes guards from the map. `--stdout` = print instead of writing the file. A factory with a
literal yields its own role: `requireRole("doctor")` → `requireRole:doctor`, otherwise staff
roles merge into one. The token `requireRole("doctor")` also matches
`requireRole("doctor", "nurse")`. Measurements: a production FastAPI project — 234 routes, 16
with `?`; a Hono/Deno medical project — 235 routes, 9 with `?`, seven roles; in every case the `?`
routes were public by nature (health, `.well-known`, webhooks, login, static files, iCal with a
token).

**Skipped:** test files, build and dependency directories, `telesma/checks/`, `.claude/`, comment
lines (for hosts, secrets and blobs).
