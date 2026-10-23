---
tag: rest-api
keywords: rest, rest api, http api, openapi, swagger, endpoint, resource, status code, pagination, versioning, idempotency, problem details, api contract, webhook
---

# Guidelines: REST API design

Framework-independent rules; the framework guideline (Hono, FastAPI, Spring, …) says how to implement them.

## Style

- Resources are plural nouns in `kebab-case`, ids as path segments: `/orders/{orderId}/line-items/{lineItemId}`; no verbs in paths — an action is a sub-resource (`POST /orders/{id}/cancellation`), not `/cancelOrder`
- Methods: `GET` safe and cacheable, `PUT` full replace, `PATCH` partial via JSON Merge Patch (`application/merge-patch+json`), `POST` create or non-idempotent action, `DELETE` idempotent (second call → `204` or `404`, one choice project-wide)
- Status codes exactly: `200` body, `201` + `Location` on create, `202` for async work (+ a status resource URL), `204` no body, `304` with ETags, `400` malformed, `401` not authenticated, `403` authenticated but denied, `404` missing or hidden, `409` state conflict/duplicate, `412` precondition failed, `415` wrong content type, `422` well-formed but invalid, `429` rate limited, `500` bug, `503` dependency down + `Retry-After`
- `4xx` is the caller's problem and says what to fix; `5xx` is ours and says nothing internal; a validation failure is never `500`, a database timeout is never `400`
- Bodies: JSON `camelCase`, `Content-Type: application/json; charset=utf-8`; timestamps RFC 3339 UTC (`2026-03-01T12:00:00Z`); money `{ "amount": "12.50", "currency": "EUR" }` as strings; ids as strings; enums `UPPER_SNAKE` strings
- Collections: `{ "items": [...], "nextCursor": "..." | null }` — never a bare top-level array (cannot be extended later)
- Pagination cursor-based: `?cursor=<opaque base64>&limit=`, `limit` default 20–50 and capped; offset only for admin screens. Filtering `?status=ACTIVE&createdAfter=…`, sorting `?sort=-createdAt,name` (leading `-` = descending), sparse fields `?fields=id,name`; every accepted parameter is documented, unknown ones → `400`
- Errors: RFC 9457 problem details, `Content-Type: application/problem+json`: `{ "type": "urn:app:error:validation", "title": "Validation failed", "status": 422, "detail": "…", "instance": "/orders/42", "errors": [{ "pointer": "/email", "message": "…" }] }` — `type` is a stable identifier clients switch on, `detail` is safe to show, no stack traces, SQL or class names
- Versioning: major only, in the path `/v1/…`; additive changes (new optional field, new endpoint, new enum value only where clients are told to tolerate unknowns) do not bump; removed/renamed fields, changed types or tightened validation do; the old major stays for a published sunset window with `Deprecation` and `Sunset` headers
- Idempotency: every `POST` that creates or charges accepts `Idempotency-Key` (client UUID); the server stores `(key, principal, requestHash, response)` with a 24 h TTL and replays the stored response on retry; same key with a different body → `422`
- Concurrency: `ETag` on `GET`, `If-Match` on `PUT`/`PATCH`/`DELETE` of mutable resources, `412` on mismatch (`428` when the header is required and missing)
- Auth: `Authorization: Bearer <token>` — never tokens in query strings (they land in logs); `WWW-Authenticate` on `401`; machine API keys hashed at rest, scoped, rotatable
- Rate limits: `429` + `Retry-After`, plus `RateLimit-Limit`/`RateLimit-Remaining`/`RateLimit-Reset` headers, keyed by principal (not IP alone), documented per tier
- `X-Request-Id` on every response (echoed if the client sent one), present in the problem details and in every log line for that request

## Project structure

- `openapi.yaml` (OpenAPI 3.1) is the contract and lives in the repo; design-first: the spec changes in the same PR as the code and is reviewed as the API change; runtime request/response validation against it (`express-openapi-validator`, FastAPI's native models, `springdoc` + bean validation) keeps the running API and the document one thing
- `components/schemas` for every body, `components/responses/ProblemDetails` reused by every operation, `components/securitySchemes` declared and applied globally, `operationId` on every operation (it becomes the generated client method name)
- Generated typed clients for first-party consumers (`openapi-typescript` + `openapi-fetch`, `openapi-python-client`); no hand-written fetch wrappers
- Three layers per operation: transport (parse, validate, map errors to problems) → service (rules) → repository; only the transport layer knows HTTP
- One central error mapper from domain errors (`NotFound`, `Conflict`, `Validation`, `Forbidden`) to problem details; handlers never build error bodies
- `/healthz` (liveness, no dependencies) and `/readyz` (dependencies) unauthenticated; everything else authenticated by default — an endpoint opts out explicitly

## Security

- Validate every input at the boundary against the schema: types, formats, `maxLength`, `minimum`/`maximum`, enums, `additionalProperties: false` on write bodies; cap body size (1 MB default) and array lengths
- Authorise every object access against the principal (owner/tenant), not only the route; a resource that is not yours is `404` (or `403` — one choice project-wide)
- Mass assignment: write DTOs enumerate writable fields; `id`, `createdAt`, `ownerId`, `role`, `balance` are never read from the body
- CORS: exact origin allowlist, no `*` with credentials; `415` on any `Content-Type` other than the declared ones; JSON only unless a format is required
- Redact `Authorization`, `Cookie`, `Idempotency-Key` values and request bodies with credentials from access logs
- Outbound webhooks: HMAC signature header + timestamp, retries with backoff, event id for consumer idempotency; inbound webhooks: verify the signature before parsing, answer `2xx` fast, process asynchronously

## Tests

- Contract tests run the app in-process (supertest, `TestClient`, `MockMvc` — no port) and validate every response against `openapi.yaml` (`jest-openapi`, `schemathesis`, `openapi-response-validator`); a response the spec does not describe fails
- Per operation: the happy path with exact status and body, and each documented `4xx`: malformed → `400`, invalid → `422` with the right `pointer`, no auth → `401`, wrong principal → `403`/`404`, duplicate → `409`, stale `If-Match` → `412`, unknown query parameter → `400` — asserting the problem `type` each time
- Pagination: walk a three-page collection to `nextCursor: null`; `limit` above the cap rejected; `-createdAt` order asserted
- Idempotency: same key twice → identical response and one side effect; same key, different body → `422`
- `schemathesis run openapi.yaml` in CI to fuzz for `500`s on unexpected input; a `500` in any test is a bug, never an expected result
- Breaking-change gate: `oasdiff breaking` against the main branch fails the build on removed fields, changed types, new required parameters
- Runner: the ecosystem's default; database via the project's disposable instance; external services mocked at the HTTP boundary (`msw`, `respx`, WireMock), never the HTTP client inside the app

## What to avoid

- Verbs in paths, `POST` for everything, `200` with `{ "success": false }`, ad-hoc error shapes per endpoint
- Top-level arrays, offset pagination on growing collections, unbounded `limit`, a `total` count computed on every list call
- Breaking changes without a major bump; `/v1.2/` minor versions; version only in a custom header
- Floats for money, local-time timestamps, sequential numeric ids that allow enumeration
- Tokens in query strings; `Access-Control-Allow-Origin: *` with cookies; accepting any `Content-Type`
- An OpenAPI document written by hand after the fact and left to drift from the code
- Unkeyed retries on `POST /payments` (double charge); `PUT` that silently partially updates
- Screens that need five calls to render — add a purpose-built read endpoint or `?include=` expansion instead of pushing N+1 to clients
- `500` for anything the client could have fixed; `detail` strings that echo exception messages
