# Adopting an existing project — design proposal

**Status: proposal, not implemented** (written 2026-11-03). Nothing described here exists in the
launcher yet; the section numbers, file names and flags are the proposed ones. When it ships, the
reasoning moves into `ARCHITECTURE.md` and the user-facing part into `WORKFLOW.md`.

## The problem

Telesma starts from a specification and an empty directory. A project that already exists — built
by hand, or with an AI assistant used the ordinary way (Claude Code, Codex, Cursor) — has neither
`telesma/spec/` nor any of the state files. The worry is obvious: Telesma would not know the
project's history, the stages it went through or the decisions taken along the way, and would make
poorly informed choices when the next features are discussed and planned.

The question this document answers: **what do we reconstruct, and from where** — the commit and
pull-request history, or the code itself?

## What Telesma actually knows about its own projects

Before deciding what to rebuild, look at what the loop reads in a session (`ARCHITECTURE.md` §1,
§8, §9):

- `PLAN.md` with **completed phases collapsed to their ids** in the prompt copy;
- `PROJECT_CONTEXT.md` in full — tech stack, architecture, key decisions (📌 rows never rotate),
  known problems, component dependencies, current state;
- `REPORT.md` after rotation — the three latest test runs; task history and the problem log rotate
  to `REPORT_ARCHIVE.md`;
- `SPEC_INDEX.md` and `config.md`;
- on demand: a spec fragment by its anchor, a guideline file per `(tech:)` tag, and `git log` /
  `git log -S` / `git blame` — the same source `tools/telesma-repair.py` treats as the truth.

`REPORT_ARCHIVE.md`, `DECISIONS.md`, `BUGFIXES.md` and `REVIEWS.md` are write-only. After a few
phases a project built by Telesma looks to the model exactly like a project built by someone else:
**the code, git, and a distillate.** The distillate is `PROJECT_CONTEXT.md` plus the spec behind
its index. This is by design (the prompt diet), not a gap.

Three consequences:

1. **Rebuilding a task history from commits is pointless.** Nothing reads it; it cannot be verified
   (no acceptance criteria, no test that belongs to the task); commits from AI-assisted projects
   are typically "wip", "fix", "more fixes"; and in telemetry it would pass for Telesma's own work.
2. **What an adopted project lacks is the distillate and a baseline**: a specification of the
   system as it stands (the loop is spec-driven — `(spec:)` tags, `- AC:` lines and clarification
   questions all cite the spec), a filled `PROJECT_CONTEXT.md`, and a recorded baseline of tests and
   check findings, without which the loop cannot tell a regression from the state it inherited.
3. **Code is the truth about *what*; git is the only source of *why*.** So the code is read to
   write the as-built spec, and git is mined — cheaply, by a script — for decisions and pitfalls.

## What is filled from where

