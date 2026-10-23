# Quality checks (`## Checks`)

Every quality mechanism Telesma had used to depend on the model remembering it. Review mode had zero
recorded uses across projects in the telemetry, and "watch out for OWASP" in the guidelines works on
errors of ignorance, not on errors made by reflex while typing. Quality checks fire **on their own, at
git operations** Telesma performs anyway — nobody has to remember to run them.

**Off by default** (`Enabled: no`). This is the one mechanism in Telesma that deliberately **adds**
blocks, so it has its own switch, separate from the permission judge (which only ever removes prompts —
see [PERMISSION_JUDGE.md](PERMISSION_JUDGE.md)).

## How it works

A Claude Code `PreToolUse` hook recognises a trigger point inside any Bash command, compound ones
included:

| Point | Trigger | Typical checks |
|-------|---------|----------------|
| `commit` | `git commit` | secrets, weakenings, dependencies, tests, hygiene, sast, lint-types, intent |
| `phase` | `git tag telesma/phase-*` (internal phase-progress tag) | weakenings, dependency-audit, dead-entry, sast, lint-types (with typechecker), intent, red-team |
| `release` | `git tag … vX.Y.Z` (a release version) | weakenings (every open weakening blocks), dependency-audit, dead-entry, red-team |
| `ci` | run by hand in the pipeline | everything configured for `ci` |

A finding with severity `block` stops the operation (`deny`), and Claude sees the list: check,
`file:line`, message, fingerprint. Warnings come back as context after the operation went through,
without blocking. Every run is logged to `telesma/state/CHECKS.jsonl` (point, check, rule, file, line,
fingerprint, decision — never secret content); the log is listed in `.git/info/exclude`, so it never
dirties the tree.

Section 19 of the instructions tells Claude how to react: fix the cause and retry the same operation;
a false positive → `TELESMA BLOCKED` with the fingerprint, never a workaround. One handling rule covers
every check, so adding a check adds no lines to the prompt.

### Configuration

The setup wizard (`telesma.sh --setup`) manages the `### <check>` blocks as tiers: **basic**
(secrets, weakenings, tests, hygiene — no network, no external tools, no map), **standard** (+
dependencies, dependency-audit, sast, lint-types, dead-entry) and **security** (+ intent, red-team,
for applications with HTTP routes). The recommended profile starts at basic; a tier is nothing more
than which blocks exist in the section, so it can be edited by hand as well.

```markdown
## Checks

- **Enabled**: yes
- **PR status**: yes

### secrets
- **When**: commit, ci
- **Scope**: changed
- **On failure**: block
```

Each `### <name>` subsection turns a module on; a check without a subsection does not run and costs
nothing. Fields: `When` (`commit`, `phase`, `release`, `ci`), `Scope` (`changed` | `all`), `On failure`
(`block` | `warn`), optional `Time limit` (`30 s`, `5 min`). **Severity is per rule and set by the
module**; the config can only soften it, never harden it. That is why `password = "…"` only warns
although `secrets` has `On failure: block` — the AWS key rule in the same module blocks.

### The command-shape rule

The hook sees files **before** the command runs. The first live test proved why that matters: it let a
planted AWS key straight through with
`printf 'AWS_KEY=…' >> config.py && git add config.py && git commit` — the check read `config.py`
before `printf` had written to it.

So before `git commit` or a phase/release tag, the same command may contain only
`git add` / `rm` / `mv` / `status` / `diff`, `cd`, and read-only commands without redirection (`grep`,
`ls`, `cat`, `head`, `find` without `-exec` / `-delete`). Anything else — a file write, `sed -i`, a
lockfile regeneration, a preceding commit before a tag — is denied with an instruction to split the
command. So are wrappers like `bash -c "git commit …"` and git aliases that are shell scripts; ordinary
aliases (`ci = commit`) are expanded and recognised.

What counts as "the commit": at hook time `git add a b && git commit` has not staged anything yet, so the
commit plan is the index plus the paths from the `git add` members of the same command (`-A` / `.` =
everything changed, `commit -a` = tracked changes). Without this the check would scan an empty index and
pass every commit Telesma makes.

### Fail-open is explicit

A hook that times out lets the operation through (Claude Code semantics), so the runner keeps its own
budget (20 s per check at `commit`, 120 s for the whole commit run, up to 570 s of the 600 s hook limit at
the other points). A check that did not run — tool missing, time limit, error — is reported to Claude as
"the operation passed **without** it", and Claude tells you at the next report. An unreachable registry
or vulnerability database is a warning, never a block: offline work does not stop.

