---
tag: nextjs
keywords: nextjs, next, app router, server components, server actions, route handler, rsc, ssr, ssg, revalidate, metadata, middleware, vercel, fullstack
---

# Guidelines: Next.js (App Router)

## Style

- App Router only (`app/`); no new code in `pages/`
- Components are Server Components by default; `"use client"` only on the leaf that needs state, effects, browser APIs or event handlers — keep that leaf small
- `next lint` (`eslint-config-next`) + Prettier + `tsc --noEmit` in the `lint`/`typecheck` scripts — run them; do not argue with them
- Route files by convention only: `page.tsx`, `layout.tsx`, `loading.tsx`, `error.tsx`, `not-found.tsx`, `route.ts`; other files live outside `app/` or in `_components/` (underscore = not a route)
- `next/link`, `next/image` (explicit `width`/`height` or `fill`), `next/font` — not raw `<a>`, `<img>`, `<link>` for fonts
- Async server components: `export default async function Page({ params, searchParams })` with `await params` / `await searchParams` (they are promises)

## Project structure

- `app/(group)/<route>/page.tsx`; route groups for layouts that do not change the URL (`(marketing)`, `(app)`)
- `components/` (shared UI), `lib/` (server utilities), `lib/data/<domain>.ts` (data access), `actions/` (server actions), `lib/db.ts` (database client singleton kept on `globalThis` to survive hot reload)
- Data-access and secret-touching modules start with `import "server-only"` — the build fails if a client component imports them
- `app/api/<domain>/route.ts` only for callers outside the app (webhooks, mobile clients); pages read data in server components, mutate through server actions
- `env.ts` parses `process.env` with zod and exports a typed `env`; server variables never prefixed `NEXT_PUBLIC_`; everything `NEXT_PUBLIC_*` is inlined into the client bundle and public
- `middleware.ts` at the root: redirects, locale, a cheap cookie check for auth — no database calls; real authorisation is repeated in the page, action or handler
- `next.config.ts` typed; `images.remotePatterns` explicit; security headers in `headers()`

## Tests

- Vitest + `@vitejs/plugin-react` + React Testing Library; `environment: "jsdom"` for components, `// @vitest-environment node` at the top of action and route-handler tests
- Run one: `pnpm vitest run components/OrderForm.test.tsx`; e2e: `pnpm playwright test e2e/checkout.spec.ts`
- Async server components cannot be rendered by Testing Library — test the extracted data function directly and the page through Playwright
- Server actions: call the exported function with a `FormData`, `vi.mock("next/cache", () => ({ revalidatePath: vi.fn(), revalidateTag: vi.fn() }))`, mock `lib/data`, assert the result object and the revalidation call
- Route handlers: `const res = await GET(new Request("http://test/api/orders?page=1"))`, assert `res.status` and `await res.json()`
- Playwright for every user flow in the spec: `webServer` runs `next build && next start` (never `next dev`), one login saved as `storageState` and reused
- Mock `next/navigation` (`useRouter`, `useSearchParams`, `redirect`) in component tests; never mock React itself
- `tsc --noEmit` over the whole project — `next build` type-checks only what it bundles

## Data, caching and mutations

- Fetch in server components with `await`, independent calls in parallel with `Promise.all`; pass data down as props — not `useEffect` + `fetch` in a client component
- Caching is decided per call, explicitly: `fetch(url, { next: { revalidate: 60, tags: ["orders"] } })` or `{ cache: "no-store" }`; database/ORM reads wrapped in `unstable_cache` / `"use cache"` with tags, or made dynamic with `connection()` / `cookies()`
- Mutations are server actions (`"use server"` at the top of a file in `actions/`): zod-validate the input, read the session inside the action (it is a public HTTP endpoint), then `revalidatePath` / `revalidateTag` or `redirect`; identity never comes from a hidden form field or an argument
- Actions return a result object (`{ ok: true } | { ok: false; errors }`) consumed with `useActionState`; `useFormStatus` for pending state; `useOptimistic` only when the spec asks for optimistic UI
- `redirect()` and `notFound()` throw — call them outside `try/catch`
- `loading.tsx` or `<Suspense>` around slow sections so the shell streams first; `error.tsx` is a client component that renders `reset`
- `generateMetadata` for dynamic titles/OG tags, static `export const metadata` otherwise; `generateStaticParams` for known dynamic routes

## Security

- Secrets (`DATABASE_URL`, API keys) only in server files; a client component gets a value as a prop after the server decided it is safe
- Never pass whole database records to `"use client"` components — props are serialised into the HTML; select the fields the UI shows
- Server actions: authorise per action, validate every argument (ids included), rate-limit the public ones — arguments are attacker-controlled even when the form is not
- Route handlers: check `Content-Type`, zod-validate the body, return `NextResponse.json` with an explicit status
- Cookies `httpOnly`, `secure`, `sameSite: "lax"`; CSP, `X-Frame-Options`, `Referrer-Policy` in `headers()`
- `dangerouslySetInnerHTML` only with sanitised HTML; no `unoptimized` image wildcards

## What to avoid

- `"use client"` on a page or layout "to make it work" — move the interactive part into a small child
- `useEffect` + `fetch` for initial data; `getServerSideProps` / `getStaticProps` in `app/`; `next/router` (use `next/navigation`)
- Importing the database, `fs` or secret env into a component without `import "server-only"`
- `NEXT_PUBLIC_` for anything secret; `process.env` read outside `env.ts`
- A mutation without `revalidatePath` / `revalidateTag` (stale pages) or `cache: "no-store"` everywhere (no caching at all)
- `try/catch` around `redirect()`; `params` used without `await`
- Heavy libraries in client components when the server could compute the result; `next/dynamic` with `ssr: false` to hide a hydration mismatch instead of fixing it
- Running e2e against `next dev` and calling the resulting flakiness a test problem
