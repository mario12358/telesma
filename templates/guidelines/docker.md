---
tag: docker
keywords: docker, compose, compose.yaml, container, dockerfile, image, deploy, network, secrets, volume, healthcheck, multi-stage, registry
---

# Guidelines: Docker / Compose

## Topology

- Services on a private container network; ONLY the HTTP/HTTPS entry layer is exposed to the internet
- The database port is NOT published on a public interface (no `ports:` for the database; administrative access via SSH/tunnel)
- Infrastructure configuration (compose, reverse proxy config etc.) versioned in the repository

## Images

- Images built in CI, versioned with an explicit tag (SHA/version) — never just `latest`
- The server does NOT build the application — ready artifacts are shipped to the server
- Multi-stage Dockerfile; only what is needed at runtime goes into the image; `.dockerignore` excludes `.git`, `node_modules`, `.env`, test data
- Base images pinned to a specific version tag (`node:22-slim`, `python:3.13-slim`), not `latest`; dependency-manifest layers (`package.json`/`pyproject.toml` + lockfile) copied and installed before the source so the cache survives code changes
- The process in the container runs as non-root (`USER`); `HEALTHCHECK` or a compose healthcheck for every long-running service
- `hadolint` on Dockerfiles in CI — run it; do not argue with it

## Compose

- `docker compose` (v2 plugin) with `compose.yaml` — not the `docker-compose` binary, no `version:` key
- A healthcheck for every service; dependencies through `depends_on: condition: service_healthy`
- Database data on a named volume
- `restart: unless-stopped` for long-running services
- Resource limits (`deploy.resources.limits`, `cpus`, `mem_limit`) as explicit configuration when services share a host — not left to chance
- `compose.override.yaml` for local-only additions (bind mounts, debug ports); production runs with an explicit `-f compose.yaml -f compose.prod.yaml`

## Secrets and configuration

- Secrets NEVER in the repo as plain text and NEVER baked into the image (no `ARG`/`ENV` with a secret — it stays in the layer history; `RUN --mount=type=secret` for build-time credentials)
- Configuration through environment variables / env files outside the repo (`.env` in `.gitignore`, `.env.example` in the repo); compose `secrets:` for files the process reads at runtime
- The same images + different configuration = a different environment

## Deployment and migrations

- Database migrations as an EXPLICIT deployment step (a separate command/task), not automatic at container start
- A manually triggered deployment is OK with a single environment — but it must be repeatable (a script/task, not a sequence from memory)
- Rollback = going back to the previous image tag; migrations must make that possible (N-1 compatibility)

## What to avoid

- `ports:` on the database and internal services
- Building images on the target server
- `latest` as the only deployment tag
- Secrets in `compose.yaml`, the Dockerfile or ARG/ENV committed to the repo
- Containers running as root without a reason
- `COPY . .` before installing dependencies (every code change invalidates the dependency layer)
