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
templates/
├── instructions/                  Model instructions, assembled per mode by the launcher
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
├── CHANGES_TEMPLATE.md            Change request format for telesma/changes/
├── BACKLOG_TEMPLATE.md            telesma/state/BACKLOG.md skeleton
├── TEST_SCENARIOS_TEMPLATE.md     Skeleton of docs/test-scenarios/vX.Y.Z.md (section 15.7)
├── APP_FLOW_TEMPLATE.md           telesma/spec/APP_FLOW.md: user flows (## Step N) for e2e + recordings
├── UX_LINKS_TEMPLATE.md           telesma/spec/ux_ui/LINKS.md: registry of external mockup links
├── guidelines/                    Technology guidelines copied to telesma/guidelines/ (general.md + one per tag, 46 tags)
├── setup/                         Setup wizard: wizard.sh (questions, first start and --setup) + configure.py (engine:
│                                  stack detection, profiles minimal/recommended/full, check tiers basic/standard/security)
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
├── telesma-repair.py                State-file diagnosis (every start) and repair (--repair)
├── telesma-telemetry.py             Optional quality telemetry collector (schema 2)
├── telesma-specky-snapshots.py      Backfill Specky release snapshots for existing vX.Y.Z tags
├── telesma-judge-eval.py            Judge evaluation on a labelled set; gate = zero false allows
├── judge-eval/dataset.jsonl       The labelled set (dangerous / safe / disputed)
├── test-*.py                      Self-tests (fixtures in temp dirs, never touch this repo)
└── test-all.sh                    Runs every self-test
benchmark/                         Frozen benchmark: same small project on any Telesma version, hidden HTTP judge
docs/                              User documentation (INTEGRATIONS.md) and ARCHITECTURE.md
examples/example-plan.md           Example plan
```

## How instructions are assembled

`telesma.sh` never sends one fixed prompt. Per run it concatenates:

- clarification (`Clarified: no`): `CLARIFY.md`;
- implementation modes: `CORE.md` + `INTERACTIVE.md` + the mode file (`MODE_BUGFIX.md`,
  `MODE_REVIEW.md`, `MODE_ARTIFACTS.md`; mode 1 has none) + `CHECKS.md` when checks are enabled +
  each configured integration's `INSTRUCTIONS.md` (appended after the mode block, so a project
  without integrations pays no tokens for them);
- the state files (PLAN, PROJECT_CONTEXT, REPORT, SPEC_INDEX, config) as **prompt copies**,
  trimmed (finished phases collapsed to ids, template comments stripped, long table rows cut);
- computed directives: `MODE: <mode>`, `LANGUAGE: <code>`, `VERSIONS: …` (last `v*` tag, its date,
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
  a push of a release tag). PreToolUse runs in every Claude Code permission mode, including `auto`,
  where the PermissionRequest hook is never called — a question there would reach nobody. Anything
  else dangerous still reaches the human: hard patterns and `Always ask` mean "ask", not "deny". A
  rule change must pass the evaluation gate (zero false allows on `dangerous`). The one switch that
  adds prompts (`Force ask despite allowlist`) is opt-in. A `gh` failure never refuses.
- **Checks never print secrets** (findings carry rule, file, line and a hash) and **never block
  on network failure** (unreachable registry or OSV = warning). Exceptions are the human's: writes
  to `telesma/state/CHECK_EXCEPTIONS.md`, `telesma/checks/` and the `## Checks` section ask the user.
- **Telemetry is off by default**, goes only to the user's own self-hosted server, never blocks
  startup, and never sends `telesma/spec/`, source code, `telesma/changes/` or commands from `PERMISSIONS.jsonl`
  (counters only). `tools/test-telemetry.py` pins this with canaries.
- **Repair never deletes what git does not know about**, and opens only REPORT.md,
  REPORT_ARCHIVE.md, PLAN.md and PLAN_ARCHIVE.md. A second run changes nothing.
- **Rotation is block-based and date-driven**: an entry is a block, never a line; the N newest by
  date survive regardless of position; current-state sections are overwritten, chronicle sections
  rotate.
- **Prompt-copy trimming never touches files on disk.**
- **Release version tags are never created without the user's answer**, never with `-f`, never
  pushed by Telesma. Commit/PR footer is exactly `🤖 Generated with Telesma`.
- **Everything in English** — identifiers, comments, messages, instructions, docs.
- **Python is stdlib-only; Bash is plain Bash 3.2+** (macOS default). Telesma is cloned, not installed.

## Versions

Two independent numbers:

- **Release version** (`vX.Y.Z` git tag, `CHANGELOG.md`) — what users install.
- **`TELESMA_FORMAT`** in `telesma.sh` — internal state-format / migration counter, stored per
  project in `telesma/state/.telesma-version`. Currently **18**. Bump it when a project's files need a
  migration, *and* when an instruction change should be measurable (telemetry tells "before" from
  "after" by this number). The format gate in the launcher runs before anything creates, reads or
  writes a file in the project: 18 = current, the first public format.

## Tests

```bash
tools/test-all.sh                   # every tools/test-*.py
tools/test-all.sh checks            # only files whose name contains "checks"
bash -n telesma.sh              # launcher syntax
python3 tools/telesma-judge-eval.py   # judge gate: zero false allows on "dangerous"
```

Self-tests: `test-setup.py` (configure.py engine; the launcher's first start without a terminal and
through a pty), `test-repair.py` (no word lost, out-of-scope files byte-identical, idempotent),
`test-telemetry.py` (canaries), `test-judge.py` (mocked `gh`), `test-checks.py`,
`test-integrations.py` (launcher heredocs on fixtures), `test-specky-snapshots.py` (fake Specky).
A parser change comes with a fixture that would have failed before it. The benchmark
(`benchmark/bench.py`, see `benchmark/README.md`) costs real tokens; do not edit `project/`,
`telesma/changes/` or `hidden/` casually — any edit changes its fingerprint.

## Usage summary

```bash
./telesma.sh /path/to/project            # first run: creates telesma/spec/; second: config.md + setup wizard; later: mode menu
./telesma.sh --setup /path/to/project        # configuration menu (tests, judge, checks, integrations, artifacts, language)
./telesma.sh /path/to/project -i         # interactive (required for clarification)
./telesma.sh /path/to/project -m 1       # autonomous loop over telesma/state/PLAN.md
./telesma.sh /path/to/project -m 2       # bugfix chat (forces -i)
./telesma.sh /path/to/project -m 3       # code review chat (forces -i)
./telesma.sh /path/to/project -m 4       # visual artifact backfill (autonomous)
./telesma.sh --repair /path/to/project         # repair state files from git history, no Claude
./telesma.sh --integrations /path/to/project   # GitHub / Specky wizard
./telesma.sh --sync-specky /path/to/project    # Specky sync into telesma/changes/, no loop
```

Terminal states the model reports: `TELESMA COMPLETE`, `TELESMA BLOCKED` (written to
`telesma/state/BLOCKED.md`), `TELESMA WAITING` (open-PR limit reached, `telesma/state/WAITING.md`).

## Files in the user's project (short)

Everything lives in **one directory, `telesma/`**: `config.md`; `spec/` (frozen after clarification,
except `spec/ux_ui/LINKS.md`); `changes/` and `changes/processed/`; `state/` (`PLAN.md`,
`REPORT.md`, `PROJECT_CONTEXT.md`, `SPEC_INDEX.md`, `QUESTIONS.md`, write-only logs `DECISIONS.md` /
`BUGFIXES.md` / `REVIEWS.md`, read-write `BACKLOG.md`, archives `*_ARCHIVE.md`, `SECURITY_MAP.md`,
`CHECK_EXCEPTIONS.md`, `CHECKS.jsonl`, `PERMISSIONS.jsonl`, `SPECKY.md`, `.telesma-version`,
`.telesma-manifest`); `guidelines/`; `checks/`; `artifacts/`. Outside it only what has to be
elsewhere: `.claude/settings.local.json` and `.claude/hooks/` (Claude Code looks for them there;
synced from config) and the project's own documentation, `docs/test-scenarios/vX.Y.Z.md` and
`docs/RUNBOOK.md`. Do not add a new top-level file or directory to the user's project. Delivered
templates (guidelines, hook, checks, scenario skeleton) auto-update through `.telesma-manifest`;
user edits win.
