---
kind: command
run: python3 run.py
check: python3 run.py --check
when: commit, phase, ci
scope: changed
on_failure: block
---

# Check: lint-types

The project's linter and typechecker as a guard nobody has to remember. Telesma runs
the linter "when it remembers" (step 9 of the loop) — this check does it at every commit on changed
files, and the typechecker at phase end. Plus one built-in rule, independent of tools:
a typographic quote used as a string delimiter — a pitfall that on the reference
project came back nine times in five weeks despite a `📌` note.

## Where the commands come from

From `## Tests` in `telesma/config.md`:

- `Linter/formatter` — e.g. `ruff check`, `npx eslint .`, `cd backend && ruff check`.
  A placeholder `[e.g. …]`, `none` or empty = no linter.
- `Typecheck command` — e.g. `mypy src`, `pyright`, `npx tsc --noEmit`. `none` = no typechecker.

Without both fields only the quote rule runs (the validator at startup reports this as a `warning`).

## What it does at which point

| Point | Quote | Linter | Typechecker |
|---|---|---|---|
| commit | changed code files | changed files matching the tool's language (15 s limit) | **skipped** |
| phase, ci | as above | files in scope (240 s limit) | full run (240 s limit) |

The typechecker deliberately does not run at commit: `tsc` and `mypy` cannot sensibly do "only these
files", and on a large project they exceed the commit budget (20 s for the whole module).

**The hook never changes files.** Autofix flags are stripped from the command (`--fix`, `--fix-only`,
`--unsafe-fixes`, `--write`, `--apply`, `--apply-unsafe`, `--autocorrect`…, prettier `-w`, rubocop
`-a` / `-A` / `-x`), formatters (`black`, `isort`, `prettier`, `cargo fmt`, `ruff format`) get `--check`.

## The field is not a way to run a command

`config.md` is a file the agent edits and a clone brings along, and this module runs inside a hook —
outside the permission system. Two rules follow:

- **Only a known tool, called directly.** The program name must be exactly one of the tools below
  (`ruff`, `/opt/bin/ruff`, `node_modules/.bin/eslint`), optionally through `npx` / `pnpm exec` / `yarn` /
  `bunx` / `uv run` / `poetry run` / `pipenv run` / `pdm run` / `hatch run` / `python -m`, and after a
  `cd <directory inside the project> &&` prefix. `python3 tools/my_ruff.py`, `npm run lint`, a pipe, `;`,
  `&&`, a redirect, `$…` or a `cd` that leaves the project are **not run** at any point — one
  `linter-unknown` / `types-unknown` warning. No shell is ever started.
- **Only a confirmed `## Tests` section.** The launcher keeps a per-machine record of the section the
  person confirmed (`~/.config/telesma/trust/`). When the section differs — the agent just filled it in,
  a pull changed it — nothing is run and one `config-unconfirmed` warning says so; the next start of
  `telesma.sh` confirms it. Run by hand or in CI (`telesma-checks.py --point …`) the runner vouches for
  the section: whoever runs that runs the project's tools knowingly.

## Tools recognised by their program name

| Tool | Files | Output format |
|---|---|---|
| `ruff`, `flake8`, `pylint`, `black`, `isort` | `.py` | ruff `--output-format json`, pylint `--output-format=json`, flake8 text `file:line:col: CODE message` |
| `eslint`, `biome`, `prettier` | `.js .jsx .ts .tsx .mjs .cjs .vue .svelte` | eslint `-f json`, biome `--reporter=json` |
| `golangci-lint`, `go vet` | `.go` — **no list** (packages), only when `.go` changed | golangci `--out-format json` |
| `cargo clippy`, `cargo fmt` | `.rs` — no list, only when `.rs` changed | clippy `--message-format json` |
| `rubocop` | `.rb` | `--format json` |
| `shellcheck` | `.sh .bash` | `-f json` |
| `mypy`, `pyright`, `tsc` (types) | — | mypy text, pyright `--outputjson`, tsc `file(l,c): error TSxxxx` |

