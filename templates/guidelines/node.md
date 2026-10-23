---
tag: node
keywords: node, nodejs, express, fastify, npm, pnpm, package.json, esm, server, api, middleware, pino, zod, supertest, dotenv, backend
---

# Guidelines: Node.js server

## Style

- ESM only: `"type": "module"` in `package.json`, `import`/`export`, file extensions in relative imports (`./router.js`); no `require`, no `__dirname` (use `import.meta.dirname`)
- TypeScript on the server too (see the typescript guidelines); run with `tsx` in development, compile with `tsc` for production
- ESLint (flat config, `typescript-eslint`) + Prettier — run both; do not argue with them
- `async`/`await` everywhere; callback-style Node APIs through `node:fs/promises`, `node:timers/promises` or `util.promisify`
- Built-in modules imported with the `node:` prefix (`import { readFile } from "node:fs/promises"`)
- No dependency for what Node has built in: `fetch`, `node:test`, `node:crypto`, `AbortController`, `structuredClone`, `--env-file`, `--watch`
- Ids and tokens from `node:crypto` (`randomUUID()`, `randomBytes`), never `Math.random`

## Project structure

- `src/app.ts` builds and returns the app without listening; `src/server.ts` reads config and listens — tests import `app.ts`
- `src/routes/<domain>.ts` (HTTP only) → `src/services/<domain>.ts` (logic) → `src/db/`, `src/clients/` (I/O); handlers never contain business logic or SQL
- `src/config.ts` is the only reader of `process.env`: parses with zod at startup, exports a typed frozen object; a missing variable fails the start, not the first request
- `.env` only in development (`node --env-file=.env` or `dotenv` in the `dev` script); production gets real environment variables; `.env` ignored by git, `.env.example` committed
- `package.json` scripts are the single entry point: `dev`, `build`, `start`, `test`, `lint`, `typecheck`; CI runs the same scripts
- One package manager per repo (`pnpm` preferred); the lockfile committed and installed with `pnpm install --frozen-lockfile` / `npm ci`
- `engines.node` set and matching `.nvmrc` / `.node-version`

## Tests

- Vitest as the runner (`node:test` + `node:assert` when the project forbids dev dependencies); files `*.test.ts` next to the code or in `tests/`
- Run one file: `pnpm vitest run src/routes/orders.test.ts`; one test: `pnpm vitest run -t "rejects an empty body"`
- HTTP tests through `supertest` against the app from `app.ts` (`request(app).post("/orders").send(body)`) or Fastify's `app.inject()` — never open a real port in tests
- Every route: happy path, invalid body (400 with the error shape), missing auth (401), someone else's resource (404), one downstream failure (database/client throws → 500 without the internal message)
- Mock external HTTP with `msw` (`setupServer`) or `vi.spyOn(globalThis, "fetch")`; never mock your own modules to make a test pass
- Database: a real database in a container, migrations applied in `globalSetup`, each test inside a transaction or on a truncated schema
- `vi.useFakeTimers()` for retry/backoff/timeout logic; assert that an `AbortSignal` reaches outbound calls
- Graceful shutdown has a test: call `close()` (or send SIGTERM to a spawned process) and assert in-flight requests finish and the process exits cleanly

## Errors, logging and shutdown

- One `AppError extends Error` with `statusCode` and `code`; a central error handler maps it to `{ error: { code, message } }` and turns everything else into a 500 — never send `err.stack` or an unknown `err.message` to the client
- `process.on("unhandledRejection")` and `process.on("uncaughtException")`: log and exit non-zero — do not keep serving from an unknown state
- `pino` for logging: one instance in `src/logger.ts`, child loggers with a request id, structured fields (`log.info({ orderId }, "order created")`); `pino-pretty` only in development; no `console.log` in server code
- Redact secrets in the pino config (`redact: ["req.headers.authorization", "*.password"]`)
- Graceful shutdown on SIGTERM/SIGINT: stop accepting connections (`server.close()` / `app.close()`), finish in-flight requests, close database pools, exit; a hard timeout (10 s) forces the exit
- Every outbound call has a timeout (`AbortSignal.timeout(ms)`); retries only for idempotent requests, with jittered backoff
- Validate every input (body, query, params, headers) with zod at the route; `z.object({...}).strict()` for bodies; the inferred type flows into the service

## Express and Fastify

- Express 5: async handlers may throw (no `next(err)` wrapping); the error middleware `(err, req, res, next)` is registered last; `express.json({ limit: "100kb" })`
- Express: `helmet()`, `cors({ origin: [...] })` with an explicit origin list, `express-rate-limit` on auth and public write endpoints, `app.disable("x-powered-by")`, `trust proxy` only behind a known proxy
- Fastify: a schema on every route (`schema: { body, response }`) through `fastify-type-provider-zod`, so zod drives both validation and serialisation
- Fastify: `@fastify/helmet`, `@fastify/cors`, `@fastify/rate-limit`, `@fastify/under-pressure`; its built-in pino (`logger: true`) instead of a second logger; shared decorators wrapped with `fastify-plugin`
- Fastify: routes registered per domain with a prefix (`app.register(orderRoutes, { prefix: "/orders" })`); one `setErrorHandler` at the root

## Security

- No `eval`, `new Function`, `vm.runInNewContext` with user data, or `child_process.exec` with interpolation — `execFile` with an argument array
- Prototype pollution: `Object.create(null)` or `Map` for user-keyed dictionaries; reject `__proto__`, `constructor`, `prototype` keys in merges; never deep-merge a request body into config or defaults
- User-supplied paths go through `path.resolve(root, input)` plus a check that the result starts with `root`
- Compare tokens with `crypto.timingSafeEqual`; hash passwords with `argon2` or `bcrypt`, never `createHash`
- Secrets only from the environment or a secret manager; never logged, never in responses
- `pnpm audit` / `npm audit` in CI; dependencies pinned by the lockfile, no `latest` or `*` ranges

## What to avoid

- `console.log`, `process.env.X` outside `config.ts`, `require`, mixing CommonJS and ESM
- Unhandled promises in handlers (a forgotten `await`, `.then` without `.catch`), fire-and-forget work with no error path
- Blocking the event loop: `fs.*Sync` after startup, synchronous crypto (`pbkdf2Sync`) in handlers, parsing huge bodies without a size limit
- Session or cache state in module-level variables — it breaks with more than one instance
- `cors()` with no options (every origin) or `origin: "*"` with credentials
- `res.send(err)` / `reply.send(err)` of raw errors, database error messages in responses
- Passing `req.body` straight into the database or ORM (mass assignment) — build the record from the parsed zod result
