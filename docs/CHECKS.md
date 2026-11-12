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

Since state format 21 the agent does not commit or tag: `telesma-task.py done` / `commit` run the
`commit` point on exactly the files they commit, `suite` the `phase` point before the phase tag, and
`release` the `release` point. The hook still recognises these operations wherever they come from.

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
command. So are wrappers like `bash -c "git commit …"` and git aliases that are shell scripts or are
defined in the command (`git -c alias.z=commit z`); ordinary aliases (`ci = commit`) are expanded and
recognised. Denied for the same reason:

- `$(…)`, backticks and `<(…)` anywhere in a command that commits or tags — they run before the commit,
  after the check has read the files. The one inert form is allowed: a message read from a heredoc with
  a **quoted** delimiter, `git commit -m "$(cat <<'EOF' … EOF)"`;
- `--output` on a `git diff` / `log` / `show` standing before the commit (it writes a file);
- a git operation that creates commits (`commit`, `tag`, `merge`, `cherry-pick`, `rebase`, `revert`, `am`,
  `pull`) standing where the hook cannot read it: a subshell `( … )`, a brace group, after `!`, with a
  variable in place of `git`, inside an interpreter one-liner.

What counts as "the commit": at hook time `git add a b && git commit` has not staged anything yet, so the
commit plan is the index plus the paths from the `git add` members of the same command. The plan is exact
only for plain paths that exist. **Whenever it cannot be read exactly, the scope widens to everything
modified plus everything untracked** — never narrows: `git add -u` / `-A` / `.`, a glob, pathspec magic,
a path that does not exist at hook time, a `cd` or `git -C` in the command, `git commit -a`, a pathspec
on the commit (`git commit -m x file.py`), and a command that does not parse. `git add -f` together with
anything but existing paths is denied (ignored files cannot be listed that way).

The checks read the **working tree**. A path that is staged in one version while the working tree holds
another — and that the command does not stage again — would be checked in a version that is not the one
committed, so such a commit is denied until the path is staged or restored. File lists come from git
NUL-separated and unquoted, so a non-ASCII name or one with a quote or a space is a path like any other;
a name with a control character, a line break or bytes that are not UTF-8 blocks (`runner/unsafe-path`).

### What the hook could not see, it checks afterwards

A commit made by a script, by `make`, by another tool, a merge, a cherry-pick — or an amend, which carries
the whole earlier commit — cannot be checked before it exists. After every Bash command a `PostToolUse`
hook looks whether `HEAD` moved to commits that have no evidence and runs the commit-point checks on
their **content** (a temporary worktree at the commit, read from git objects, not from your working
tree). Blocking findings come back to Claude as a blocking message naming the commit, and the commit's
evidence says so — the PR status is red until the commit is fixed and amended (the amended commit is
checked again as a whole). Evidence from the pre-commit run is given only to a commit that holds exactly
the blobs the checks read. A merge is checked for what differs from every parent.

### What fails closed and what does not

A hook that times out lets the operation through (Claude Code semantics), so the runner keeps its own
budget (20 s per check at `commit`, 120 s for the whole commit run, up to 570 s of the 600 s hook limit at
the other points). A check that did not run because its **tool is missing** or its **time limit** ran out
is reported to Claude as "the operation passed **without** it", and Claude tells you at the next report.
An unreachable registry or vulnerability database is a warning, never a block: offline work does not stop.

Everything else stops a commit or a tag:

- an **internal error of the hook** (an exception, git not answering when the scope is computed) — the
  operation is denied with a plain-ASCII message instead of passing unchecked; an undecodable byte in
  `telesma/config.md` no longer switches the checks off;
- a **check module that broke** (an exit code other than 0 and 3) — a blocking finding `check-crashed`
  with a fingerprint, so you can let it through with an exception and the author of the commit cannot;
- a **difference in the check files** (below).

The check modules themselves (`telesma/checks/`) are not scanned; `.claude/`, lockfiles, minified bundles
and files over 1 MB are skipped by every check **except `secrets`**, which reads everything in scope.

### Integrity of the check files