Also as typecheckers: `basedpyright`, `vue-tsc`, `svelte-check`, `go vet` / `go build`, `cargo check`,
`deno check`. An unknown tool or a compound command (pipe, `;`, `&&` other than a `cd X &&` prefix) is
not run — see above. The `cd X &&` prefix works: file paths are recomputed relative to `X`.

**Several commands in one field** — a project with a backend and a frontend writes each one separately, with its own
`cd`: `` `cd backend && ruff check app tests` · `cd frontend && npx eslint src` `` (commands
in backticks or separated by ` · ` / ` and ` / ` ; `). Each one gets only the files from its own
directory. Paths written into the command after the tool (`app tests`, `src`) are replaced at commit
by the list of changed files — otherwise the linter would check the whole directory and block the
commit for errors in files the commit does not touch. The same for `Typecheck command`.

When no file is left after the language filter (a commit of `.md` files only), the linter does not start — silence.

## Rules and severities

| Rule | Severity | What |
|---|---|---|
| `typographic-quote` | **block** | `„ ” “ ‚ ’ ‹ › « »` as a delimiter: `x = „text”`, `foo(“a”)`, `return „b”` or `"text”` (opened with ASCII, closed typographically) |
| `linter/<code>` | by code | ruff/flake8: `E9*`, `F*`, `B*`, syntax error → block; `E`, `W`, `I`, `D`, `N`, `UP`… → warn. eslint `severity: 2` / fatal, pylint `error`/`fatal`, biome `error`, shellcheck `error`, rubocop `error`/`fatal`, clippy `error` → block; the rest warn |
| `linter/format` | warn | a file to reformat (black / isort / prettier / cargo fmt) |
| `types/<code>` | **block** | mypy `error … [code]`, tsc `error TSxxxx`, pyright `error`; pyright `warning` warns, `note` skipped |
| `linter-unknown`, `types-unknown` | warn | not a known tool called directly — not run at any point |
| `config-unconfirmed` | warn | `## Tests` differs from the section confirmed on this machine — linter and typechecker not run until the next start |
| `linter-unavailable`, `types-unavailable` | warn | the command points at something that does not exist (code 127 / missing file) — the field is optional, so not code 3 |
| `linter-failed`, `types-failed` | warn | exit code ≠ 0, output not parseable — first 3 lines of output (≤ 300 characters) |
| `linter-timeout`, `types-timeout` | warn | limit exceeded — the operation passed without the tool |
| `linter-more`, `types-more` | warn | more than 100 tool findings — the rest summarised in one finding |

Style rules (`E501`, `W…`, `format`) do not block even when the tool itself
classifies them as an error — what blocks is a syntax error, an undefined name or a
type error. The fingerprint of a linter finding is the line content (survives line shifts); findings
"about the tool" (`linter-*`, `types-*`) have `file_fingerprint: false`.

## The quote rule — what passes

A simple per-line state scanner (in a string / outside / in a comment, with the block comment,
`"""` docstring and template literal carried across lines). A typographic quote
**inside** a valid string — `print("He said „yes”")`, `` `Quote „x”` `` — is
the most common case in projects with non-English UI text and gives no finding. Comments
(`#`, `//`, `/* */`, `--`), docstrings, `.md` / `.txt` files — skipped.

Deliberate concessions to avoid false alarms:

- **shell, YAML** — only the mixed variant (`"text”`) and the assignment `X=„…”`; outside a string
  a typographic quote is a legitimate character there (heredoc, values in translation files).
- **JSX/TSX, PHP** — no "closing" rule (`…”,`), because text stands outside strings there
  (`<p>He said „yes”, </p>`); `title=„x”` and `{„x”}` are still caught.
- The end of the line after a literal is not a signal — JSX and heredoc split text across lines.

What it skips: regex literals in JS, Rust raw strings with `#`, the lifetime `'a` (the rest of the line is treated as a
string — at worst it misses something, it does not report falsely).

## What it does not do

It does not configure the linter (no `eslint.config.js` / `[tool.ruff]` = the tool runs with its own
default rules or reports an error — then `linter-failed`). It does not run tests. It does not
check `.md` files. It does not scan the whole repo with scope `changed`.

False positive → an exception by fingerprint in `telesma/state/CHECK_EXCEPTIONS.md`, written by a human.
