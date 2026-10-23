---
tag: svelte
keywords: svelte, svelte5, sveltekit, runes, state, derived, props, load function, form actions, adapter, vite, vitest, playwright, page.svelte, server.ts
---

# Guidelines: Svelte 5 and SvelteKit

## Style

- Runes in all new code: `$state`, `$derived`, `$effect`, `$props`, `$bindable` — no `export let`, no `$:` statements, no `createEventDispatcher`
- `<script lang="ts">`; typed props: `let { user, compact = false, onselect }: { user: User; compact?: boolean; onselect?: (id: string) => void } = $props()`; children through the `children` snippet and `{@render children?.()}`
- Callback props (`onselect={...}`) instead of events; `$bindable()` only for two-way binding the parent really needs
- Component files `PascalCase.svelte`; routes under `src/routes/` with the Kit names: `+page.svelte`, `+page.ts`, `+page.server.ts`, `+layout.svelte`, `+layout.server.ts`, `+server.ts`, `+error.svelte`
- Prettier with `prettier-plugin-svelte` + ESLint with `eslint-plugin-svelte` + `svelte-check` — run them; do not argue with them
- `{#each items as item (item.id)}` always keyed; `{#if}`/`{:else}` over ternaries in markup
- Styles in the component `<style>` block (scoped by default); global styles only in `src/app.css`

## Project structure

- `src/lib/` (imported as `$lib`): `components/`, `server/` (database, secrets, API clients), `state/` (`.svelte.ts` modules), `utils/`
- Anything under `src/lib/server/` or named `*.server.ts` is server-only — Kit fails the build when a client file imports it; every secret-touching module lives there
- Env: `$env/static/private` / `$env/dynamic/private` for secrets (server-only), `$env/static/public` for `PUBLIC_*` values the browser may see; never `process.env` or `import.meta.env` directly
- `src/hooks.server.ts`: auth (`event.locals.user` from the session cookie) and request-wide concerns; `handleError` for logging; `src/app.d.ts` types `App.Locals`, `App.PageData`, `App.Error`
- Route groups `(app)`, `(marketing)` for layout boundaries without URL segments; `[param]` and `[...rest]` folders for dynamic segments
- One adapter in `svelte.config.js` matching the deployment target (`adapter-node`, `adapter-static`, `adapter-vercel`, `adapter-cloudflare`); `adapter-auto` only until the target is known
- Path aliases in `kit.alias` of `svelte.config.js`, not only in `vite.config.ts`

## Tests

- Vitest with two projects in `vite.config.ts`: `client` (`environment: "jsdom"`, `*.svelte.test.ts` and component tests with `@testing-library/svelte`) and `server` (`environment: "node"`, `*.test.ts` for `load`, actions, `+server.ts`, `$lib/server`)
- Run one: `pnpm vitest run src/lib/components/OrderForm.svelte.test.ts`; e2e: `pnpm playwright test e2e/checkout.test.ts`
- Component tests: `render(Component, { props })`, `screen.getByRole`, `await user.click(...)`; assert rendered output and callback-prop calls, not internal `$state`
- Rune logic outside components (`.svelte.ts`) is tested in `*.svelte.test.ts` files so the runes compile; wrap in `$effect.root` when effects are involved and `flushSync()` before asserting
- `load` functions and form actions are plain functions: build a fake event (`{ params, url, locals, cookies, request: new Request(...) }`), `vi.mock("$lib/server/db")`, assert the returned data; `redirect()`/`error()` throw — `await expect(load(event)).rejects.toMatchObject({ status: 303 })`
- `+server.ts` handlers: `const res = await GET(event)`; assert `res.status` and `await res.json()`
- Playwright for every user flow: `webServer` runs `pnpm build && pnpm preview` in `playwright.config.ts`; one login saved as `storageState` and reused
- HTTP mocked at the boundary (`msw`, or the `fetch` passed into `load`); never mock Svelte's runtime

## Loading data and mutations

- `load` in `+page.server.ts` when it needs secrets, the database or cookies; `+page.ts` only for public data the client may also fetch; return plain serialisable objects (no class instances, no functions)
- Use the `fetch` handed to `load`, not the global one — it forwards cookies and inlines responses during SSR
- Layout `load` provides shared data; `await parent()` in a child only when the child needs it; independent fetches returned as promises to stream, or awaited together with `Promise.all`
- Mutations are form actions in `+page.server.ts` (`export const actions = { create: async ({ request, locals }) => ... }`): validate `formData` (zod; `sveltekit-superforms` when forms are many), check `locals.user`, `return fail(400, { errors })` on invalid input, `redirect(303, ...)` on success
- Forms work without JavaScript (`<form method="POST" action="?/create">`); `use:enhance` adds progressive enhancement; `invalidateAll()` / `invalidate(url)` to refresh data after client-side changes
- `+server.ts` endpoints only for non-form clients (webhooks, JSON API); respond with `json(...)` from `@sveltejs/kit`
- Shared client state in `.svelte.ts` modules with `$state` (`export const cart = $state<Cart>({ items: [] })`) or `setContext`/`getContext` for per-tree state; `svelte/store` only for existing stores or libraries that require them
- Server-side module variables are shared by every user — per-request data lives in `locals`, the session or the database
- `$derived` for computed values; `$effect` only to synchronise with the outside world (DOM, timers, third-party libraries), never to set other state

## What to avoid

- Mixing Svelte 4 syntax (`export let`, `$:`, `on:click`, `<slot>`) with runes in one component; `on:click` → `onclick`
- Importing `$lib/server/*` or `$env/*/private` from `.svelte` files or `+page.ts`
- Fetching in `onMount` / `$effect` what belongs in `load`; global `fetch` inside `load`
- Returning class instances or functions from `load` (not serialisable)
- `$effect` writing to `$state` it also reads (infinite loop); `$state` on a large object you only replace — use `$state.raw`
- Module-level `$state` or caches in server code holding per-user data
- `try/catch` around `redirect()` / `error()` — they throw on purpose
- `{@html ...}` with unsanitised content; `adapter-auto` in a production config
