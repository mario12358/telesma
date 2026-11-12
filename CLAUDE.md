# CLAUDE.md

Guidance for Claude Code (or a human) working **on** the Telesma repository. The reasoning behind
the design — why things are the way they are, with the numbers that decided them — lives in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Read it before changing a mechanism.

## Project overview

Telesma is an autonomous development framework for Claude Code. Instead of restarting the CLI for
every task, it runs **one continuous session** in which Claude drives the loop itself: read spec →
clarify → generate plan → pick the next task (respecting dependencies) → load only the spec
fragments and technology guidelines it needs → implement → test → check for regressions → commit →
report → repeat, using `/compact` to manage context. Everything that must survive a compaction or
a new session lives in state files under `telesma/` in the user's project.

The repository contains:

- a Bash launcher (`telesma.sh`) that prepares the project, migrates, rotates and validates
  state files, assembles the startup prompt from instruction templates and starts Claude Code;
- Markdown instruction templates that are fed to the model;
- templates for state files written into the user's project;
- Python hooks (permission judge, quality checks) and standalone tools (repair, telemetry, judge
  evaluation), all stdlib-only;
- self-tests and a frozen benchmark.

## Repository structure

```
telesma.sh                         Launcher: setup, format gate, rotation, validation, prompt assembly, start
install.sh, install.ps1            One-line installers (macOS / Windows): dependencies, Telesma, desktop shortcut → --home
templates/
├── instructions/                  Model instructions, assembled per mode by the launcher
│   ├── INTERVIEW.md               Section -2: the --new interview that writes telesma/spec/ (idea, no spec)
│   ├── SURVEY.md                  Section -3: the --adopt survey of an existing codebase (loop over Phase 0 → AS_BUILT.md)
│   ├── BEGINNER.md                EXPERIENCE: beginner block, appended after LANGUAGE for Experience: beginner
│   ├── CLARIFY.md                 Section -1: clarification and plan generation
│   ├── CORE.md                    Sections 0-9 + global rules (every implementation mode)
│   ├── INTERACTIVE.md             Sections 10 (decision log), 13 (backlog), 15 (release versions)
│   ├── MODE_BUGFIX.md             Section 11 (mode 2)
│   ├── MODE_REVIEW.md             Section 12 (mode 3)
│   ├── MODE_ARTIFACTS.md          Section 14 (mode 4)
│   └── CHECKS.md                  Section 19 (only with ## Checks → Enabled: yes)
├── PLAN_TEMPLATE.md               Plan format: phases, tasks, dependencies, tags, AC lines
├── REPORT.md, PROJECT_CONTEXT.md  State-file templates (structure is parsed — see below)
├── config.md                      Per-project configuration (tests, git, integrations, checks, judge, telemetry)
├── QUESTIONS_TEMPLATE.md          Clarification: contradictions (S), assumptions (A), questions (Q)
├── SPEC_INDEX_TEMPLATE.md         Spec index with line ranges, anchors and quality assessment
├── SPEC_TEMPLATE.md               telesma/spec/TECHNICAL_GUIDELINES.md skeleton
├── AS_BUILT_TEMPLATE.md           telesma/spec/AS_BUILT.md skeleton (adopted projects: the system as found)
├── CHANGES_TEMPLATE.md            Change request format for telesma/changes/
├── BACKLOG_TEMPLATE.md            telesma/state/BACKLOG.md skeleton
├── TEST_SCENARIOS_TEMPLATE.md     Skeleton of docs/test-scenarios/vX.Y.Z.md (section 15.7)
├── APP_FLOW_TEMPLATE.md           telesma/spec/APP_FLOW.md: user flows (## Step N) for e2e + recordings
├── UX_LINKS_TEMPLATE.md           telesma/spec/ux_ui/LINKS.md: registry of external mockup links
├── guidelines/                    Technology guidelines copied to telesma/guidelines/ (general.md + one per tag, 48 tags)
├── messages/                      msg.sh (msg KEY 'English' → <lang>.txt) + pl.txt: launcher lines in Language
├── setup/                         preflight.sh (git, python3, claude + sign-in; every start and --doctor;
│                                  the ## Tests tools before a build session); home.sh (--home start menu);
│                                  setup wizard: wizard.sh (questions, first start and --setup) + configure.py (engine:
│                                  stack detection, profiles minimal/recommended/full, check tiers basic/standard/security);
│                                  trust.py (per-machine confirmation of config.md's executable sections — the only writer);
│                                  sandbox.py (## Sandbox → Claude Code's built-in sandbox in settings.local.json)
├── hooks/telesma-permission-judge.py  Permission judge (PermissionRequest/PreToolUse/PostToolUse hook)
├── checks/                        Quality checks (## Checks, section 19), copied to telesma/checks/
│   ├── telesma-checks.py            Runner: git-operation hook, PR status, --point ci, --validate
│   ├── _net.py                    Shared HTTP + ~/.cache/telesma/ cache for checks that call services
│   ├── _routes.py                 Shared route extraction (FastAPI, Flask, Express, Hono, Fastify, Nest) + map parser
│   ├── secrets/                   Known key formats, secret-named files; gitleaks when present
│   ├── weakenings/                `telesma: weakening <id> — <reason>` markers, MUTANT, unmarked weakening patterns
│   ├── dependencies/              New packages vs npm/PyPI/JSR: missing, too young, typosquat
│   ├── dependency-audit/          OSV vulnerabilities for lockfile versions
│   ├── tests/                     Weakened tests: .only, reasonless skip, deleted test blocks
│   ├── hygiene/                   Build dirs, big files, manifest without lockfile, floating versions
│   ├── dead-entry/                New symbol/route/component nothing calls (warns only)
│   ├── sast/                      semgrep (OWASP packs) or built-in patterns
│   ├── lint-types/                Project linter at commit, typechecker at phase
│   ├── intent/                    Code vs attack-surface map telesma/state/SECURITY_MAP.md (MAP_TEMPLATE.md)
│   └── red-team/                  Changed protected route needs a `telesma: red-team` test marker
│                                  (each check dir: CHECK.md frontmatter + run.py)
└── integrations/                  Optional integrations (## Integrations)
    ├── lib.sh, wizard.sh          Wizard menu + shared helpers (config_field, set_field, add_permissions)
    ├── git/github/                Section 17: branch per task → PR → checks → squash merge
    └── tracker/specky/            Section 18: requirement anchors, criteria evidence, sync, snapshots
                                   (each: INSTRUCTIONS.md, setup.sh, permissions.txt, DESCRIPTION.txt)
tools/
├── telesma-task.py                  The task loop's mechanics for the model: next (task + context, terminal
│                                  states, reservation), done (tests, checks, tick, Task history row, commit),
│                                  commit --kind, suite (full suite, Test status, phase tag, regression gate),
│                                  changes / changes-done; runs from this clone, never copied into a project
├── telesma_state.py               Shared plan / config / report reading (the launcher's plan check and next)
├── telesma_github.py              The GitHub flow of section 17 for the task tool: PR list, required checks,
│                                  squash merge, chain re-point + rebase, branch, push, PR
├── telesma-guard.py                 PreToolUse "code only" guard: refuses git / gh writes, ticks in PLAN.md and edits
│                                  of REPORT.md's history sections (format 21+)
├── telesma-repair.py                State-file diagnosis (every start) and repair (--repair)
├── telesma-telemetry.py             Optional quality telemetry collector (schema 2)
├── telesma-survey.py                Git digest + survey units for --adopt (SURVEY: block, Phase 0 tasks)
├── telesma-specky-snapshots.py      Backfill Specky release snapshots for existing vX.Y.Z tags
├── telesma-judge-eval.py            Judge evaluation on a labelled set; gate = zero false allows
├── judge-eval/dataset.jsonl       The labelled set (dangerous / safe / disputed); heldout.jsonl is never tuned against
├── test-*.py                      Self-tests (fixtures in temp dirs, never touch this repo)
└── test-all.sh                    Runs every self-test
benchmark/                         Frozen benchmark: same small project on any Telesma version, hidden HTTP judge
docs/                              User documentation (INTEGRATIONS.md) and ARCHITECTURE.md
examples/example-plan.md           Example plan
```

