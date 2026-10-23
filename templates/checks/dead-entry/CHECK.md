---
kind: command
run: python3 run.py
check: python3 run.py --check
when: phase, release, ci
scope: all
on_failure: warn
---

# Check: dead entry

The costliest defect class of the first retro: a mechanism **built, tested
and wired to nothing** — a toolbar rendered only in its own test, four screens with no entry
in the navigation, "the phase did not work end-to-end despite 37 green tests". The `AC: entry` rule
(section 0.3 of the instructions) makes Telesma name what triggers a new mechanism — this check is its
mechanical guard.

**What it catches.** A symbol **new since the reference point** that nothing outside tests refers to —
neither another code file nor a line of its own file other than the definition line. A call in its own module
is an entry: the first measurement on the Telesma repository without this rule gave 146 "dead" functions,
every one of them a helper called in its own file; with it — one true finding. Reference point: the last `telesma/phase-*` tag (at `phase`),
the last `vX.Y.Z` tag (at `release`), the `TELESMA_SINCE` variable (CI: `TELESMA_SINCE=origin/main`), and without
a tag — the first commit of the repository. New definitions = lines added in `git diff <since>...HEAD`.
Existing dead code is deliberately skipped: a full list at every phase would be noise.

| Rule | What | Severity |
|---|---|---|
| `symbol-without-entry` | a new function / class / export with no reference in another code file | warn |
| `route-without-client` | a new HTTP route (`@app.get`, `router.post`, `@Get()`) whose path no front-end / client / API documentation file calls | warn |
| `component-without-parent` | a new React component (`export function Name` in `.tsx`/`.jsx`) rendered in no other file | warn |
| `dead-symbol-tool` | a symbol new in the diff that `vulture` / `knip` / `ts-prune` reports as unused, while our grep found its name elsewhere (e.g. in a string) | warn |

**It never blocks.** Dead code does not break anything, and the precision of this check has not been
measured yet — telemetry (the share of warnings closed by an exception vs by a fix) will tell whether it works.
Above 30 findings the rest goes out as one counter finding.

**Languages and definitions.** Python: `def` / `async def` / `class` at module level (no indentation;
methods skipped). JS/TS: `export function|const|let|class`, `export default function`,
`export { … }` (without `from` — a re-export is not a definition). Go: a capitalised `func` (exported),
no methods. Other languages — zero findings.

**HTTP routes** are checked **only when the repo has a front end**: any `.tsx/.jsx/.vue/.svelte/.html` file,
`openapi*`/`swagger*`, or a `.ts/.js` in a `frontend/ client/ web/ ui/ static/ public/` directory. A backend
alone means the client lives in another repository — routes are not judged. A reference to a route =
its path (prefix `/api`, `/api/vN` optional; parameters `:id`, `{id}`, `<id>`, `[id]`
match any segment) in a front-end / client / `.md` / `.yaml` / `.json` file outside the
definition and tests. The prefix `APIRouter(prefix=…)`, `Blueprint(url_prefix=…)`, `@Controller(…)` is
added when it stands in the same file; a route whose path normalises to `/` is not judged.

**What it does not do / what it skips (entry points registered by convention).**
- Python: names starting with `_`, `main`, `test_*`, `Test*` classes (unittest discovers them by name), names in `__all__`, files in `migrations/`, `alembic/`,
  `commands/`, `management/`, `manage.py`, `wsgi.py`, `asgi.py`, `conftest.py`, `setup.py`, `settings.py`,
  `urls.py`, `admin.py`, `apps.py`, `signals.py`; `tasks.py`/`celery.py` with `@shared_task`/`celery`;
  `cli.py` with `@click`/`@app.command`/typer; functions under registering decorators (`@shared_task`,
  `@click.*`, `@receiver`, `@pytest.fixture`, `@app.on_event`, `@app.exception_handler`, `@validator`…);
  a symbol passed in the same file to `register(`/`setup(`/`add_command(`/`include_router(`.
- JS/TS: `index.*` and `main.*` (re-exports, bootstrap), `*.d.ts`, `*.config.*`, `*.stories.*`,
  `pages/`, `app/`, `routes/` **only** in projects with file-based routing (Next, SvelteKit, Remix, Nuxt,
  Astro, TanStack/React Router — by config file or a dependency in `package.json`); a `use*` hook
  is an ordinary symbol (not skipped).
- Go: `main`, `init`, `Test*`, `Benchmark*`, `Example*`, `Fuzz*`, methods.
- Test files (`tests/`, `test_*`, `*.test.*`, `*.spec.*`, `_test.*`) provide neither definitions
  nor references; `*.stories.*` likewise. Directories `node_modules/`, `vendor/`, `dist/`, `build/`, `.venv/`,
  files > 1 MB, lockfiles, minified and binary files — outside the corpus.
- **Simplification:** comments are not stripped — a name mentioned in a comment of another file counts
  as a reference (the check prefers staying silent to raising a false alarm). It does not follow data flow: `getattr`,
  string registries (`"module:function"` in configuration) are a reference, because the name appears as a word.
  A route called without a leading `/` (`api.get('items')`) or assembled from pieces is not seen.

**Tools (an extra signal, nothing is installed).** `vulture` from PATH on new Python
files (`--min-confidence 80`); `knip` / `ts-prune` through `npx --no-install` only when they are
in the project's `devDependencies`. A tool result about a symbol new in the diff: a confirmation
in the finding's message or a separate `dead-symbol-tool` finding. 60 s limit per tool;
timeout = tool skipped. No tools is the normal mode (built-in, no validator note);
`--check` warns only when the project declares a tool that is not at hand.

False positive (a dynamically loaded plugin, a library's public API) → an exception by fingerprint
in `telesma/state/CHECK_EXCEPTIONS.md` (fingerprint = definition file + name, survives line shifts) —
written by a human.
