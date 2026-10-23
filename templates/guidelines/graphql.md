---
tag: graphql
keywords: graphql, gql, sdl, resolver, apollo, graphql-yoga, pothos, strawberry, dataloader, relay, urql, codegen, subscriptions, persisted queries
---

# Guidelines: GraphQL

## Style

- Default is schema-first: the SDL in `schema/*.graphql` is the contract; resolver types and client types are generated from it (`@graphql-codegen/cli` with `typescript-resolvers`; `ariadne` on Python). Code-first (Pothos, Strawberry) only when the team already owns it — never both in one service
- Naming: types `PascalCase`, fields/arguments `camelCase`, enum values `UPPER_SNAKE`; no `get`/`fetch` prefixes (`user(id:)`, not `getUser`); mutations verb+noun (`createOrder`, `cancelOrder`) with one `CreateOrderInput` and one `CreateOrderPayload` each
- Non-null by default (`String!`, `[Item!]!`); nullable only where absence is a real state or where a partial failure should null one field instead of the whole response (expensive or cross-service fields)
- `ID!` everywhere, globally opaque (base64 `Type:dbId` or UUID); never auto-increment integers
- Pagination on every growable list as Relay connections: `edges { cursor node } pageInfo { hasNextPage endCursor }`, arguments `first`/`after`, `first` capped (100); no `offset`/`limit`
- Expected domain outcomes are part of the schema: `union CreateOrderPayload = CreateOrderSuccess | ValidationError | NotFoundError` (or `userErrors: [UserError!]!` in the payload); the top-level `errors` array is only for unexpected failures and auth, with `extensions.code` in `UNAUTHENTICATED | FORBIDDEN | BAD_USER_INPUT | INTERNAL_SERVER_ERROR` and never a stack trace or database message
- The schema is unversioned: `@deprecated(reason: "use fooV2")`, remove only after usage telemetry shows zero callers; never `/v2/graphql`
- Custom scalars from `graphql-scalars` (`DateTime`, `EmailAddress`, `URL`, `PositiveInt`, `JSON` only for genuinely opaque blobs) instead of `String` for typed data

## Project structure

- `schema/<domain>.graphql` (merged at build), `src/resolvers/<domain>.ts` mirroring it, `src/loaders/` (DataLoaders), `src/context.ts`, `src/generated/` (codegen output — committed or built in CI, one choice)
- Resolvers are thin: parse args → authorise → call a service → return plain objects; zero SQL and zero business rules in resolvers
- Context built once per request: principal, a fresh set of DataLoaders, request id, abort signal; nothing request-scoped in module globals
- Server: Apollo Server or GraphQL Yoga (Node), Strawberry (Python), gqlgen (Go); introspection and the playground off in production unless the API is public
- Clients: `urql` or Apollo Client with `graphql-codegen` `client-preset`; operations in `.graphql` files or `graphql()` templates, hooks and types generated; a component asks for exactly the fields it renders (fragments colocated with components)

## N+1, authorisation, limits

- Every relation field resolves through a DataLoader keyed by parent id (`ctx.loaders.userById.load(order.userId)`); loaders are created per request in the context, never shared (cache leaks between users)
- Batch functions run one query (`WHERE id = ANY($1)`) with the key list bounded, and return results in key order with `null`/`Error` for misses
- Authorisation in one layer mapped to the schema — a directive (`@auth(requires: ADMIN)`) or a shield/middleware — not ifs inside resolvers; object-level access is checked where the object is loaded, field-level (`User.email`) where the field resolves; a resolver never assumes the parent already checked
- Denied object reads return `null` with `NOT_FOUND` or `FORBIDDEN` consistently across the schema — do not reveal existence by varying it
- Server limits before execution: depth (≈10), complexity with list multipliers (`graphql-armor` or `graphql-query-complexity`), alias and batch caps, body size; introspection depth limited too
- Persisted queries for first-party clients: a build-time allowlist of operation hashes, arbitrary operations rejected in production (APQ alone is a cache, not protection)
- Mutations return the mutated object so client caches update; an idempotency key input field for retry-safe mutations
- Subscriptions over `graphql-ws`; the pub/sub behind them is external (Redis) once more than one instance runs
- CSRF prevention on (`Content-Type: application/json` or a custom header required), explicit CORS allowlist, `GET` only for persisted queries

## Tests

- Schema in CI: SDL parses, codegen passes, `graphql-inspector diff` against the main branch fails on breaking changes (removed field, tightened nullability, removed enum value)
- Operation tests run against the executable schema with a test context, no HTTP port: `server.executeOperation({ query, variables }, { contextValue })` (Apollo), `yoga.fetch` (Yoga), `schema.execute` (Strawberry); assert `data` and the exact `errors[0].extensions.code`
- One test per branch of every payload union, and per auth case: unauthenticated → `UNAUTHENTICATED`, wrong role → `FORBIDDEN`, someone else's object → `null`
- N+1 test: a list query with 20 parents and a relation; a query counter on the repository stays constant (2–3), not 1 + 20
- Limit tests: one level over the depth limit and one unit over the complexity budget are rejected before any resolver runs
- Loader tests: N `load` calls → one batch call, result order matches key order, a miss returns `null`
- Client tests mock at the operation level (`msw` GraphQL handlers), never the generated hook; `tsc` on generated types catches renamed fields at build time
- Runner: the ecosystem's default (`vitest`/`jest`, `pytest`); database via the project's disposable instance

## What to avoid

- Exposing the database 1:1 (every table, column and FK as a field) — the graph is shaped by client use cases
- Resolvers querying per parent; singleton DataLoaders; `include`/eager-loading everything instead of loaders
- `JSON`/`String` for dates, ids, enums; everything nullable "to be safe" or everything non-null (one failing field kills the response)
- Throwing for expected domain outcomes; leaking `error.message` from the database; stack traces in `extensions`
- Public introspection/playground in production; an internet-facing API with no depth, complexity or persisted-query limits
- `userV2` fields or versioned endpoints instead of `@deprecated` plus additive change
- A catch-all `doThing(input: JSON)` mutation; business logic in resolvers
- Hand-written response types, `any` on query results, over-fetching whole objects for two fields
- Legacy `subscriptions-transport-ws`; in-memory pub/sub with several instances
