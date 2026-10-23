---
tag: htmx
keywords: htmx, ssr, hypermedia, server rendering, forms, html fragment, hx-get, hx-post, hx-target, hx-swap, templates, progressive enhancement
---

# Guidelines: SSR + HTMX

## When HTMX, when React

- HTMX: the screen is primarily data presentation and forms (lists, CRUD, panels)
- React: an interface with rich client-side state and interaction
- Targeted vanilla JS: small local interactivity
- Decide per screen — there is no requirement for a single rendering model across the whole application

## Working model

- The server renders HTML with the stack's templating (`hono/jsx`, Jinja, templ, ERB…); HTMX swaps page fragments
- An HTMX endpoint returns an HTML FRAGMENT when `HX-Request: true`, the full page otherwise — one route, two renderings; never a JSON API for HTMX
- `hx-get`/`hx-post` + `hx-target` + `hx-swap` — the swap target stated explicitly; `hx-indicator` for anything slower than ~300 ms
- `hx-boost` on navigation links only when the page has no scripts that depend on a full reload
- Partials in files of their own (`partials/booking_row.html`) reused by the full page and the fragment endpoint — never two copies of the same markup
- State lives on the server/in the database — do not build a state model in the browser
- Events between fragments: an `HX-Trigger` header from the server instead of hand-written JS

## Forms

- A form also works without JS where that is cheap (plain POST + redirect) — HTMX as progressive enhancement
- Validation errors: the server returns the form fragment with messages (status 422), HTMX swaps it in place
- After a mutation: the response contains the updated fragment or `HX-Redirect`

## Security

- Code in the browser is NEVER the authorisation boundary — every HTMX endpoint authorises like any other endpoint (auth middleware + roles/RLS in the database)
- CSRF: a token in mutating forms (`hx-headers` or a hidden field) + `SameSite` cookies; the `HX-Request` header alone is NOT protection
- Escape content in templates by default; raw HTML only when trusted and sanitised; never put user content into `hx-*` attribute values unescaped
- CSP without `unsafe-eval`: load htmx from your own static files, not an inline script; `hx-on:` attributes need `unsafe-inline` or a nonce — prefer `HX-Trigger` events

## Tests

- Endpoint tests assert on the HTML (parse it, query by role/text — not string equality on the whole fragment) for both the fragment and the full-page rendering
- One browser e2e test per critical flow with JS enabled; one request-level test proving the no-JS fallback (plain POST → redirect)

## What to avoid

- Building an SPA in HTMX — a lot of client-side state is a sign that the screen belongs to React
- Endpoints returning JSON that JS assembles into HTML — the server assembles the HTML
- Duplicating on the client data/state that the server already has
- Hiding UI elements as "access control"