| Telesma file | Source | Who |
|---|---|---|
| `telesma/spec/AS_BUILT.md` (new): what the system does today, per module, as `When …, then …` lines like the interview's `REQUIREMENTS.md`, each with an evidence pointer `file:lines` and a confidence label *verified by test* / *inferred* | the code — tests first (test names are behaviours), routes (`templates/checks/_routes.py` already extracts them), public APIs and types, manifests, README and `docs/` | model, top-down, one module at a time |
| `telesma/spec/TECHNICAL_GUIDELINES.md`: the stack and conventions **as found**, not the defaults | manifests, `CLAUDE.md` / `AGENTS.md` / `.cursorrules`, linter and formatter configs, the code's style | `configure.py detect` (exists) + model |
| `PROJECT_CONTEXT.md` → Key decisions 📌 | ADRs, CHANGELOG, PR descriptions, commits that migrate / replace / switch a dependency, dependency changes in lockfiles | script digest + model |
| `PROJECT_CONTEXT.md` → Known problems | **reverts**, files with a high density of "fix" commits (churn), `TODO` / `FIXME` / `HACK`, flaky or skipped tests | script digest + model |
| `REPORT.md` → Test status | a real run of the full suite | launcher, zero tokens |
| `REPORT.md` → Task history | **one** entry: "Phase 0: existing system up to `<sha>`, tag `<tag>`" | launcher |
| `PLAN.md` → `### Phase 0: Existing system — ✅ completed` | one completed task per module of `AS_BUILT.md`, so that `(requires: 0.N)` and `## Spec coverage` have something to point at; collapsed in the prompt anyway | model, during the survey |
| `QUESTIONS.md` → `### A…` assumptions | everything the code does not explain: "I assume `auth_v1/` is dead — no caller since 2025", "I assume feature flag X is off in production" | model; a human confirms in minutes what would cost the model hours of certainty |
| `CHECK_EXCEPTIONS.md` → proposals | the checks run once, dry, on the old repository | script; the human decides (exceptions are the human's — an invariant) |

## The flow: `telesma.sh --adopt /path/to/project`

1. **Launcher, deterministic.** Preflight. Refuse without git, with a dirty tree, or off the main
   branch. Create `telesma/` with `config.md` carrying `Adopted: yes` and `Adopted at: <sha> <date>`.
   The setup wizard with stack detection (exists). **Run the full suite** and write the baseline
   into `REPORT.md`. A new stdlib tool, `tools/telesma-survey.py`, computes from `git log`: the tag
   timeline and its scheme (`v1.2.3` or `1.2.3`), reverts, churn per directory, fix density per
   file, big-bang commits, dependency changes, the presence of ADRs / CHANGELOG / `CLAUDE.md`, the
   ratio of test files to source files. The result is a `SURVEY:` block in the startup prompt (like
   `VERSIONS:` today): a few dozen lines instead of a raw `git log`. The checks run once dry and
   produce a list for the human. `PLAN.md` gets a skeleton `### Phase 0: Existing system` with one
   `- [ ] Task 0.N: Survey <module>` per detected part (monorepo parts from `configure.py` plus the
   top-level directories under `src/` or equivalent).
2. **The survey session** (new instruction file `templates/instructions/SURVEY.md`, section -3).
   It is **the ordinary Telesma loop** over Phase 0: a task = read the module (tests, public API,
   routes, types; sampling, never everything), append a section to `AS_BUILT.md`, rows to
   `PROJECT_CONTEXT.md`, assumptions to `QUESTIONS.md`, tick the box, commit. This gives `/compact`,
   resumption after an interruption and a budget for free: the human strikes the tasks of modules
   they do not care about. Permissions: read the code, write only inside `telesma/`. It ends with
   `TELESMA: SURVEY DONE` and reads a summary back to the person, as the interview does in -2.5.
3. **The human** confirms the assumptions, corrects `AS_BUILT.md` where the model guessed wrong,
   and puts into `telesma/spec/` **what should happen next** (for `Experience: beginner`: a variant
   of the interview with one question, "what do you want to change?").
4. **Clarification, unchanged**, indexes all of `telesma/spec/` (`AS_BUILT.md` included), produces
   S/A/Q and the plan from Phase 1. One branch in `CLARIFY.md` for `Adopted: yes`: no "architecture
   skeleton" task 1.1; instead, when the test baseline is weak, a proposed assumption "Phase 1:
   safety net — characterisation tests for X, Y"; `## Spec coverage` rows for `AS_BUILT.md`
   sections read "exists — 0.N".
5. Modes 1–4 work unchanged. **Modes 2 (bugfix) and 3 (review) are useful right after step 2**:
   they need only the context and the index, not a plan. That is the first tangible value of an
   adoption, before any new plan exists.

## Hard spots

- **A large codebase.** The survey does not read everything: tree → manifests → entry points →
  tests → routes / API → samples. Every statement in `AS_BUILT.md` carries a confidence label so
  that clarification knows what to ask about.
- **Red or absent tests.** The baseline records the set of tests that fail "since forever"; the
  loop compares against the baseline, not against zero. No tests means Telesma cannot detect
  regressions; the survey says so plainly and proposes a characterisation-test phase as an
  assumption to accept or reject.
- **Project conventions vs `telesma/guidelines/`.** The conventions found win. The slot exists
  already — "departures from the defaults" in `TECHNICAL_GUIDELINES.md`; `general.md` gets one
  sentence about precedence.
- **The project's `CLAUDE.md`.** A Telesma session is Claude Code, so it loads by itself. The
  survey absorbs it into the conventions instead of duplicating it; a conflict between its
  instructions and Telesma's must be tried on a live project.
- **Checks on an old repository.** Hygiene and secrets light up on the first commit (big files,
  floating versions, keys in the history). Hence the dry run in step 1 and the human's decision
  before the first task.
- **Release tags.** `VERSIONS:` looks for `v*`; an adopted project may use another scheme. The
  survey records the scheme found; the launcher honours it.

## Scope of the change

`--adopt` in the launcher; `tools/telesma-survey.py` with a self-test; `templates/instructions/SURVEY.md`;
an `Adopted` field in `config.md`; the branch in `CLARIFY.md` (Phase 0, no skeleton task, coverage
"exists"); the plan validator (a Phase 0 completed from the start is legal); `AS_BUILT_TEMPLATE.md`;
telemetry with an adoption flag (so the benchmark does not mix greenfield and adopted projects);
a `TELESMA_FORMAT` bump; `ARCHITECTURE.md` §21.

The order that yields value earliest: (1) launcher + `telesma-survey.py` + the test and check
baseline, (2) `SURVEY.md` and the Phase 0 loop, (3) the clarification branch, (4) the "what next"
interview variant for beginners.

## Open decisions

1. **Name and boundary of the mode**: `--adopt` as a separate start (recommended — a visible
   threshold and preconditions different from `--new`), or automatic detection of "code present, no
   `telesma/`" on an ordinary start?
2. **The survey as an autonomous loop over Phase 0** (recommended — resumption and `/compact` for
   free, the human strikes modules), or one interactive session like the interview (simpler, but it
   falls over on a large codebase)?
