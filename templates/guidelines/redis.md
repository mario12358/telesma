---
tag: redis
keywords: redis, valkey, ioredis, node-redis, redis-py, cache, caching, ttl, pub/sub, streams, rate limit, lua script, session store, bullmq
---

# Guidelines: Redis

## Style

- Key names `<app>:<entity>:<id>[:<field>]`, lowercase, `:` separated (`shop:user:42:session`, `shop:cache:product:7`); every prefix is a function in one `keys.ts`/`keys.py` module — never string concatenation scattered across the code
- Every cache-like key gets its TTL in the same command: `SET key value EX 3600`, `HSET` + `EXPIRE` inside `MULTI`; a key without TTL is a deliberate decision with a comment saying why
- Structure follows the access pattern: Hash for an object with independently updated fields, Sorted Set for leaderboards/time ranges/scheduling, Set for membership, List with `LPUSH` + `LTRIM` for a bounded recent-items window, String for blobs and counters, Stream for an event log, HyperLogLog for approximate distinct counts
- One serialisation codec project-wide (JSON or MessagePack), shape changes versioned in the prefix (`shop:v2:cart:…`); never `pickle` or Java serialisation (deserialisation RCE)
- Read-modify-write is always atomic: a single command (`INCR`, `HINCRBY`, `SET NX`, `GETDEL`), `WATCH` + `MULTI`/`EXEC`, or a Lua script — never GET → compute in the client → SET
- Lua scripts: short, deterministic, every key passed in `KEYS[]` (cluster-safe), values in `ARGV[]`, loaded once with `SCRIPT LOAD` and run with `EVALSHA`, fallback to `EVAL` on `NOSCRIPT`
- Cache-aside is the default: read cache → miss → read the source → `SET … EX` → return; invalidate by `DEL` on write, do not maintain caches in place; the database remains the source of truth
- Values read from Redis are untrusted input until parsed and validated like any other external data

## Project structure

- One client per process from `src/redis.ts`/`redis.py`: `ioredis` or `node-redis` (Node), `redis-py` with a `ConnectionPool` (Python), `go-redis` (Go), Lettuce (Java); the client owns pooling and reconnection
- A dedicated second client for blocking commands (`SUBSCRIBE`, `BLPOP`, `XREAD BLOCK`) — a subscribed connection cannot run anything else
- `REDIS_URL=rediss://user:pass@host:6379/0` from env; TLS and an ACL user in production; `connectTimeout` and per-command timeout of a few seconds; `maxRetriesPerRequest` bounded — the application degrades (serves without cache, returns 503 for queue writes), it never hangs
- Numbered databases (`SELECT 1`) are not isolation — prefixes are; one Redis per environment
- Domain wrappers (`SessionStore`, `RateLimiter`, `ProductCache`, `JobQueue`) are the only code that issues commands; business code never sees `redis.get`

## Patterns

- Rate limiting: fixed window = `INCR key` + `EXPIRE key window NX` in one Lua script (or `SET key 0 EX window NX` then `INCR`); sliding window = Sorted Set with `ZADD now now`, `ZREMRANGEBYSCORE 0 now-window`, `ZCARD`, `EXPIRE` — in one script so check and record are atomic; the caller gets `Retry-After`
- Distributed lock: `SET lock:<resource> <randomToken> NX PX <ttl>`; release only via a Lua script that compares the token before `DEL`; TTL longer than the longest critical section; Redlock only for a demonstrated multi-master need
- Pub/Sub is fire-and-forget (no persistence, no replay, slow subscribers drop messages): cache invalidation broadcasts and presence, nothing that must be processed
- Durable work and event logs use Streams: `XADD key MAXLEN ~ 100000 * …`, consumer groups with `XREADGROUP`, `XACK` after success, `XAUTOCLAIM` to recover from dead consumers, dead-letter after N deliveries — or a library built on them (BullMQ, Celery with the Redis broker)
- Sessions: a Hash per opaque random session id with a sliding `EXPIRE` on every touch; never user data in the key
- Enumerate keys only with `SCAN cursor MATCH prefix:* COUNT 1000` in a loop; batch independent commands with a pipeline, `MGET`/`HMGET` instead of N single gets
- Cluster mode: multi-key commands and Lua need one hash slot — hash tags `{user:42}:cart`, `{user:42}:prefs`

## Persistence and operations

- Redis is volatile even with AOF/RDB enabled: the system must survive a flush (cold cache, logged-out sessions, re-enqueued jobs) with zero loss in the system of record
- `maxmemory` set, eviction policy matched to the role: `allkeys-lru`/`allkeys-lfu` for a pure cache, `noeviction` plus memory alerts for queues/streams/locks — never one instance for both roles
- Watch `evicted_keys`, `keyspace_hits`/`misses`, `connected_clients`, `SLOWLOG GET`, `--bigkeys`; one big key with `O(N)` commands on it is the typical production incident
- ACL for the application user: `-@dangerous -@admin` (blocks `KEYS`, `FLUSHALL`, `CONFIG`, `DEBUG`, `SHUTDOWN`)

## Tests

- A real Redis/Valkey in Docker for integration (Testcontainers or a compose service); isolation per test by a unique key prefix or `FLUSHDB` on a dedicated test instance in `beforeEach`
- In-process fakes (`ioredis-mock`, `fakeredis`) only for unit tests of logic around the client; anything about Lua, TTL, atomicity, Streams or Pub/Sub runs against the real server
- TTL without sleeping: assert `TTL key` is in the expected range right after the write; test expiry handling with `PEXPIRE key 1` and a short wait, or an injected clock
- Test the failure modes: Redis down → the cache wrapper returns a miss and logs, the request still succeeds; rate limiter at the exact boundary (nth allowed, n+1th rejected, window reset re-allows); a lock not released by a non-owner token; a crashed consumer's message re-delivered by `XAUTOCLAIM`
- A unit test asserts the exact key strings produced by the `keys` module — renaming a prefix silently orphans production data
- Runner: the ecosystem's default (`vitest`/`jest`, `pytest`); one container per test file via global setup

## What to avoid

- `KEYS *`, `FLUSHALL`, `SMEMBERS`/`HGETALL`/`LRANGE 0 -1` on unbounded keys in application code
- Redis as the primary store for orders, money, accounts — anything that must not be lost
- Secrets, API keys, raw passwords, or PII without TTL in Redis
- Keys without TTL that grow with users or time; values over 100 KB; Hashes with millions of fields
- `GET` → `if` → `SET` races; `SETNX` without `PX` (locks that live forever); `DEL` of a lock without checking the token
- A `SUBSCRIBE` connection reused for commands; Pub/Sub for durable messaging; polling a List with `LPOP` in a tight loop instead of `BLPOP`/Streams
- One instance shared by cache and queue (`allkeys-lru` evicts jobs; `noeviction` makes cache writes fail at `maxmemory`)
- A connection per request; commands without timeouts; retrying forever while the request waits