## How instructions are assembled

`telesma.sh` never sends one fixed prompt. Per run it concatenates:

- `--new` with no complete spec: `INTERVIEW.md` + `BEGINNER.md` + the list of files already in
  `telesma/spec/` (an interactive session with `acceptEdits`; config.md is created before it with
  `Experience: beginner`, the first-start wizard runs after it);
- `--adopt` / an adopted project with an open task in Phase 0: `SURVEY.md` + the plan, context and
  report (with the test baseline the launcher ran) + the `SURVEY:` git digest from
  `tools/telesma-survey.py`; permission mode `default` with an `Edit(telesma/**)` allow rule;
- clarification (`Clarified: no`): `CLARIFY.md` (+ an `ADOPTED: yes` line for adopted projects);
- implementation modes: `CORE.md` + `INTERACTIVE.md` + the mode file (`MODE_BUGFIX.md`,
  `MODE_REVIEW.md`, `MODE_ARTIFACTS.md`; mode 1 has none) + `CHECKS.md` when checks are enabled +
  each configured integration's `INSTRUCTIONS.md` (appended after the mode block, so a project
  without integrations pays no tokens for them);
- `TASK_TOOL: python3 <clone>/tools/telesma-task.py` for the implementation modes and the survey,
  with a session-only allow rule (`--allowedTools`, never written to `settings.local.json`);
