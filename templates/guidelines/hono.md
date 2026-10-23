---
tag: hono
keywords: hono, api, http, routing, middleware, endpoint, rest, zod, validation, contract, openapi, backend, jsx
---

# Guidelines: Hono 4

## Structure

- One domain module = one router file (`routes/bookings.ts` with its own `new Hono()`), composed into the app with `app.route("/bookings", bookings)`
- Handlers are thin: validation → call into the domain/database layer → map to a response. Zero business logic in handlers
- Typed context: `new Hono<{ Variables: {...} }>()`; request data through `c.set`/`c.get`, not through global variables

## Input validation

- Every input (body, query, param) validated AT THE BOUNDARY: zod + `@hono/zod-validator` (`zValidator('json', schema)`); handlers read `c.req.valid('json')`, never `await c.req.json()` directly
- zod schemas shared with the frontend where this really prevents the contract from drifting apart; a typed client via `hc<typeof app>()` when the frontend is TypeScript
- OpenAPI needed → `@hono/zod-openapi` generates it from the same schemas; never a hand-written spec next to the code
- Application validation is UX and fast failure — the database constraints remain the source of integrity

## Errors

- `HTTPException` for expected errors; a central `app.onError` maps exceptions to responses
- A consistent error format across the whole API (code, message, optionally field details)
- Never return a stack trace or SQL details to the client — details go to the logs
- 401 vs 403 vs 404 deliberately: lack of access to someone else's resource is usually a 404 (do not reveal that it exists)

## Middleware

- A fixed, explicit order: logger/trace → auth → tenant context → routers
- The auth middleware sets the identity in the context; it is passed to PostgreSQL per transaction (`SET LOCAL` — see the postgres guidelines)

## Tests

- API contract tests through `app.request('/bookings', { method: 'POST', body, headers })` — without opening a port; runner per runtime (Vitest on Node/Bun, `Deno.test` on Deno)
- Also test the negative cases: no auth, someone else's tenant, invalid input (expect `400` with the field in the error body)
- Test the real router, not the handler function alone — middleware order is part of the behaviour

## What to avoid

- Business logic and raw SQL directly in handlers
- Validation "somewhere in the middle" instead of at the boundary
- Authorisation scattered across ifs per endpoint — use middleware + the boundary in the database
- Module-level global state to carry request data
