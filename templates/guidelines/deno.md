---
tag: deno
keywords: deno, deno2, runtime, deno.json, jsr, permissions, tasks, std, deno test, deno deploy, fresh, typescript runtime
---

# Guidelines: Deno 2

## Project configuration

- `deno.json` is the centre of the project: `tasks`, `imports` (import map), `compilerOptions`, `fmt`, `lint`
- Do NOT create `tsconfig.json` or `package.json` — TypeScript options go into `compilerOptions` in `deno.json`
- Dependency versions pinned in the import map, not scattered across files
- `deno.lock` committed to the repo

## Dependencies

- Prefer `jsr:` (JSR) and the standard library `@std/*`; `npm:` only when there is no equivalent
- Add with `deno add jsr:@std/path` / `deno add npm:zod` (writes the import map entry); import through the alias (`import { join } from "@std/path"`), not full specifiers in code
- Do not add a dependency for something that exists in `Deno.*` or `@std/*` (fs, path, crypto, dotenv, testing, assert)
- `node:` built-ins (`import { readFile } from "node:fs/promises"`) only when porting Node code — new code uses `Deno.*`/`@std/*`

## Permissions (sandbox)

- Run with EXPLICIT, minimal flags: `--allow-net=host:port`, `--allow-env=NAME1,NAME2`, `--allow-read=path`
- `-A` / `--allow-all` at most locally in dev — never in CI or in the production image
- Permission flags written in the tasks in `deno.json` — one source of truth for how to run things

## Tasks

- Every project operation as a task: `deno task dev`, `test`, `check`, `db:migrate`
- CI calls the same tasks as a developer — zero commands that exist "only in CI"

## Tests

- `Deno.test` + `@std/assert` / `@std/expect`; `*_test.ts` files next to the code or in `tests/`; one test: `deno test src/x_test.ts --filter "name"`
- `deno test` with minimal permissions — a test that does not need the network does not get the network
- Time and HTTP in tests: `@std/testing/time` (`FakeTime`) and `@std/testing/mock` (`stub`) — no real clocks, no real network
- Resource sanitizers stay enabled (they catch leaked connections/timers) — fix the leak, do not disable the sanitizer

## Quality

- `deno fmt` and `deno lint` are built in — no Prettier/ESLint; `deno check` in CI before the tests
- Formatting is not up for discussion — fmt decides

## Container

- Image based on the official `denoland/deno`; `COPY deno.json deno.lock` + `deno install --frozen` as a separate layer before COPYing the code (`deno cache` is the legacy name)
- Run in the container with the same explicit permission flags as in the tasks; `deno compile` to ship a single binary when the image needs no runtime

## What to avoid

- `npm:` when a `jsr:`/`@std/*` equivalent exists
- Node-isms: `process.env` (use `Deno.env.get`), `__dirname` (use `import.meta`), `require`
- `-A` in CI/production
- Dynamic imports from URLs built at runtime