- the state files (PLAN, PROJECT_CONTEXT, REPORT, SPEC_INDEX, config) as **prompt copies**,
  trimmed (finished phases collapsed to ids, template comments stripped, long table rows cut);
- computed directives: `MODE: <mode>`, `LANGUAGE: <code>` (+ the `EXPERIENCE: beginner` block
  from `BEGINNER.md` when `## Project → Experience` is `beginner`; it changes prose only, never
  mechanics or file structure), `VERSIONS: …` (last `v*` tag, its date,
  commits since, attack-surface changes), `INTEGRATIONS: …`, `GUIDELINES_INDEX:`, the next-task
  `HINT:`, validator `ERRORS:`, pending `telesma/changes/`, and the contents of `telesma/state/BLOCKED.md` /
  `telesma/state/WAITING.md` left by the previous session.

Section numbers (0.1, 0.3, 15.7, 17.5 …) are referenced across files and stay stable.

## State files are a contract

Section titles, task keywords, tags and field labels in `templates/*.md` are written by the model
(following `templates/instructions/`) and **parsed** by the launcher (rotation, prompt diet,
plan/config validators, next-task hint), by `tools/telesma-repair.py`, `tools/telesma-telemetry.py`
and by the checks. Examples: `### Phase N: Title`, `Task N.M:`, `(requires: X.Y)`,
`(change: file.md)`, `(pr: #n)`, `- AC: entry — …`, `## Test status`, `## Task history`,
`## Problem log`, `[YYYY-MM-DD]` log openers, `## Key decisions`, `📌`, `Kind` / `Bug source` /
`Detected by`, `telesma/phase-<ID>` tags, `<!-- telesma-archived: … -->`.

Changing one structural token means changing, in the same change: the template, the
instructions that tell the model to write it, every parser that reads it, their test fixtures —
and adding a migration for existing projects (bump `TELESMA_FORMAT`). Free prose inside sections
is written in the user's `Language`; the structure is always English.

## Invariants — do not break these

- **The permission judge only removes prompts, it never adds blocks** — with one deliberate,
  tiny exception: the **contract layer** in PreToolUse refuses two things the instructions already
  forbid the agent (a merge while a required check is red, pending or missing, or with `--admin`;
  a push of a release tag) — in every spelling it can read: `gh pr merge`, `gh api …/merge`,
  `git push` of `v*` tags, `--tags`, `--mirror`, `gh release create vX`, and a merge or push whose
  PR or ref is a substitution or variable ("write it literally"). PreToolUse runs in every Claude Code permission mode, including `auto`,
  where the PermissionRequest hook is never called — a question there would reach nobody. Anything
  else dangerous still reaches the human: hard patterns and `Always ask` mean "ask", not "deny". A
  rule change must pass the evaluation gate (zero false allows on `dangerous`, in the working set
  and in the held-out set, which is never used to tune a rule; the mutation test in
  `test-judge.py` respells every dangerous case). What the parser cannot read is a question, never
  a pass. The one switch that adds prompts (`Force ask despite allowlist`) is opt-in. A `gh`
  failure never refuses.
