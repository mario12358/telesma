---
tag: general
keywords: clean code, naming, comments, testing, git, refactoring, errors, shell, commands
---

# General guidelines (always loaded)

## Clean code

- Descriptive, intention-revealing names — avoid abbreviations (`userById`, not `ubi`)
- Functions do one thing and stay short (≤ 20 lines); nesting deeper than 3 levels — extract into a function; prefer early return over else
- No typographic quotes (`“…”`, `„…“`, `‘…’`) in string literals or test names — a mismatched closing `"` terminates the string with an error that points elsewhere. Quote inside code with apostrophes or `«…»`

## Comments

- By default, write no comments — the code should document itself
- Comment ONLY the "why" when it is not obvious, never "what the code does"
- Delete dead code instead of commenting it out (git remembers)

## Tests

- Test every new feature: happy path + at least one edge case
- A test of a new service called directly does not prove that anything calls it — for every new mechanism, one test through its entry point (endpoint, handler, screen, worker)
- Test data in production shape, not the simplest one: if an entity occurs in groups/batches/multiple versions in practice, a test on a single item skips the whole branch
- Isolate external dependencies (database, API, time) — mock or fixture
- Fix a failing test by changing the code, not the test — weaken an assertion or skip only when the test is wrong with respect to the requirements (with a justification and an entry in the problem log)
- "0 tests executed" is a configuration error, not a success — even with exit code 0
- Verify a test of a RULE (validation, permission, limit, threshold, barrier) by mutation before you consider it done: disable the rule in production code and run the test — it must fail. Green under mutation = the test guards nothing (most often: the test data never enters the branch, the assertion counts elements instead of pointing at a specific one, the scenario does not tell two rules apart)
- Mutation procedure, no exceptions: (1) mutate ONE line and mark it with a `MUTANT` comment on a separate line ABOVE the change, not inside the expression under test; (2) revert with the reverse edit, NEVER `git checkout`/`git restore` — on a file with uncommitted work that is deletion, not reverting; (3) a test run under mutation must not write to repository files — send its output to a temporary directory; (4) after reverting, run the test once more — green is the proof that the mutant is gone

## Errors

- Never swallow exceptions silently (no empty catch)
- Validate at the boundaries (user input, external APIs) — not inside trusted code
- Do not add try/catch "just in case"

## Git

- Specific `git add <file>`, never `git add -A` / `git add .`
- One commit = one logical change
- Message in the imperative mood ("add X", not "added X")
- Do not commit secrets (.env, API keys, credentials)

## Shell commands

Claude Code matches every command against the permission rules; a construct it cannot
analyse unambiguously is covered by no `allow` rule and always asks the user. Seven
patterns break this most often; each has an equivalent form that goes through without asking:

| Instead of | Write | Why |
|---|---|---|
| `SP=/tmp/x` … `cp $SP/a.bak .` | the path itself: `cp /tmp/x/a.bak .` | variable expansion hides the real target from the analysis |
| `cd frontend && git add src/a.ts` | `git -C frontend add src/a.ts` | `cd` before `git` can fire hooks from another directory |
| `cd A && … && cd B && …` | separate Bash calls | changing directory more than once always needs approval |
| `cd ../backend && cp a b` | full paths without `cd` | with `cd` plus a write the analyser cannot tell what the paths refer to |
| `for l in pl en de; do … done` | the loop **inside** a script (`python3 - <<PY`) or separate calls | the analyser does not parse shell loops; you also lose the result of each single pass |
| `cat >> file <<'EOF' … EOF` | the Edit/Write tool | the same change, visible as a diff, with no shell quoting |
| `python3 <<PY … p.write_text(s) … PY` | the Edit/Write tool | use a script for reading and analysis; write with the tool — safer and with a diff |

General rule: a command should be **one readable invocation with explicit arguments**.
Write code (Python, JS) to a file with the Edit/Write tool and run the file, instead of pasting
it into the shell via a heredoc or `-c`.

## Refactoring

- Three similar lines < a premature abstraction
- Do not refactor while fixing a bug (separate task)
- YAGNI — no compatibility flags, fallbacks or abstractions for scenarios that will not happen
