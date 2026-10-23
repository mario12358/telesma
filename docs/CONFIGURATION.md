# Configuration

All project settings live in `telesma/config.md`, created from `templates/config.md` the first time
the launcher runs on a project with a specification, and filled in by the **setup wizard** (one
question per module, see [Setup wizard](#setup-wizard)). It is a Markdown file of `## Section`
headers and `- **Key**: value` lines. The `<!-- -->` comment next to each key in the template is the
authoritative description of that key; this page is the overview.

At every start the launcher **merges** new keys and sections from the template into your file
(your values are kept), so a project picks up new settings without manual edits.

`telesma/config.md` is committed. **Never put a secret in it** — keys that need one take a reference
(`env:`, `file:`, `cmd:`), see [Secrets in config](#secrets-in-config).

- [Sections and keys](#sections-and-keys)
- [Validation at startup](#validation-at-startup)
- [Working directories](#working-directories)
- [Permissions sync and generalization](#permissions-sync-and-generalization)
- [Commit and PR footer](#commit-and-pr-footer)
- [Automatic project updates](#automatic-project-updates)
- [Run modes and launcher flags](#run-modes-and-launcher-flags)

## Setup wizard

The wizard runs by itself when `telesma/config.md` is created, and on demand with
`telesma.sh --setup <project>`. Its deterministic half is `templates/setup/configure.py` (stack
detection, profiles, check tiers, field edits — every change printed as one line); the questions
live in `templates/setup/wizard.sh`. It writes only `telesma/config.md`, plus the templates of
`telesma/spec/APP_FLOW.md` / `telesma/spec/ux_ui/LINKS.md` when visual artifacts are turned on.

| Profile | Permission judge | Quality checks | Also asks about |
|---|---|---|---|
| `minimal` | off | none | — |
| `recommended` (ENTER) | on, `rules` | `basic` | — |
| `full` | on, `rules` | `standard` | integrations, visual artifacts, telemetry |

Steps: git repository (offers `git init`) → stack and tests (detected from manifests, one level
down in a monorepo; proposals you can edit) → permission prompts → quality-check tier →
[integrations, visual artifacts, telemetry] → language → summary and next steps. On an existing
project `--setup` shows a menu with the state of every module and lets you change one at a time.
Without a terminal the first start applies `recommended` silently and prints the summary.

Check tiers are sets of `### <check>` blocks under `## Checks`: `basic` = secrets, weakenings,
tests, hygiene; `standard` adds dependencies, dependency-audit, sast, lint-types, dead-entry;
`security` adds intent and red-team. The wizard keeps your edits inside a kept block and takes
missing blocks from the template; the merge at startup respects removed blocks.

## Sections and keys

### `## Project`

| Key | Default | Meaning |
|---|---|---|
| `Clarified` | `no` | `no` = the next start runs the clarification phase; `yes` = the plan is ready, the mode menu appears. Telesma sets it itself at the end of clarification. |
| `Language` | `en` | The language Telesma uses to talk to you and to write prose into state files (`en`, `pl`, `de`, …). Structural labels — section headers, field names, task keywords, tags — stay English because scripts parse them. Injected into the prompt as `LANGUAGE: <code>`. |

### `## Tests`

| Key | Default | Meaning |
|---|---|---|
| `Test command` | placeholder | Runs the task's tests. **Required** — a placeholder is a startup error. |
| `Full suite command` | placeholder | Full suite for regression detection after a phase. **Required.** |
| `Smoke suite` | `none` | A fast subset run after **every** task, so a regression is caught on the task that caused it rather than at the end of the phase. Small projects: the full suite. |
| `Full suite after` | `every phase` | When the full suite runs. |
| `Linter/formatter` | placeholder | Project linter, e.g. `ruff check`, `eslint`. Also used by the `lint-types` check on changed files at commit. `none` if you do not use one. |
| `Typecheck command` | `none` | Typechecker, e.g. `mypy src`, `npx tsc --noEmit`. Used by `lint-types` at the end of a phase. |
| `Lint before commit` | `no` | Run the linter before each commit. |

### `## Git`

| Key | Default | Meaning |
|---|---|---|
| `Auto-commit` | `yes` | Commit after each completed task (specific files only, never `git add -A`). |
| `Auto-push` | `no` | Telesma never pushes unless a repository integration is active (then: task branches only). |
| `Branch strategy` | `none (commit to the current branch)` | Branching convention. |
| `Ignore on commit` | `.env`, `*.log`, `node_modules/`, `telesma/artifacts/`, `telesma/state/PERMISSIONS.jsonl`, `telesma/state/CHECKS.jsonl`, … | Patterns never committed. Keep each pattern in backticks — Markdown linters turn bare `*.log` or `__pycache__` into emphasis and silently break the list. |

### `## Integrations`

Off by default; filled in by the wizard (`--integrations`). Details: [INTEGRATIONS.md](INTEGRATIONS.md).

| Key | Default | Meaning |
|---|---|---|
| `Repository` | `none` | `none` \| `github`. Branch per task, PR, merge; a task is done on merge. Requires `gh` logged in and `Auto-push: yes`. |
| `Repo` | | `owner/name` on GitHub (detected from `origin`). |
| `Merge` | `agent` | `agent` = Telesma waits for the required checks and squash-merges; `auto` = GitHub auto-merge (needs branch protection); `manual` = a human merges. |
| `Required checks` | `none` | Comma-separated check names. Must not be empty in `agent` mode. |
| `Open PR limit` | `3` | Reached with no red PR → `TELESMA WAITING`, end of session. |
| `Wait for merge` | `10 min` | How long to wait for checks/merge after opening a PR before taking another task. |
| `Max fixes per PR` | `3` | Fixes on a red PR before `TELESMA BLOCKED`. Separate from `Max tries per task`. |
| `Branch prefix` | `task-` | Task branches are `<prefix><id>-<slug>`; the judge removes push prompts only for these. |
| `Tracker` | `none` | `none` \| `specky`. |
| `Tracker project` | | The Specky project id (from the project URL). |
| `Tracker MCP` | `https://app.specky.app/mcp` | The tracker's MCP address (the MCP tools themselves are configured in Claude Code). |

### `## Checks`

Quality checks triggered by git operations. Off by default. Details: [CHECKS.md](CHECKS.md).

| Key | Default | Meaning |
|---|---|---|
| `Enabled` | `no` | `yes` installs the hook and copies the check modules into `telesma/checks/`. |
| `PR status` | `yes` | With the GitHub integration, post the commit status `Telesma: checks (local)` after each push to a task branch. |

Then one `### <check>` subsection per check — `secrets`, `weakenings`, `dependencies`,
`dependency-audit`, `tests`, `hygiene`, `dead-entry`, `sast`, `lint-types`, `intent`, `red-team` —
grouped by the wizard into the tiers `basic` / `standard` / `security` ([Setup wizard](#setup-wizard)),
each with:

| Key | Values |
|---|---|
| `When` | Points: `commit`, `phase`, `release`, `ci` |
| `Scope` | `changed` \| `all` |
| `On failure` | `block` \| `warn` — the config can soften a module's severity, never harden it |
| `Time limit` | Optional, e.g. `30 s`, `5 min` |

A check without a subsection does not run and costs nothing. Writes to this section, to
`telesma/checks/` and to `telesma/state/CHECK_EXCEPTIONS.md` always ask the human.

### `## Visual artifacts`

Opt-in screenshots and recordings ([WORKFLOW.md § 7](WORKFLOW.md#7-visual-artifacts)).

| Key | Default | Meaning |
|---|---|---|
| `Screenshots` | `no` | `yes` = after a task tagged `(screen: <id>)`, save `telesma/artifacts/screens/<id>.png`. |
| `Recordings` | `no` | `yes` = on e2e tasks tagged `(flow: …#step-N)`, save a video to `telesma/artifacts/flows/`. |
| `Flow files` | `telesma/spec/APP_FLOW.md` | Files with `## Step N — Title` flows (comma-separated). |
| `Artifacts dir` | `telesma/artifacts/` | Where artifacts go. |
| `Commit artifacts` | `no` | `yes` = artifacts go into git (consider Git LFS for videos). |

### `## Telesma loop`

| Key | Default | Meaning |
|---|---|---|
| `Max tries per task` | `3` | Tries before `TELESMA BLOCKED`. Later tries widen the context (neighbouring spec sections, the whole file, the problem log). |
| `Report progress` | `yes` | Kept for compatibility; currently not read by the launcher or the instructions. |
| `Rotate state files` | `yes` | Move older entries of REPORT.md, PROJECT_CONTEXT.md and PLAN.md into `*_ARCHIVE.md` at every start ([STATE_FILES.md](STATE_FILES.md#state-file-rotation)). `no` turns all rotation off. |
| `Plan phases in file` | `5` | How many of the latest fully completed phases stay in PLAN.md in full; only applies above 100 KB of plan. `none` = never touch PLAN.md; `0` = archive every completed phase. |
| `Active phases` | `all` | `all`, or a list of phase ids (`1, 2, 3` or `1M, 2M, 3M`). Case-sensitive. Rework phases `.Z<n>` follow their base phase. Used for multi-client tracks. |

Older projects may still carry `Compact every`; it has no effect — Claude cannot run `/compact`
itself, and auto-compaction is handled by keeping state files current after every task.

### `## Working directories`

| Key | Default | Meaning |
|---|---|---|
| `Extra directories` | empty | Directories outside the repository Claude may access without prompts. See [below](#working-directories). |
| `Auto-sync directories` | `yes` | Directories added to `.claude/settings.local.json` outside this file come back into it at startup. |

### `## Auto-approval`

The permission judge. Off in the template; the setup wizard's recommended profile turns it on in
`rules` mode. Full description: [PERMISSION_JUDGE.md](PERMISSION_JUDGE.md).

| Key | Default | Meaning |
|---|---|---|
| `Auto-approve` | `no` | `yes` installs the `PermissionRequest` hook. |
| `Force ask despite allowlist` | `no` | Adds a `PreToolUse` hook whose "ask" beats a broad allow rule. The only key that **adds** prompts. |
| `Suggest command fixes` | `yes` | Commands Claude Code always prompts on because of their shape (`cd X && git …`) are bounced back with a rewrite instruction instead. |
| `Allow reads` | `yes` | A command whose every member is provably a read inside the project passes without a model. |
| `Judge` | `rules` | `rules` (hard patterns, "Always ask" and the read layer — no model), `command` (same script + an OpenAI-compatible model for the gray zone), `none`, `prompt`, `agent` (Claude Code's built-in judges). |
| `Risk level` | `conservative` | `conservative` \| `balanced`. |
| `Gated tools` | `Bash` | Tool-name regex the judge handles. |
| `Model (command)`, `Endpoint (command)`, `API key (command)` | local Ollama example | The judge model, used only with `Judge: command`. Run it through the evaluation set before trusting it. |
| `Fallback endpoint (command)`, `Fallback model (command)`, `Fallback API key (command)` | `none` | A second model, asked only when the primary does not answer. |
| `Fallback mode` | `shadow` | `shadow` = the fallback only logs its verdict; `allow` = its ALLOW removes the prompt. |
| `Model (prompt/agent)` | a Haiku model | Model for the `prompt` / `agent` variants. |
| `Decision log` | `yes` | Every decision → `telesma/state/PERMISSIONS.jsonl` (stays on this machine). |
| `Log human decision` | `yes` | Records that a command you were asked about actually ran — the only labels a model can be evaluated on. |
| `Always ask` | empty | Your own regex patterns, checked before the model; the model cannot override them. |

### `## Telemetry`

Optional quality events sent to a server you host. Off by default — nothing leaves your machine.
Details: [TELEMETRY.md](TELEMETRY.md).

| Key | Default | Meaning |
|---|---|---|
| `Send` | `no` | `yes` = send to `Endpoint`. |
| `Endpoint` | `none` | Address of your own server. |
| `API key` | `env:TELESMA_HUB_TOKEN` | A reference, never a literal. |
| `Project label` | empty | Readable project name; empty = directory name. |

### `## Permissions`

Synced both ways with `.claude/settings.local.json` ([below](#permissions-sync-and-generalization)).

| Key | Default | Meaning |
|---|---|---|
| `Mode` | `acceptEdits` | `default` (asks about every tool), `acceptEdits` (Edit/Write auto-accepted, Bash asks), `bypassPermissions` (no prompts — risky), `plan`. |
| `Auto-sync new permissions` | `yes` | "Allow always" answers given during a session are merged back here at the next start. |
| `Generalize permissions` | `yes` | Exact approved commands from safe families are promoted to prefix patterns. |
| `Allowed commands` | test runners, `mkdir`, `ls`, safe git, `WebFetch(domain:claude.ai)` | Allow rules. |
| `Denied commands` | `rm -rf`, `sudo`, `git push --force`, `git reset --hard` | Deny rules; deny always wins over allow. |

### Secrets in config

Keys that need a secret (`API key (command)`, `Fallback API key (command)`, the telemetry `API key`)
accept:

| Form | Meaning |
|---|---|
| `env:NAME` | An environment variable. |
| `file:<path>` | The first line of a file **outside** the repository — works even when you start `claude` without the launcher. |
| `cmd:<command>` | The command's stdout — macOS Keychain, `pass`, a vault. |
| `none` | No `Authorization` header (a local server). |
| a literal | Allowed for the judge but warned about at every start; use only when `config.md` is not under version control. Never for telemetry. |

Anything that cannot be resolved means the feature stays silent — for the judge, the prompt goes to you.

## Validation at startup

The launcher reads `config.md` as data before starting Claude:

- `Test command` or `Full suite command` missing, empty or still a `[…]` placeholder → **error**. In
  autonomous mode you are asked whether to continue anyway (the same `[y/N]` gate as plan errors);
  other modes just print it. The reason: a placeholder test command once survived 100 days on a
  real project — Claude invented a command and "green suite" meant whatever it guessed.
- Any other placeholder-shaped value → one **warning** per key.
- `Smoke suite: none` on a plan over 50 KB → warning: a regression then surfaces only at the end of the
  phase, with no task to attribute it to.
- Judge endpoint and key resolvable; integration fields (`gh` installed, logged in, version ≥ 2.41;
  with `Merge: auto`, the repository's auto-merge and branch protection); the checks section (modules
  exist, points valid, tools available — `telesma-checks.py --validate`).

## Working directories

`## Working directories` declares directories outside the repository Claude may use without
prompts — a build cache, an asset directory, a neighbouring repository your scripts depend on.

```markdown
- **Extra directories**:
  - /tmp/my-project-logs
  - ~/.cache/my-project
- **Auto-sync directories**: yes
```

- The project directory is always accessible; do not list it. Relative paths resolve against the
  project; `~` and `$VARIABLES` are expanded.
- The list is synced into `permissions.additionalDirectories` in `.claude/settings.local.json`.
  Entries there grant **file access only** — unlike the `--add-dir` flag, which would also load
  `CLAUDE.md`, hooks and skills from that directory. That difference is the reason Telesma uses the
  settings file.
- The permission judge reads the same list, so it stops guessing "outside the project" from `/` and
  `~` prefixes: file operations (`cp`, `mv`, `rm`, `tee`, redirections) into a declared directory pass,
  while `cp src/x ~/Documents/x` still asks. Recursive deletes pass **only** inside working
  directories; inside the repository they still ask — that is where work lives that nobody can
  recreate.
- **No need to list** the Claude Code session scratchpad (`/private/tmp/claude-<uid>` or
  `/tmp/claude-<uid>`): the judge trusts it by default — it is the agent's own workspace, so the common
  backup → mutate → restore pattern works with no configuration. List its root only if you also want
  Claude Code to *read* from there without prompts (the per-session path contains a UUID; list the root).
- **Bad candidates**: toolchain directories (`/opt/homebrew/bin`, `/Library/Frameworks/…`). You need
  to read them, but an entry here also grants **write** access under `acceptEdits`; use a
  `Read(/path/**)` rule in `## Permissions` instead.
- **Rejected**: roots whose addition would switch protection off rather than configure it — `/`, `~`,
  `$HOME`, `/Users`, `/Volumes`, `/System`, `/Library`, `/etc`, `/usr`, `/var`, `/tmp` — are refused with
  a red message. A directory that does not exist gives a yellow warning and stays in the list.

## Permissions sync and generalization

`## Permissions` is synced both ways with `.claude/settings.local.json` at every start: the union of
both lists is written to both files. During a session Claude Code itself appends "allow always"
answers to `settings.local.json`; the next start merges them back into `config.md`.

The problem this solves: Claude Code stores "allow always" as **exact** commands
(`Bash(npm test -- --coverage)`), so every variation prompts again and stalls the autonomous loop.

**Generalization** (`Generalize permissions: yes`): an approved command from a curated list of safe
families is promoted at startup to a prefix pattern — approving `docker compose up -d postgres`
gives `Bash(docker compose:*)`, approving `uv run pytest -x` gives `Bash(uv run:*)`. Exact entries
covered by a pattern are removed. The families cover test runners and linters (pytest, jest, vitest,
ruff, eslint, tsc, playwright, detox, …), builds and package managers (npm/yarn/pnpm
install|run|test, pip, uv, poetry, cargo, go, docker compose|build), safe git (status, diff, log,
show, add, commit, tag, describe, fetch) and file tools (ls, mkdir, grep, find, …).

**Never generalized**: `rm`, `sudo`, `curl`/`wget`, `git push`, `git reset`, `docker run` and anything
outside the list — they stay exact, and each new variation needs your approval. `Denied commands`
always wins over `Allowed commands`.

The launcher also writes hook entries for the permission judge and the quality checks into the same
file when those are enabled, and removes them when they are disabled. Your own keys in
`settings.local.json` are preserved.

## Commit and PR footer

Every commit, pull request and PR comment Telesma writes ends with exactly:

```
🤖 Generated with Telesma
```

— no model name, tool name or session link. The launcher writes this into the `attribution` key of
`.claude/settings.local.json` (where Claude Code would otherwise put `Co-Authored-By` and a session
link), and the instructions repeat the rule for the model. Project trailers such as `Specky-Req:` go
above the footer.

## Automatic project updates

Telesma evolves centrally and many projects use it, so projects update **themselves at every start**:

- **Migrations** — one-time repairs of project files after a framework change, gated by
  `telesma/state/.telesma-version` (committed, so a team stays consistent) and idempotent.
- **Delivered files** (`telesma/guidelines/`, the judge hook, check modules, the test scenarios
  skeleton) — `telesma/state/.telesma-manifest` remembers which template version each file received. Template
  changed and your file untouched → replaced automatically. Your file edited → a one-time notice with
  a ready `diff` command; never a silent overwrite.
- **config.md** — new keys and sections merged in at every start.

## Run modes and launcher flags

```bash
telesma.sh [options] [project_dir]
```

| Flag | Meaning |
|---|---|
| `-i`, `--interactive` | Start Claude interactively (an open chat) instead of in pipe mode. |
| `-m`, `--mode <1\|2\|3\|4>` | Choose the mode and skip the menu: 1 autonomous, 2 bugfix, 3 review, 4 artifacts. |
| `--repair` | Repair state files from git history and exit, without starting Claude ([STATE_FILES.md](STATE_FILES.md#diagnosis-and---repair)). |
| `--setup` | Configuration menu on an existing project: the state of every module, pick one to change ([Setup wizard](#setup-wizard)). Exits afterwards. |
| `--integrations` | Run only the integrations wizard on an existing project; writes only `telesma/config.md`. |
| `--sync-specky` | With `Tracker: specky`: a short Claude session that turns Specky changes into files in `telesma/changes/`. No loop. |
| `-h`, `--help` | Show help. |

Behaviour by mode:

- **Clarification** (`Clarified: no`) always runs interactively; `-i` is forced. Interrupt with
  Ctrl+C at any time; the next start resumes from the first unanswered item.
- **Modes 2 and 3** always run interactively (the chat is the point).
- **Modes 1 and 4** run in pipe mode by default and work to the end on their own. If Telesma blocks in
  pipe mode, stdin is closed — the blocker is saved to `telesma/state/BLOCKED.md`, shown at the next start and
  passed to Claude to resolve. With `-i` you can answer questions as they come.

```bash
telesma.sh /path/to/project            # menu
telesma.sh /path/to/project -m 1       # mode 1, pipe
telesma.sh /path/to/project -m 1 -i    # mode 1, interactive
telesma.sh /path/to/project -m 2       # mode 2 (interactive)
telesma.sh /path/to/project -m 3       # mode 3 (interactive)
telesma.sh /path/to/project -m 4       # mode 4, pipe
```

The instructions are assembled per mode from `templates/instructions/`: each mode receives only its
own sections (core, the mode module, the interactive module, and integration or check modules when
configured), which keeps the startup prompt small and prevents behaviour leaking between modes.
