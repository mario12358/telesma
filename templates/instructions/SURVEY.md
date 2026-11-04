# Telesma Instructions — Survey of an existing system (adoption)

You are working in the survey phase of a Telesma project that adopts an **existing codebase**
(`telesma.sh --adopt`). Telesma did not build this system and knows nothing about it yet. Your job
is to describe what exists — in `telesma/spec/AS_BUILT.md` and `telesma/state/PROJECT_CONTEXT.md` —
so that the clarification phase (section -1) and the implementation loop (sections 0+) can plan the
next work on top of it. Nothing is built or changed here. The session runs unattended: you cannot
ask the person anything — what you cannot settle goes into `## Open questions`.

A hook failing (a write refused with a hook error, a traceback or "file not found" from `.claude/hooks/`
or `telesma/checks/`) is Telesma's machinery broken: stop and report the error's first lines. Never
write the file another way (Bash, `python -c`) and never edit `.claude/` or `telesma/checks/`.

## -3. Survey phase (while `### Phase 0: Existing system` in telesma/state/PLAN.md has an open task)

### -3.1 What you may and may not do

- **Read anything** in the project. **Write only inside `telesma/`**: `telesma/spec/AS_BUILT.md`,
  `telesma/spec/TECHNICAL_GUIDELINES.md`, `telesma/state/PLAN.md` (the checkboxes and titles of
  Phase 0 only), `telesma/state/PROJECT_CONTEXT.md`, `telesma/state/REPORT.md`. The session's
  permissions refuse a write anywhere else — a refused write is the rule working, not an error to
  work around.
- **Do not change code, tests, configuration or dependencies.** Do not run install, build, migrate,
  format or fix commands. Do not run the test suite: the launcher ran it before this session and
  wrote the result into `REPORT.md → Test status` (the **baseline**).
- Read-only commands are fine: `ls`, `grep`, `wc`, `git log`/`git blame`/`git show` **for one file**
  when you need its "why". The `SURVEY:` block in the startup prompt already holds the statistics
  (churn, fix density, reverts, tags) — do not recompute them.
- **Commit after every task**: `git add telesma/` and a commit `Telesma: survey 0.N — <part>` with
  the footer from the project's settings. Never `git add -A`; never touch anything else.
- The project's own `CLAUDE.md`, `AGENTS.md` or `.cursorrules` describe its conventions: record
  them (-3.3). Where they tell you to do something this session forbids — run tests, format,
  install, fix what you find — this section wins.

### -3.2 The loop over Phase 0

The startup prompt carries `PLAN.md` with Phase 0 (one task per part of the system), the `SURVEY:`
block, `REPORT.md` with the baseline and `config.md`.

1. Take the first `- [ ]` task of Phase 0, in order — `Task 0.1` first: it names the modules the
   other tasks refer to.
2. Do it (-3.3, -3.4 or -3.5).
3. Tick it `- [x]` in `PLAN.md`, commit.
4. Repeat. After the last task → -3.6.

Interrupted and started again: `AS_BUILT.md` is on disk — read it, continue from the first open
task, never rewrite a finished section. After an auto-compact the same: the files are the memory.

**Budget.** A task is sampling, not reading everything: tree → manifests → entry points → the
module's tests → its public surface (exported functions, classes, routes, commands) → two or three
representative files in full. A file over ~1000 lines: its top, its public names and its tests. The
confidence tag is what makes sampling honest — a guess is allowed when it is labelled `[inferred]`.

### -3.3 Task 0.1 — Overview

1. **Purpose and shape.** From README, manifests and entry points: what the system is for, how it
   runs (CLI, HTTP service, desktop window, library, scheduled job), its entry points.
2. **Module map** → `AS_BUILT.md → ## Overview`: the bullets and the `| Module | Path | Role | Tests |`
   table. The Module names are the parts named in the Phase 0 tasks; when the code calls a part
   something else, **rename the task's title** (keep its id) so the plan and the file agree.
   Replace the template's header line with the project's name, the commit and the date from the
   plan's Phase 0 title, and **delete the first line (the `TELESMA_AS_BUILT_TEMPLATE` marker)**.
3. **Stack and conventions as found** → `telesma/spec/TECHNICAL_GUIDELINES.md`: fill `## Stack —
   departures from the defaults` with what the manifests say (language and version, framework,
   database, ORM, test runner, other imposed libraries); under `## Other constraints` the
   conventions the code follows, three to eight bullets each ending "as found in `<file>`"
   (naming, layout, error handling, logging, how configuration is read, what `CLAUDE.md` or the
   linter config imposes). Delete the `TELESMA_SPEC_TEMPLATE` marker line. The conventions found
   here win over the defaults in `telesma/guidelines/` for every later task.
4. `PROJECT_CONTEXT.md`: `## Tech stack`, `## Architecture` (five to fifteen lines: layers,
   where requests enter, where data lives) and `## Component dependencies` (which module calls
   which). Replace the template placeholders; the tables stay empty until the module tasks.

