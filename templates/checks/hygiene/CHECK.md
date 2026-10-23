---
kind: rule
run: python3 run.py
when: commit, ci
scope: changed
on_failure: block
---

# Check: hygiene

Things that should not end up in the repository — the model's most common mechanical slip
at commit time: `dist/`, `coverage/`, `.pyc`, a 40 MB database dump, a `package.json`
with a new dependency and no rebuilt `package-lock.json`. Until now only `Ignore on commit`
in the config guarded this, and it works only when someone filled it in. This check
always runs — and suggests what to add to `.gitignore`.

## What blocks and what warns

| Rule | Severity | What it catches |
|---|---|---|
| `build-dir` | block | a file under `node_modules/`, `dist/`, `build/`, `out/`, `.venv/`, `venv/`, `__pycache__/`, `coverage/`, `htmlcov/`, `.next/`, `.nuxt/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `target/` (only next to `Cargo.toml` / `pom.xml` / `build.gradle`), `*.pyc`, `*.pyo`, `.DS_Store`. One finding per directory (first file + counter); fingerprint = directory name, so one exception covers the whole directory |
| `file-too-large` | block | a file > 5 MB (threshold: environment variable `TELESMA_HYGIENE_MAX_MB`). An artifact from `telesma/artifacts/` with `Commit artifacts: yes` does not block — above 50 MB it reminds about Git LFS (section 0.5) |
| `lockfile-stale` | block | a manifest with a **changed dependency section** in the commit, while the lockfile is tracked in the repo and untouched: `package.json` ↔ `package-lock.json` / `pnpm-lock.yaml` / `yarn.lock` / `bun.lockb`, `pyproject.toml` ↔ `poetry.lock` / `uv.lock` / `pdm.lock`, `Cargo.toml` ↔ `Cargo.lock`, `go.mod` ↔ `go.sum`, `Gemfile` ↔ `Gemfile.lock`, `composer.json` ↔ `composer.lock`, `deno.json` ↔ `deno.lock` (lockfile in the same directory). A change of only the project version or scripts passes; a repo without a lockfile = the project does not use one, silence |
| `floating-version` | warn | a **production** dependency without an upper bound: `*`, `latest`, `x`, empty, `>=X` without `<`, `git+…` without `#ref` (`package.json` → only `dependencies`; `requirements*.txt` → a line without `==` / `~=` / `<` / `===`; `pyproject.toml` → `[project] dependencies` and `[tool.poetry.dependencies]`; `Cargo.toml` → `[dependencies]`). Once per file, up to 5 names in the message |
| `binary-file` | warn | a `\0` byte in the first 8 KB of a file under `src/`, `app/`, `lib/`, `backend/`, `frontend/`, `pkg/`, `cmd/` — except images (`.png .jpg .gif .webp .ico .svg`), fonts (`.woff .woff2 .ttf .otf`), `.pdf` in `docs/`, `.wasm`, `bun.lockb` and test files (fixtures) |
| `minified-bundle` | warn | `.js` / `.css` with a line > 5000 characters or named `*.min.*` — except `vendor/` (also `static/vendor/`, `public/vendor/`) |
| `ide-file` | warn | `.idea/` (one finding per directory), `.vscode/` except `extensions.json` / `launch.json` / `tasks.json` / `settings.json` — and those four when they contain an absolute path from one machine (`/Users/`, `/home/`, `C:\`); `*.swp`, `*.swo`, `*~`, `Thumbs.db` |
| `visual-artifacts` | warn | a file under `telesma/artifacts/` (field `Artifacts dir`) while `## Visual artifacts` → `Commit artifacts` ≠ `yes`. No config or no section = silence |
| `missing-gitignore` | warn | a repo without a `.gitignore` in the root, and the first code file is going into the commit. Once; fingerprint without a file |

## Where the file list comes from

The runner passes the files in scope on stdin, but **without** files > 1 MB, lockfiles and `*.min.*` —
and with `git add x && git commit`, at hook time `x` is not in the index yet. So the
check adds the index (`git diff --cached`) and changes against HEAD to stdin (at `ci`:
the diff from the branch base — `TELESMA_SINCE`, merge-base with `origin/HEAD` / `main`, as a last resort
`HEAD~1`). A lockfile counts as "in the commit" when it has any change against HEAD —
that is the only trace of `git add package.json package-lock.json && git commit`, because the runner
cut the lockfile from stdin.

## What it does not do

- It does not see a file > 5 MB or a `*.min.js` that is **untracked and added only
  in the commit command** (`git add big.sql && git commit`) — it is not in the index, and the runner
  filtered it out of stdin. A file already in the index (a separate `git add`) or `git add .` is visible.
- At `commit` it also checks tracked files that are changed but not staged (it does not tell
  `commit -a` from a plain one) — a database dump lying in the working tree will block a commit of something
  else; that is a signal for `.gitignore` anyway.
- It does not read the lockfile — it only compares the *set of dependency entries* of the manifest before and after.
  A lockfile changed by hand in the wrong place passes.
- It does not judge floating versions in development dependencies, `optional-dependencies`
  or in `go.mod` (always pinned).
- It does not check git history — only the files in the scope of the point.

False positive (a `build/` directory with sources, a binary test file outside `tests/`, a lockfile
rebuilt only in CI) → an exception by fingerprint in `telesma/state/CHECK_EXCEPTIONS.md`, written by
a human. The fingerprint of `build-dir`, `ide-file` (`.idea/`) and `visual-artifacts` does not
contain the file — one exception covers the directory.