- **`telesma/config.md` is confirmed per machine.** It is committed, and it names what runs on a
  person's machine: test, lint and typecheck commands, the permission mode and allow rules, judge
  and telemetry endpoints and key forms, extra directories, integrations. The launcher's trust
  gate (`templates/setup/trust.py`, record in `~/.config/telesma/trust/`) shows new or changed
  values and asks once, before anything executes one; without a terminal the start stops unless
  `TELESMA_TRUST_CONFIG=yes`; `bypassPermissions` is typed by the person, never taken from the
  environment. Only the launcher writes the record; the judge hook, the telemetry tool and the
  `lint-types` check read it and treat an unconfirmed section as "no key / do not run". The section
  hash is defined once (field lines of the section, sha256) and implemented identically in each.
- **Checks never print secrets** (findings carry rule, file, line, length and a hash — no part of
  the value) and **never block on network failure** (unreachable registry or OSV = warning; a
  missing tool or a time limit is a warning too, while an internal error of the hook, a crashed
  module or an unreadable command shape refuses the commit). **What is checked is what is
  committed**: the scope widens to everything modified whenever the `git add` plan is not exact,
  and a commit that appears without evidence is checked after the fact. Exceptions are the
  human's: writes to `telesma/state/CHECK_EXCEPTIONS.md`, `telesma/checks/` and the `## Checks`
  section ask the user, and a difference from the integrity baseline
  (`.git/telesma-checks/baseline.json`) that no approved edit explains stops the next commit until
  the human runs `telesma-checks.py --approve` in a terminal. The baseline lives where the agent
  can reach it — it catches a careless model, not a determined one; CI (`--point ci`) is the
  verifiable layer.
- **A task is finished by the script, not by the model.** `tools/telesma-task.py done` chooses the
  files (everything `git status` shows minus `Ignore on commit` and this machine's files), runs the
  `## Tests` commands only when that section is confirmed on the machine (a run with 0 tests is a
  failure), runs the commit-point checks on exactly those files and records their evidence, and only
  then ticks the task, writes the `Task history` row and commits with the footer. A refusal leaves
  PLAN.md and REPORT.md byte-identical. `next` and the launcher's hint choose the task with the same
  code (`tools/telesma_state.py`). The reservation lives in `.git/telesma-task/` — this machine's
  data; it keeps a careless model in line, not a determined one.
- **The "code only" guard refuses, by design** (`tools/telesma-guard.py`, registered by the launcher
  on every start, whatever `## Auto-approval` and `## Checks` say): git commands that write history
  or move refs, GitHub writes through `gh`, a tick or untick in PLAN.md, and edits of `Task history`,
  `Test status` and `Change history` in REPORT.md — each with the command to use instead. It is the
  second deliberate exception to "the judge only removes prompts" (the judge itself is unchanged);
  it is off below format 21. With `Repository: github` the task tool does the whole GitHub side
  (reconcile, merge on green required checks by squash, chain re-point before the merge and rebase
  after it, branch, push, PR); task PRs carry the task's work only, and what GitHub says (ticks,
  `(pr: #n)`, history rows, the phase run on main) is derived on main and committed by a state PR.
  A command it cannot read that mentions a git write is refused; an internal error lets the call through.
- **The session budget is the script's** (`## Telesma loop` → `Max refusals per task`, `Max attempts
  per task`, `Max tasks per session`, `Max hours per session`): the launcher snapshots the limits at
  `session-start`, the task tool counts and, past a limit, writes BLOCKED.md and marks the session;
  the guard then refuses everything but reads (with an integration too). Going on is the person's
  answer at the next start of the launcher, never the agent's.
- **Telemetry is off by default**; it sends only after an explicit per-machine opt-in, to the shared
  Telesma hub (opt-in file `~/.config/telesma/hub`, never a committed `Send: yes` alone; no sender
  name, no directory name) or to the user's own server (https only, and only after the
  `## Telemetry` section is confirmed on that machine); it never blocks startup, and never sends
  `telesma/spec/`, source code, `telesma/changes/` or commands from `PERMISSIONS.jsonl` (counters
  only). `tools/test-telemetry.py` pins this with canaries.
