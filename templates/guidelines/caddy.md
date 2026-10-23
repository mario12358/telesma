---
tag: caddy
keywords: caddy, reverse proxy, proxy, tls, https, certificate, caddyfile, ingress, rate limit, edge, security headers
---

# Guidelines: Caddy

## Role

- Caddy is the only HTTP/HTTPS entry into the system: TLS, reverse proxy, basic edge configuration
- The application and the database are never exposed directly to the internet

## Configuration

- `Caddyfile` versioned in the repository, mounted into the container (alternatively generated from the container configuration — record the choice in PROJECT_CONTEXT)
- `caddy fmt --overwrite Caddyfile` before committing and `caddy validate --config Caddyfile` in CI — run them; do not argue with the formatter
- `reverse_proxy` to the application by SERVICE NAME on the private container network (`app:8000`), not by IP
- Automatic TLS (ACME) — do not turn it off without a reason; a volume for `/data` (`caddy_data`), so that a restart does not burn through certificate issuance limits; `tls internal` only for local development
- Caddy's admin API (`:2019`) not reachable from outside; `admin off` when nothing uses it

## Headers and edge hygiene

- Security headers at the edge via the `header` directive (one per line inside its block): `Strict-Transport-Security "max-age=31536000; includeSubDomains"`, `X-Content-Type-Options nosniff`, `Content-Security-Policy "frame-ancestors 'none'"`
- `encode zstd gzip` for compressible responses
- Explicit body size limits for endpoints that accept data (`request_body { max_size 10MB }`)
- Explicit proxy timeouts: `transport http` inside `reverse_proxy` with `dial_timeout` and `response_header_timeout`
- Static assets served by Caddy (`file_server`, `handle_path /assets/*`), not proxied to the application

## Rate limiting

- Request rate limiting is NOT a standard part of core Caddy — it needs a module or an implementation in the application layer
- Choosing the layer (Caddy with a module vs middleware in the application) is a decision made during implementation — record it and cover the expensive operations

## Logs

- Structured access logs (`log { output stdout format json }`) — input for diagnostics and telemetry
- Do not log secrets/tokens from headers — the `filter` log encoder with `request>headers>Authorization delete` (and the same for `Cookie`)

## What to avoid

- Exposing application/database ports "for a moment" next to Caddy
- Edge configuration done by hand on the server, outside the repository
- Terminating TLS in the application instead of in Caddy