A Bash command can write to a file in ways no reading of the command reveals (`python3 -c …`, a `cd`
first, `git checkout <old> -- telesma/checks`). So besides asking on recognisable writes, the runner
keeps hashes of every file in `telesma/checks/`, of `telesma/state/CHECK_EXCEPTIONS.md` and of the
`## Checks` section in `.git/telesma-checks/baseline.json` (this machine's data, never committed).
A difference **stops the next commit or tag** with the list of what differs, and Claude reports
`TELESMA BLOCKED`. The baseline moves in three ways only:

- the launcher at start: it creates the baseline when there is none and records module files identical to
  the delivered templates (`telesma-checks.py --baseline <project> --templates <dir>`; with
  `--config-section` right after its own wizard wrote `## Checks`). In a repository
  that has no commit yet (created during the session) the hook creates it at the first commit;
- an Edit/Write Claude made after the hook asked you and you agreed — exactly the announced content;
- you, in a terminal: `python3 telesma/checks/telesma-checks.py --approve` shows what differs and records
  it. It refuses to run without a terminal.

**After you write an exception by hand, or pull a teammate's change to these files, run `--approve`**
(the startup validator reminds you with a warning). The honest limit: the baseline lives inside the
repository's `.git/`, which a determined process can also write to; it catches the sloppy and the
goal-seeking edit, not an adversary with a shell. The verifiable variant is CI on the pull request,
where a change to these files is in the diff.

### CI usage

The modules are committed with the project, so the pipeline runs exactly the same code:

```bash
python3 telesma/checks/telesma-checks.py --point ci --since origin/main
```

Exit code 1 when something blocks or a check did not run. `--since` sets the reference point
(`TELESMA_SINCE` for the modules) for "what is new". It takes seconds and needs no secrets. Run by hand
or in CI, the runner vouches for the `## Tests` commands of `lint-types` (whoever runs it runs the
project's tools knowingly); the integrity baseline is a hook matter and is not consulted. Running it by hand at `--point phase` on a
project that had no checks before is a good way to calibrate exceptions before they reach commits.

## The checks

| Check | Points | Blocks | Warns |
|-------|--------|--------|-------|
| `secrets` | commit, ci | keys in known formats: `private-key`, `aws-access-key`, `github-token`, `gitlab-token`, `slack-token`, `slack-webhook`, `anthropic-key`, `openai-key`, `google-api-key`, `stripe-live-key`, `huggingface-token`, `npm-token`, `pypi-token`, `sendgrid-key`, `digitalocean-token` (also split into adjacent literals: `<rule>-split`, or wrapped in base64: `<rule>-base64`); `url-credentials` (`scheme://user:password@host` to a real host); `secret-file` (`.env`, `*.env`, `*.pem`, `id_rsa`…); every `gitleaks:<rule>` when gitleaks is in PATH | `jwt`, `secret-assignment` (a name holding `password` / `secret` / `token` / `api_key`… with any prefix: `DB_PASSWORD = "…"`, `SECRET_KEY = "…"`; bare `NAME=value` in env files), `url-credentials` to localhost / a service name |
| `weakenings` | commit, phase, release, ci | `incomplete-marker` (marker without id or reason), `mutant` (`MUTANT` in code); at `release`: every `open-weakening` | at `phase`: `open-weakening`; patterns without a marker: `tls-disabled`, `debug-enabled`, `csrf-disabled`, `security-bypass`, `bypass-token`, `cors-any-origin`, `secret-in-response` |
| `dependencies` | commit, ci | a **new** package that is `not-found` in the registry (a name invented by the model), `fresh-package` (< 7 days), or `similar-to-popular` and young or rarely downloaded (typosquatting) | `similar-to-popular`, `young-package` (< 30 days), `few-downloads`, `deprecated`, `install-scripts`, `outside-registry` (git/URL), `extra-index` (dependency confusion), `other-registry`, `not-checked` (registry unreachable) |
| `dependency-audit` | phase, release, ci | `vulnerability`: critical/high from OSV, with a fixed version **newer than the installed one**, in a production dependency | the rest; `unreadable-lockfile`; `not-checked` (OSV unreachable) |
| `tests` | commit, ci | `only` (`.only`, `fit`, `fdescribe`), `skip-without-reason` (also `xfail`, `expectedFailure`, `pytestmark = …skip`, `pytest.skip()` in the body, `return` as the first statement, `test.fixme` / `it.failing`), `test-deleted` while the tested module still exists (a rename out of the test pattern counts), `tests-removed` (fewer test functions than in HEAD, counted over the whole commit) | `skip-with-reason`, `test-without-assertion` (commented-out assertions and `x == x` do not count), `code-without-test`, `test-pinned-to-code` (test and code it checks changed together), `fewer-assertions` |
| `hygiene` | commit, ci | `build-dir` (`node_modules/`, `dist/`, `__pycache__/`…), `file-too-large` (> 5 MB), `lockfile-stale` (manifest dependencies changed without the lockfile) | `floating-version`, `binary-file`, `minified-bundle`, `ide-file`, `visual-artifacts`, `missing-gitignore` |
| `dead-entry` | phase, release, ci | — never | `symbol-without-entry`, `route-without-client`, `component-without-parent`, `dead-symbol-tool` — something **new since the last phase tag** that nothing outside its own test refers to; the mechanical guard of `AC: entry` |
| `sast` | commit, phase, ci | `sql-concatenation`, `shell-command`, `eval-exec`, `deserialization`, `path-traversal` | `xss-innerhtml`, `cors-any-origin-with-credentials`, `weak-hash`, `non-crypto-randomness`, `open-redirect`, `stacktrace-in-response`, `jwt-without-verification`, `xxe`, `ssrf`, `insecure-tmp`, `secret-in-log`, `nosec-suppression` (a `nosec` / `nosemgrep` that switched a rule off), `not-checked`. With `semgrep` in PATH also the OWASP packs |
| `lint-types` | commit, phase, ci | `typographic-quote` (a typographic quote used as a string delimiter), linter errors (`linter/<code>`) on changed files, typechecker errors (`types/<code>`) at phase/ci | `linter/format`, linter warnings, `linter-unknown` / `types-unknown` (not a known tool called directly — not run), `config-unconfirmed` (`## Tests` changed since the last start — not run), `*-unavailable`, `*-failed`, `*-timeout`, `*-more` |
| `intent` | commit, phase, ci | `route-outside-map` (a new HTTP route without a map row), `guard-mismatch` (a route whose definition lacks its role's guard) | `new-public-route`, `role-undecided`, `role-unknown`, `role-without-guard`, `route-gone`, `host-outside-map`, `secret-outside-map`, `db-privilege` (`GRANT`, `SECURITY DEFINER`, `BYPASSRLS`…), `encoded-blob`, `map-missing` |
| `red-team` | phase, release, ci | `red-team-missing`: a protected route changed in the phase without a red-team test for each required case | the same in the first phase after the map appears; `red-team-undecided` (routes with role `?`); `red-team-marker-invalid` (a marker that does not count) |

Each module's `telesma/checks/<name>/CHECK.md` has the full rule table, what it skips and why. Some notes
that matter in practice:

- **`secrets`** never prints any part of a secret: the log and the message carry rule, file, line, the
  **length** of the value and a hash. For `secret-assignment` and `url-credentials` the hash is of the
  name / the address, not of the value — a short hash of a weak password could be guessed, and the
  exceptions file is committed. It reads **every file in scope**: no size limit, long lines in windows,
  lockfiles, minified bundles, binaries and `.claude/` included. The built-in rules always run; with
  `gitleaks` in PATH its rules are added (`--redact`), and a project `.gitleaks.toml` / `.gitleaksignore`
  can silence only gitleaks, not the built-in rules. The exemption of test files for `secret-assignment`
  needs a test file by name **and** by content. What no pattern can close: a secret assembled at run time
  or encoded in a way of its own.
- **`dependencies`** checks only packages that **appeared** in a manifest (`package.json`,
  `requirements*.txt`, `pyproject.toml`, `deno.json`) compared with HEAD; scopes that `.npmrc` points
  to a private registry are skipped. Names go to the public registries, just as they would on install —
  URL-quoted, and a name no registry could hold is reported as `not-found` without being sent. On a
  Python older than 3.11 (no TOML reader) `pyproject.toml`, `poetry.lock` and `uv.lock` are reported as
  `not-checked` instead of being skipped in silence.
- **`dependency-audit`** always reads every tracked lockfile — a vulnerability appears in the database
  without any change in the project. It blocks only what a version bump fixes; a vulnerability without a
  fix is a decision for a human. One finding per package; the fingerprint covers the vulnerability list,
  so a waiver does not hide the next CVE in the same package.
- **`lint-types`** takes its commands from `## Tests` (`Linter/formatter`, `Typecheck command`). The hook
  never changes files: autofix flags (`--fix`, `--write`, `--apply`, rubocop `-a`/`-A`…) are stripped,
  formatters get `--check`. The typechecker runs only at phase/ci — `tsc` and `mypy` cannot sensibly
  check "only these files". Because the hook runs outside the permission system, the field is **not a
  way to run a command**: only a known tool called directly is run (exact program name; optionally
  through `npx` / `uv run` / `poetry run` / `python -m` and after `cd <dir inside the project> &&`) —
  never a script, `npm run …`, a pipe or a shell; and only when `## Tests` is the section you confirmed
  on this machine (the launcher's trust record). After Claude or a pull changes `## Tests`, the linter
  is not run (`config-unconfirmed`) until the next start of `telesma.sh`.
- **`dead-entry`** never blocks: its precision is still being measured.
- **`sast`** fingerprints an aggregated finding from **all** hit lines of the rule in the file, so an
  exception for line 12 does not silence a new injection on line 80. A call whose bracket closes on a
  later line is read as one line. `# nosec` still suppresses, and is reported (`nosec-suppression`).
  semgrep findings of rules about secrets in code are shown without the matched line.
- **Test files** are exempt from `sast`, from the weakening patterns and from `secret-assignment` only
  when the file is a test by name **and** holds a test (an import of a test framework, a test function,
  `describe(` / `it(` / `expect(` …). `src/db_spec.py` with production code in it is production code.

Network-based checks cache in `~/.cache/telesma/`; an entry is bound to the address it came from. The
environment variables that redirect the registries, OSV, the cache, `gh`, switch semgrep off or raise the
file-size limit (`TELESMA_REGISTRY_*`, `TELESMA_OSV`, `TELESMA_CACHE`, `TELESMA_GH`, `TELESMA_SEMGREP`,
`TELESMA_HYGIENE_MAX_MB`) exist for the self-tests and are honoured only with `TELESMA_CHECKS_TEST=1`.

## Exceptions belong to the human (`telesma/state/CHECK_EXCEPTIONS.md`)

A false positive is waived by its fingerprint, one line per finding:

```markdown
- `3f2a9c1e0b7d` secrets tests/fixtures/vendor_example.py — test key from the vendor's docs (Alex, 2026-10-07)
```

Every write by Claude to this file, to `telesma/checks/`, to the evidence directory or to the `## Checks`
section of the config **asks you**: through Edit/Write (the path is compared with symlinks resolved and
without regard to case; an edit is applied in memory and the section compared before and after), or
through a Bash command that can be read as a write to them (a redirect into them, `sed -i`, `cp`/`mv`/`rm`/
`ln`/`chmod`…, an interpreter one-liner naming them, `git checkout`/`restore` of them). Reading them does
not ask. What a command hides is caught by the integrity baseline (above). The author of the code does
not close the findings that block it; Claude reports a false positive as `TELESMA BLOCKED` instead.

After writing an exception yourself, run `python3 telesma/checks/telesma-checks.py --approve` in your
terminal — until then the changed file stops commits.

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
`telesma: red-team * /registrar/* — csrf`. A marker counts only when it names a route or a route prefix
with a concrete beginning (`* /*` covers nothing) and stands in a test or right above one (within 40
lines); one that does not is reported as `red-team-marker-invalid`.

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
audit. It is red when any commit has no evidence, when a commit checked after the fact has blocking
findings, or when a check did not run — absence is not green. Evidence is bound to content: the
pre-commit result goes only to a commit holding exactly the blobs that were read; any other commit
(an amend, a commit made outside the hook) is checked from its own content. The wizard adds the name to `Required checks`, so the judge will not merge a PR without
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

- **Input:** file paths on stdin, one relative path per line — split on `\n` only and do not strip
  them (files over 1 MB, lockfiles, minified bundles and `.claude/` are filtered out by the runner unless
  the frontmatter says `filter: none`; a module that needs them reads git itself). Environment:
  `TELESMA_POINT` (`commit` | `phase` | `release` | `ci`), `TELESMA_ROOT` (where the files are read from:
  the project root, or a snapshot of a commit being verified), `TELESMA_PROJECT` (always the project
  root: config and trust belong there), and `TELESMA_SINCE` when `--since` was given. The working
  directory is the module directory.
- **Output:** findings as JSON lines on stdout:
  `{"file": …, "line": …, "rule": …, "message": …, "severity": "block" | "warn", "content_fingerprint": …, "file_fingerprint": true}`.
  `severity`, `content_fingerprint` (what the fingerprint is computed from instead of the message — use
  it to survive line shifts) and `file_fingerprint: false` (the finding is about a thing, not a place)
  are optional.
- **Exit code:** `0` = checked (findings may exist), `3` = tool missing (reported as "did not run");
  anything else = the module broke, which blocks (`check-crashed`).
- **`--check`:** prints one line about readiness; a line starting with `warning:` becomes a startup
  validator warning.
- **Never print a secret's content** — not a prefix of it either; only its length and a fingerprint.

Then add a `### <name>` subsection to `## Checks` in the config. The fingerprint the runner computes
(check + rule + file + content) is what goes into `telesma/state/CHECK_EXCEPTIONS.md`.