- **Repair never deletes what git does not know about**, and opens only REPORT.md,
  REPORT_ARCHIVE.md, PLAN.md and PLAN_ARCHIVE.md (the diagnosis at every start also reads
  PROJECT_CONTEXT.md). A run on a clean project changes nothing, byte for byte.
- **Rotation is block-based and date-driven**: an entry is a block, never a line; the N newest by
  date survive regardless of position; current-state sections are overwritten, chronicle sections
  rotate; the archive is written before the source file is shortened.
- **State and settings files are written atomically** (temp file in the same directory, then
  rename), and one launcher at a time works on a project (`telesma/state/.telesma-lock/`).
- **Prompt-copy trimming never touches files on disk.**
- **The sandbox is a layer under the questions, never instead of them** (`## Sandbox`,
  `templates/setup/sandbox.py`, written to `settings.local.json` after the mode is final): a refused
  command is never retried outside it (`allowUnsandboxedCommands: false` — the live probe showed an
  allow rule letting that retry through), `autoAllowBashIfSandboxed: false`, an autonomous session
  refuses an unknown host (`strictAllowlist`), the person's keys are not readable, while
  `~/.config/telesma` (the trust record, read by the task tool inside the sandbox) and, with the
  GitHub integration, `~/.config/gh` stay readable. The section is under the trust gate: `Allowed
  hosts`, `Writable paths` and `Excluded commands` loosen it.
- **Release version tags are never created without the user's answer**, never with `-f`, never
  pushed by Telesma. From format 21 they are created by `telesma-task.py release` only (clean tree, a
  green full suite on that state, the scenarios file committed, the `release` checks), which the
  guard always turns into a question to the person — in `auto` too — and refuses where a question
  reaches nobody (`bypassPermissions`, `dontAsk`); a hand-made `git tag` is refused. Commit/PR footer is exactly `🤖 Generated with Telesma`.
- **Everything in English** — identifiers, comments, messages, instructions, docs. The one
  exception is `templates/messages/<lang>.txt`: translations of the launcher lines a person sees
  from the idea to the first build, looked up by `msg KEY 'English text'` (the English stays in
  the code; a missing key falls back to it). `test-setup.py` keeps every catalog complete.
- **Python is stdlib-only; Bash is plain Bash 3.2+** (macOS default). Telesma is cloned, not installed.

## Versions

Two independent numbers:

- **Release version** (`vX.Y.Z` git tag, `CHANGELOG.md`) — what users install.
- **`TELESMA_FORMAT`** in `telesma.sh` — internal state-format / migration counter, stored per
  project in `telesma/state/.telesma-version`. Currently **23**. Bump it when a project's files need a
  migration, *and* when an instruction change should be measurable (telemetry tells "before" from
  "after" by this number). The format gate in the launcher runs before anything creates, reads or
  writes a file in the project: 18 = the first public format (the layout every later number
  shares), 19 = recall of earlier decisions (section 0.6, instructions only — the gate stamps a
  format-18 project 19 without touching any other file), 20 = adoption of existing projects
  (`--adopt`, section -3; the `Adopted` fields reach an older config through the merge), 21 = the
  task loop's mechanics in `tools/telesma-task.py` (`next` / `done` / `commit`; instructions only),
  22 = the sandbox (`## Sandbox` reaches an older config through the merge as `Enabled: no`; a config
  the launcher creates starts with `yes`), 23 = allow rules for what the task tool does (`git add` /
  `git commit`, phase tags, task-branch pushes, `gh pr create`) removed from config.md and
  settings.local.json (`templates/setup/retired_rules.py`).
  A new step is one `case` line in the gate's loop.

## Tests

```bash
tools/test-all.sh                   # every tools/test-*.py
tools/test-all.sh checks            # only files whose name contains "checks"
bash -n telesma.sh              # launcher syntax
python3 tools/telesma-judge-eval.py   # judge gate: zero false allows on "dangerous"
```

