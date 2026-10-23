---
tag: observability
keywords: otel, opentelemetry, otlp, logs, logging, metrics, monitoring, alerts, telemetry, tracing, health, grafana, prometheus, slo
---

# Guidelines: Observability

## Principle

- The system emits structured logs and basic telemetry FROM THE START — not "we will add it later"
- Open standards: OpenTelemetry and OTLP; a full stack (Grafana/Prometheus/Loki/Tempo/Alloy) optional, when needed — it is not a precondition for starting
- OTel SDK configured through the standard environment variables (`OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_RESOURCE_ATTRIBUTES`), not through code constants; auto-instrumentation for HTTP, database driver and queue client, manual spans only around business operations

## Logs

- Structured (JSON on stdout), one entry = one event
- Every entry: level, time, event name + the request's correlation/trace id — threaded through the whole path (middleware → domain → database); the trace id comes from the W3C `traceparent` header, and the logger attaches it automatically (context propagation), never by hand per call
- Levels used deliberately: ERROR = needs a reaction; WARN = degradation; INFO = business events; DEBUG off by default
- Message as a constant event name + fields (`log.info("booking.created", booking_id=…)`), not an interpolated sentence — fields are queryable, sentences are not
- Do NOT log sensitive data (personal/medical data, tokens, passwords, full payloads) — log identifiers
- Audit events are NOT logs — they go to the audit journal in the database (postgres guidelines)

## Metrics

Minimum scope:
- host: CPU, RAM, disk (free space!), IO
- application: request count, response codes, latency as a histogram (percentiles, not the mean) — labelled by route template (`/users/{id}`), never by raw path (cardinality explosion)
- database: connections (used vs pool size), locks, query time, database size
- execution time of the most important business operations
- Metric names follow the OTel semantic conventions (`http.server.request.duration`), units in the name or the unit field, not both

## Alerts

- The absolute minimum: disk running out of space (well in advance), application not responding, no connection to the database
- Availability monitoring also from OUTSIDE the server (an external healthcheck) — the server cannot be the only witness of its own failure

## Health endpoints

- `/healthz` (liveness — the process is alive) and `/readyz` (readiness — the database is reachable)
- Used by the container healthcheck and by external monitoring; no sensitive data in the response; excluded from access logs and request metrics (they drown the signal)

## Tests

- A test asserts that the critical operation emits its log event and span with the expected attributes (in-memory exporter / captured logger) — telemetry that nobody tests silently disappears in a refactor
- A test proves that the sensitive fields are NOT in the log output (assert on their absence)

## What to avoid

- Unstructured logs (printf debugging in production)
- Sensitive data in logs, metrics and span attributes
- The mean as the only latency measure — look at p50/p95/p99
- Telemetry tied to a closed vendor instead of OTLP
- Alerts on everything — an alert nobody reacts to teaches people to ignore alerts