Framework files in the project (`telesma/checks/`, `.claude/`) are not checked — they are not project code.

### CI usage

The modules are committed with the project, so the pipeline runs exactly the same code:

```bash
python3 telesma/checks/telesma-checks.py --point ci --since origin/main
```

Exit code 1 when something blocks. `--since` sets the reference point (`TELESMA_SINCE` for the modules)
for "what is new". It takes seconds and needs no secrets. Running it by hand at `--point phase` on a
project that had no checks before is a good way to calibrate exceptions before they reach commits.

## The checks

| Check | Points | Blocks | Warns |
|-------|--------|--------|-------|
| `secrets` | commit, ci | keys in known formats: `private-key`, `aws-access-key`, `github-token`, `gitlab-token`, `slack-token`, `anthropic-key`, `openai-key`, `google-api-key`, `stripe-live-key`; `secret-file` (`.env`, `*.pem`, `id_rsa`…); every `gitleaks:<rule>` when gitleaks is in PATH | `jwt`, `secret-assignment` (`password = "…"` in code) |
| `weakenings` | commit, phase, release, ci | `incomplete-marker` (marker without id or reason), `mutant` (`MUTANT` in code); at `release`: every `open-weakening` | at `phase`: `open-weakening`; patterns without a marker: `tls-disabled`, `debug-enabled`, `csrf-disabled`, `security-bypass`, `bypass-token`, `cors-any-origin`, `secret-in-response` |
| `dependencies` | commit, ci | a **new** package that is `not-found` in the registry (a name invented by the model), `fresh-package` (< 7 days), or `similar-to-popular` and young or rarely downloaded (typosquatting) | `similar-to-popular`, `young-package` (< 30 days), `few-downloads`, `deprecated`, `install-scripts`, `outside-registry` (git/URL), `extra-index` (dependency confusion), `other-registry`, `not-checked` (registry unreachable) |
| `dependency-audit` | phase, release, ci | `vulnerability`: critical/high from OSV, with a fixed version **newer than the installed one**, in a production dependency | the rest; `unreadable-lockfile`; `not-checked` (OSV unreachable) |
| `tests` | commit, ci | `only` (`.only`, `fit`, `fdescribe`), `skip-without-reason`, `test-deleted` while the tested module still exists | `skip-with-reason`, `test-without-assertion`, `code-without-test`, `test-pinned-to-code` (test and code it checks changed together), `fewer-assertions` |
| `hygiene` | commit, ci | `build-dir` (`node_modules/`, `dist/`, `__pycache__/`…), `file-too-large` (> 5 MB), `lockfile-stale` (manifest dependencies changed without the lockfile) | `floating-version`, `binary-file`, `minified-bundle`, `ide-file`, `visual-artifacts`, `missing-gitignore` |
| `dead-entry` | phase, release, ci | — never | `symbol-without-entry`, `route-without-client`, `component-without-parent`, `dead-symbol-tool` — something **new since the last phase tag** that nothing outside its own test refers to; the mechanical guard of `AC: entry` |
| `sast` | commit, phase, ci | `sql-concatenation`, `shell-command`, `eval-exec`, `deserialization`, `path-traversal` | `xss-innerhtml`, `cors-any-origin-with-credentials`, `weak-hash`, `non-crypto-randomness`, `open-redirect`, `stacktrace-in-response`, `jwt-without-verification`, `xxe`, `ssrf`, `insecure-tmp`, `secret-in-log`, `not-checked`. With `semgrep` in PATH also the OWASP packs |
| `lint-types` | commit, phase, ci | `typographic-quote` (a typographic quote used as a string delimiter), linter errors (`linter/<code>`) on changed files, typechecker errors (`types/<code>`) at phase/ci | `linter/format`, linter warnings, `linter-unknown`, `*-unavailable`, `*-failed`, `*-timeout`, `*-more` |
| `intent` | commit, phase, ci | `route-outside-map` (a new HTTP route without a map row), `guard-mismatch` (a route whose definition lacks its role's guard) | `new-public-route`, `role-undecided`, `role-unknown`, `role-without-guard`, `route-gone`, `host-outside-map`, `secret-outside-map`, `db-privilege` (`GRANT`, `SECURITY DEFINER`, `BYPASSRLS`…), `encoded-blob`, `map-missing` |
| `red-team` | phase, release, ci | `red-team-missing`: a protected route changed in the phase without a red-team test for each required case | the same in the first phase after the map appears; `red-team-undecided` (routes with role `?`) |

Each module's `telesma/checks/<name>/CHECK.md` has the full rule table, what it skips and why. Some notes
that matter in practice:

- **`secrets`** never prints a secret: the log and the message carry rule, file, line and a hash. With
  `gitleaks` it uses `--redact`; without it, a dozen built-in rules. The startup validator says which mode
  is active.
- **`dependencies`** checks only packages that **appeared** in a manifest (`package.json`,
  `requirements*.txt`, `pyproject.toml`, `deno.json`) compared with HEAD; scopes that `.npmrc` points
  to a private registry are skipped. Names go to the public registries, just as they would on install.
- **`dependency-audit`** always reads every tracked lockfile — a vulnerability appears in the database
  without any change in the project. It blocks only what a version bump fixes; a vulnerability without a
  fix is a decision for a human. One finding per package; the fingerprint covers the vulnerability list,
  so a waiver does not hide the next CVE in the same package.
- **`lint-types`** takes its commands from `## Tests` (`Linter/formatter`, `Typecheck command`). The hook
  never changes files: `--fix` / `--write` are stripped, formatters get `--check`. The typechecker runs
  only at phase/ci — `tsc` and `mypy` cannot sensibly check "only these files".
- **`dead-entry`** never blocks: its precision is still being measured.
- **`sast`** fingerprints an aggregated finding from **all** hit lines of the rule in the file, so an
  exception for line 12 does not silence a new injection on line 80.

Network-based checks cache in `~/.cache/telesma/`.

## Exceptions belong to the human (`telesma/state/CHECK_EXCEPTIONS.md`)

A false positive is waived by its fingerprint, one line per finding:

```markdown
- `3f2a9c1e0b7d` secrets tests/fixtures/vendor_example.py — test key from the vendor's docs (Alex, 2026-10-07)
```

Every write by Claude to this file, to `telesma/checks/`, or to the `## Checks` section of the config —
through Edit/Write or a Bash command with a write pattern — **asks you**. The author of the code does
not close the findings that block it; Claude reports a false positive as `TELESMA BLOCKED` instead.

## Weakening markers

A weakening is a deliberate hole: a safeguard switched off or a workaround added "for a moment" — TLS
verification off, debug mode, a login bypass for manual testing, a code shown under the login form
"to be removed before deployment". Sometimes it is needed; it must never reach a release unnoticed.

```python
# telesma: weakening totp-preview — TOTP code under the login form for manual testing; remove before deployment
```

The marker goes on the same line or the line above, and the marker **is** the register: the list of open
weakenings is `grep -rn "telesma: weakening"`. A marker without an id or reason blocks a commit; an open
weakening warns at phase end and **blocks the release tag**. A weakening is removed together with its
marker. Typical weakening patterns found without a marker warn (test files excluded). `MUTANT` left in
code — the leftover of an abandoned mutation test — always blocks.

## Attack-surface map (`telesma/state/SECURITY_MAP.md`)

The other checks read a line of code: they catch an injection typed in a hurry, they do not catch a
**missing** check. Missing authorization (OWASP A01) was the costliest defect class observed, every
time under green tests ("doctor A1 admitted a patient from doctor A2's queue"; "the signing screen
opened for anyone who knew the session URL").

`telesma/state/SECURITY_MAP.md` declares intent:

- `## Roles` — every role from the spec with the **guard text in code** that stands for it
  (`member` → `Depends(get_project_membership)`, `doctor` → `requireRole("doctor")`); `anonymous` is
  built in; `(global)` = enforced outside the route (app-wide middleware, a proxy's `forward_auth`).
- `## Ownership boundaries` — who may see whose resource, and what a violation returns.
- `## Routes` — every route with its roles (`a + b` = both, `a, b` = either, `?` = undecided) and its
  ownership.
- `## Outbound` — `host`, `env` (secrets from the environment) and `db` (privilege statements) rows.
- `Session: cookie | header | bearer` — decides whether write routes need a CSRF case.

The checks never learn your authentication framework. For each route they extract a **window** —
decorators and signature plus the router's `dependencies=` (Python), call arguments before the handler
plus `x.use(prefix, …)` (JS), class and method decorators (Nest) — and test whether the map's guard
text appears in it. Sub-apps mounted in another file (`app.route("/doctor", …)`) get the prefix and
guards from the mount site. Recognised: FastAPI, Flask, Starlette-like, Express, Hono, Fastify,
Koa-router, Nest; other frameworks (Django URLconf, Rails, Spring) — the checks stay silent.

**Where the map comes from.** On a new project, clarification writes the roles and ownership boundaries
from the spec; routes are added during implementation, because a new route without a row blocks the
commit. On an existing project the launcher writes a skeleton from the code when the map is missing and
`### intent` is configured: all routes, guard candidates, `?` where nothing was recognised.
`python3 telesma/checks/intent/run.py --skeleton` does the same by hand (`--stdout` to print instead).

**Who approves it.** Telesma writes the map — the row in the same commit as the route — without asking
you on every route. You review it where you decide anyway: the release proposal has an "attack surface"
line (route rows added/removed, public ones, role or ownership changes since the last version), and the
map's diff is in the PR.

## Red-team markers

At phase end, every protected route whose definition or body changed in the phase needs a test that
attacks it and expects a refusal, marked in the test file:

```python
# telesma: red-team PATCH /projects/{project_id} — no-session, foreign-role, foreign-owner, csrf
```

The required cases follow from the map: `no-session` always; `foreign-role` when the map has roles the
route does not admit; `foreign-owner` when the route's ownership is not `—`; `csrf` for write methods
unless `Session: header`. A test that iterates over a module's route list uses a wildcard marker:
`telesma: red-team * /registrar/* — csrf`.

The blocking finding **is** the task text (route, missing cases, the marker line to write), so Telesma
creates the red-team task in the current phase without any extra instruction. The first phase after the
map appears only warns — nobody has reviewed the skeleton's roles yet. The cost is one-time per route:
markers stay in the tests.

What it does **not** check: that the test really attacks and would fail without the guard — the marker is
a declaration. That is what the mutation check in `telesma/guidelines/general.md` is for (remove the guard,
the test must turn red).

## PR status — an attestation, not verification

With the GitHub integration and `PR status: yes`, a `PostToolUse` hook records evidence for every commit
the hook checked, and after a push to a task branch posts one commit status, **`Telesma: checks (local)`**,
on the branch tip: which checks ran, on how many commits, when, and the date of the last dependency
audit. It is red when any commit has no evidence (made outside the hook) or a check did not run — absence
is not green. The wizard adds the name to `Required checks`, so the judge will not merge a PR without
evidence. Details: [INTEGRATIONS.md](INTEGRATIONS.md#pr-status-telesma-checks-local).

The honest limit is in the name: it is an attestation from the developer's machine. Anyone with push
rights can post the same status. The verifiable variant is the same runner in CI (`--point ci`).

## Adding a check module

A check is a directory `telesma/checks/<name>/` (in the Telesma repo: `templates/checks/<name>/`, delivered
to projects at startup; your local edits win) with two files.

**`CHECK.md`** — frontmatter plus the human description (rule table, what it skips):

```markdown
---
kind: command          # command | rule | agent (agent cannot run at commit — the validator refuses it)
run: python3 run.py    # how to run the check
check: python3 run.py --check   # optional readiness probe for the startup validator
when: commit, ci       # default points
scope: changed         # changed | all
on_failure: block      # block | warn — the strongest severity this module may report
---

# Check: <name>
…
```

**`run.py`** (or whatever `run` names) — the protocol:

- **Input:** file paths on stdin, one relative path per line (files over 1 MB, lockfiles and minified
  bundles are filtered out by the runner — a module that needs them reads git itself). Environment:
  `TELESMA_POINT` (`commit` | `phase` | `release` | `ci`), `TELESMA_ROOT` (project root), and `TELESMA_SINCE`
  when `--since` was given. The working directory is the module directory.
- **Output:** findings as JSON lines on stdout:
  `{"file": …, "line": …, "rule": …, "message": …, "severity": "block" | "warn", "content_fingerprint": …, "file_fingerprint": true}`.
  `severity`, `content_fingerprint` (what the fingerprint is computed from instead of the message — use
  it to survive line shifts) and `file_fingerprint: false` (the finding is about a thing, not a place)
  are optional.
- **Exit code:** `0` = checked (findings may exist), `3` = tool missing (reported as "did not run").
- **`--check`:** prints one line about readiness; a line starting with `warning:` becomes a startup
  validator warning.
- **Never print a secret's content** — only a fingerprint.

Then add a `### <name>` subsection to `## Checks` in the config. The fingerprint the runner computes
(check + rule + file + content) is what goes into `telesma/state/CHECK_EXCEPTIONS.md`.