Self-tests: `test-setup.py` (configure.py engine; the launcher's first start without a terminal and
through a pty), `test-repair.py` (no word lost, out-of-scope files byte-identical, idempotent),
`test-telemetry.py` (canaries), `test-judge.py` (mocked `gh`; both evaluation sets, the mutation
test, the contract layer, answer parsing, the trust record), `test-checks.py`,
`test-integrations.py` (launcher heredocs on fixtures), `test-launcher.py` (rotation and prompt
trimming extracted from the launcher, trust gate, lock, format gate), `test-specky-snapshots.py` (fake Specky),
`test-survey.py` (git digest: numbers, never an author; survey units), `test-task.py` (`next` / `done` /
`commit` / `suite` / `changes` on temp git projects: selection, spec anchors, refusals that leave the
state files as they were, the 0-tests guard, the trust record, check evidence, the regression gate),
`test-guard.py` (what the guard refuses and lets through, when it is off, its registration),
`test-github-flow.py` (a fake `gh` and a local bare `origin`: PRs, merge on green, WAITING, PR fix,
the phase on main and its state PR, a chain re-pointed and rebased, side PRs, a closed PR),
`test-sandbox.py` (`## Sandbox` → the settings: fixed values, stack / check / GitHub hosts, the
person's additions kept, `Enabled: no` removing only Telesma's own key, the trust section).
A parser change comes with a fixture that would have failed before it. The benchmark
(`benchmark/bench.py`, see `benchmark/README.md`) costs real tokens; do not edit `project/`,
`telesma/changes/` or `hidden/` casually — any edit changes its fingerprint.

## Usage summary

```bash
./telesma.sh /path/to/project            # first run: creates telesma/spec/; second: config.md + setup wizard; later: mode menu
./telesma.sh --new /path/to/project          # no spec yet: interview writes telesma/spec/, Experience: beginner, then the wizard
./telesma.sh --adopt /path/to/project        # existing code: wizard + Adopted: yes; the next start = test baseline + survey → AS_BUILT.md
./telesma.sh --setup /path/to/project        # configuration menu (tests, judge, checks, integrations, artifacts, language)
./telesma.sh /path/to/project -i         # interactive (required for clarification)
./telesma.sh /path/to/project -m 1       # autonomous loop over telesma/state/PLAN.md
./telesma.sh /path/to/project -m 2       # bugfix chat (forces -i)
./telesma.sh /path/to/project -m 3       # code review chat (forces -i)
./telesma.sh /path/to/project -m 4       # visual artifact backfill (autonomous)
./telesma.sh --repair /path/to/project         # repair state files from git history, no Claude
./telesma.sh --home [folder]                   # start menu of the desktop shortcut: new idea or a project
./telesma.sh --doctor [project]                # what this machine still needs (git, python3, claude, sign-in; the project's tools)
./telesma.sh --integrations /path/to/project   # GitHub / Specky wizard
./telesma.sh --sync-specky /path/to/project    # Specky sync into telesma/changes/, no loop
```

Terminal states the model reports: `TELESMA COMPLETE`, `TELESMA BLOCKED` (written to
`telesma/state/BLOCKED.md`), `TELESMA WAITING` (open-PR limit reached, `telesma/state/WAITING.md`).

## Files in the user's project (short)

Everything lives in **one directory, `telesma/`**: `config.md`; `spec/` (frozen after clarification,
except `spec/ux_ui/LINKS.md`; adopted projects also hold `spec/AS_BUILT.md`, the system as found);
`changes/` and `changes/processed/`; `state/` (`PLAN.md`,
`REPORT.md`, `PROJECT_CONTEXT.md`, `SPEC_INDEX.md`, `QUESTIONS.md`, write-only logs `DECISIONS.md` /
`BUGFIXES.md` / `REVIEWS.md`, read-write `BACKLOG.md`, archives `*_ARCHIVE.md`, `SECURITY_MAP.md`,
`CHECK_EXCEPTIONS.md`, `CHECKS.jsonl`, `PERMISSIONS.jsonl`, `SPECKY.md`, `.telesma-version`,
`.telesma-manifest`); `guidelines/`; `checks/`; `artifacts/`. Outside it only what has to be
elsewhere: `.claude/settings.local.json` and `.claude/hooks/` (Claude Code looks for them there;
synced from config) and the project's own documentation, `docs/test-scenarios/vX.Y.Z.md` and
`docs/RUNBOOK.md`. Do not add a new top-level file or directory to the user's project. Delivered
templates (guidelines, hook, checks, scenario skeleton) auto-update through `.telesma-manifest`;
user edits win.