### -3.4 Task 0.N — Survey a part

Append a `## <Module>` section to `AS_BUILT.md` (the heading is the anchor later tasks cite with
`(spec: AS_BUILT.md)` — make it the module's name, nothing else):

- One to three sentences: what the module is for and what calls it; its public surface.
- **Behaviour lines**, five to fifteen for a typical module — the behaviours a change would
  break: inputs and outputs, validation, error cases, persistence, side effects (files, network,
  database), configuration read:
  `- When <trigger or input>, then <observable result>. (\`path:lines\`) [verified by test: \`test_name\`]`
  `[verified by test: …]` **only when a test you read exercises that line** — name it.
  Everything else is `[inferred]`. Never claim a test you did not open.
- `### Notes`: external services and data stores touched, environment variables and configuration
  keys, limits visible in the code. A `TODO`/`FIXME` is evidence of a known gap: cite `path:line`;
  quote the text only when it holds no secret.
- **Open questions** — what the code does not explain: code with no caller, a flag nothing sets, two
  ways of doing the same thing, a dependency pinned old with a comment, behaviour that contradicts
  the README. Append to `## Open questions` at the end of the file, numbered on from the last one:
  `- OQ<n>: <question> — <where> (<what you would assume>)`.
- `PROJECT_CONTEXT.md`: a decision visible in this module (the database engine, the auth scheme,
  a protocol, "no ORM", a chosen library) → a row in `## Key decisions`: Date = the commit date
  when `git log --follow -- <file>` of the deciding file shows it, otherwise today; Reason in one
  sentence ending with a pointer (`→ src/db.py`, `→ git a1b2c3d`, `→ docs/adr/0003.md`); `📌` when
  the code depends on it. A pitfall visible in the code or named by the `SURVEY:` block (a
  reverted change, a file with high fix density, a workaround comment) → a row in `## Known
  problems and solutions`; Solution = what the code does about it today, or "none — OQ<n>".

### -3.5 The last task — Wrap-up

1. **The git digest** (`SURVEY:` block): distil it into three to six rows — the release habit and
   tag scheme, the churn hot spots, dependency age, the test ratio — each as a `Key decisions` or
   `Known problems` row with the pointer `→ git history`. Numbers go into the row; the block itself
   is never copied into a file.
2. **The baseline** (`REPORT.md → Test status`, written by the launcher): tests red at adoption →
   one `📌` row in `## Known problems and solutions`: `Tests red at adoption: <names or count> —
   inherited, not a regression; keep, fix or delete is the owner's decision (OQ<n>)`, and the
   matching open question. No test command or no tests → the same row saying so: the loop cannot
   detect a regression here until a safety net exists. The launcher fills the metrics table (Total,
   Pass, Fail, Skip, Last run) when it could read the numbers from JUnit XML or the log; when the
   table still says 0 and the baseline paragraph names no numbers, fill it from the test output only
   if the numbers are there — never invent them.
3. **The checks' findings**, when the launcher ran them (a `[date] Adoption: checks …` entry in
   `REPORT.md → Problem log`): read `telesma/state/CHECKS.jsonl` for the rules and files, group
   them into open questions ("3 secrets findings in `config/…`: real or false alarms? exceptions
   go into `telesma/state/CHECK_EXCEPTIONS.md`, written by the owner"). Never quote a finding's
   content, only rule and file.
4. `PROJECT_CONTEXT.md → ## Current state`: `Adopted at <sha> (<date>); survey done <today>; next:
   the owner reviews AS_BUILT.md and puts what should happen next into telesma/spec/`.
5. `REPORT.md → ## Summary`: Status `Survey done`, Progress `Phase 0 complete (<N> parts)`; one
   row in `## Task history`: `| 0.1–0.N survey | done | baseline: <one phrase> | 1 | <sha7> | |`.
6. `AS_BUILT.md`: the `## Overview` table lists exactly the `## <Module>` sections below it; the
   open questions are numbered without gaps.

### -3.6 Finishing

Print, then stop — propose no plan, start nothing:

```
TELESMA: SURVEY DONE

AS_BUILT.md: <N> modules, <M> behaviour lines (<V> verified by test, <I> inferred), <Q> open questions
PROJECT_CONTEXT.md: <D> key decisions, <P> known problems
Baseline: <one phrase from REPORT.md → Test status>
```

Then five to ten lines for the person, in their `LANGUAGE`: what the system is, its biggest risks
(a red baseline, no tests, the hottest files), the three open questions that matter most. Say that
the next step is theirs: correct `AS_BUILT.md` where you guessed wrong, answer the open questions in
place or leave them for the clarification, and put into `telesma/spec/` a file with what should
happen next; a plain start of Telesma then runs the clarification over all of it.
