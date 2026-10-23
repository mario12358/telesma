---
tag: mongodb
keywords: mongodb, mongo, mongoose, pymongo, motor, document database, nosql, aggregation, bson, objectid, atlas, mongodb-memory-server, collection, change streams
---

# Guidelines: MongoDB

## Style

- Collections plural `camelCase` (`users`, `orderItems`), fields `camelCase`; `_id` stays `ObjectId` unless a natural immutable key exists
- One schema definition per collection in code (Mongoose schema, Pydantic model, Prisma model) is the only place fields are declared; no ad-hoc field writes anywhere else
- Server-side validation on every collection: `createCollection(name, { validator: { $jsonSchema: {...} }, validationLevel: "strict", validationAction: "error" })` — the application model is UX, the validator is the integrity boundary
- Dates as BSON `Date` (UTC), never ISO strings; money as `Decimal128` or integer minor units, never `Double`
- Updates with operators (`$set`, `$inc`, `$push`, `$addToSet`, `$setOnInsert`), never read → mutate in memory → replace the whole document — concurrent writers overwrite each other
- Filters built from typed objects; user input never becomes an operator: reject or strip keys starting with `$` (NoSQL injection via `{ "password": { "$gt": "" } }`)
- `writeConcern: { w: "majority" }` and `readConcern: "majority"` for anything that must survive a failover; `retryWrites=true` in the URI
- Soft delete `deletedAt: Date | null` plus a partial index `{ partialFilterExpression: { deletedAt: null } }` on the active-row queries

## Project structure

- `src/db/client.ts` (or `db/client.py`): one `MongoClient` per process, created at startup and shared — the client owns the pool; never a client per request
- `src/models/<collection>.ts`: schema + indexes + validator declared together; `src/repositories/` wraps collection access; services never call `db.collection()` directly
- Indexes declared in code and applied by an explicit idempotent `ensureIndexes` deploy step (`createIndexes`), not `autoIndex: true` at application start in production
- Migrations in `migrations/<timestamp>_<description>.ts` with a runner (`migrate-mongo` style) and a `changelog` collection; documents carry `schemaVersion`; large collections migrate lazily on read, small ones eagerly in `bulkWrite` batches of ~1000
- Connection string from env with the database name in the URI; separate users for the application (`readWrite`) and migrations/index management (`dbAdmin`)

## Schema design

- Design from the queries: list the top read patterns first, then shape documents so each is one indexed `find`; do not model entities first
- Embed when the children are read with the parent, owned by it and bounded in count (address, order lines); reference by `parentId: ObjectId` when children are queried alone, shared, or unbounded (comments, events, logs)
- Unbounded arrays are a bug: the 16 MB document limit is hard and performance degrades long before — move them to their own collection indexed on the parent id, or use the bucket pattern (one document per parent per time window)
- Denormalise deliberately: copy a stable display field (`authorName`) into the child and accept the fan-out update; never copy mutable money/status fields
- Polymorphic documents in one collection carry a `type` discriminator as the first key of the compound index
- Multi-document transactions exist (replica set required, 60 s default) but are a design smell — one logical write should be one document; use `findOneAndUpdate` with the expected old state in the filter for optimistic concurrency

## Indexes and aggregation

- Every production query has a supporting index, proven with `explain("executionStats")`: `IXSCAN`, `totalDocsExamined` ≈ `nReturned`, no `COLLSCAN`, no in-memory `SORT`
- Compound index order Equality → Sort → Range (ESR); one well-chosen compound index beats three single-field ones
- `unique: true` for natural keys (email, slug), partial for optional unique fields, TTL index `{ expireAfterSeconds }` on `createdAt` for sessions, tokens and logs
- `$regex` uses an index only as `^prefix`; real text search goes through a text index or Atlas Search
- Pipelines: `$match` first (hits the index), `$project` early, `$lookup` last and only on an indexed foreign field; `$group` over an unbounded set needs `allowDiskUse: true` and probably belongs in a batch job
- Pagination by cursor (`{ _id: { $gt: lastId } }` or `(sortField, _id)` pair), not `skip()` beyond the first pages
- Change streams (`watch()`) for reacting to writes instead of polling; resume tokens persisted

## Tests

- A real `mongod`: `mongodb-memory-server` (Node) or Testcontainers `mongo` image (any language), started as a replica set (`MongoMemoryReplSet`) so transactions and change streams work; never a mocked driver
- One database per test file (`app_test_<file>_<worker>`), `deleteMany({})` per collection in `beforeEach`, `dropDatabase()` in `afterAll`
- Test setup runs the real `ensureIndexes` and validators — an invalid document must fail on the server validator, not only on the application model
- Test the failure modes: duplicate key `E11000` mapped to a domain conflict, validator rejection, an update with `matchedCount === 0` handled, a `$`-prefixed key in input rejected, a conflicting concurrent `findOneAndUpdate` losing cleanly
- An `explain()` assertion on the hot queries (`stage !== "COLLSCAN"`) catches a dropped index in CI
- Runner: `vitest`/`jest` with a global setup starting the memory server once; `pytest` with a session-scoped container fixture and `pymongo`/`motor`

## What to avoid

- Unbounded arrays, documents near 16 MB, nesting deeper than 2–3 levels, "just store the JSON" collections with no validator
- `$where`, `mapReduce`, `$function`, server-side JavaScript of any kind; filters from untrusted JSON without stripping `$` keys
- `doc.save()` / full-document replace in concurrent code; relying on Mongoose defaults (`strict: false`, `autoIndex`, `bufferCommands`) in production
- `find({})` without projection and limit; `skip(n)` with large n; `countDocuments()` on big collections where `estimatedDocumentCount()` or a counter document will do
- A relational domain (many-to-many everywhere) in MongoDB with `$lookup` compensating — then a relational database is the right tool
- Multi-document transactions as the normal write path; a single-node deployment where transactions, change streams and `w: "majority"` cannot work
- Files in documents (GridFS only for legacy) — object storage and a key
- A new `MongoClient` per request, or the connection URI in code
