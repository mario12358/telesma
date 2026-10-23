# State files

Telesma keeps all of its state in plain files inside your project. This page lists them, then explains
the three mechanisms that keep them from growing without bound: rotation, the startup-prompt diet,
and the diagnosis with `--repair`.

- [Files in your project](#files-in-your-project)
- [State-file rotation](#state-file-rotation)
- [Startup-prompt diet](#startup-prompt-diet)
- [Diagnosis and `--repair`](#diagnosis-and---repair)

## Files in your project

### Specification (yours)

| File | Role | Written by |
|---|---|---|
| `telesma/spec/TECHNICAL_GUIDELINES.md` | Departures from the defaults in `telesma/guidelines/` (stack, hosting, integrations, non-functional requirements). Template copied on the first run; delete the `TELESMA_SPEC_TEMPLATE` marker once filled in. | You, before the start |
| `telesma/spec/*` | Business and functional requirements, use cases, domain model, diagrams — any format. Frozen after clarification. | You, before the start |
| `telesma/spec/ux_ui/` | Mockups, design tokens, reference components (CSS, HTML, JSX, TSX, images). Loaded fragment by fragment through `(ui-*:)` tags. Always created; empty is fine. | You, before the start |
| `telesma/spec/ux_ui/LINKS.md` | Registry of mockups kept outside the repository (`## <id> — Title` + `- link:`). Template created by the setup wizard when screenshots are turned on (or copy `templates/UX_LINKS_TEMPLATE.md` yourself). **Exempt from the freeze** — add links any time; Telesma indexes new entries at the next start. The link must be shared. | You, any time |
| `telesma/spec/APP_FLOW.md` | User flows (`## Step N — Title`), mapped 1:1 to e2e tests and recordings. Template created by the setup wizard when recordings are turned on; used only with `Recordings: yes`. | You, optional |
| `telesma/changes/` | Spec changes after clarification, one `.md` file per change. `telesma/changes/EXAMPLE.md` is an annotated sample and is never processed. | You, any time after clarification |
| `telesma/changes/processed/` | Applied changes, moved here by Telesma (audit trail in git). | Telesma |

### Telesma's working files (`telesma/`)

| File | Role | Written by |
|---|---|---|
| `telesma/config.md` | Configuration ([CONFIGURATION.md](CONFIGURATION.md)). | You (Telesma sets `Clarified`) |
| `telesma/state/SPEC_INDEX.md` | Two-level spec index with line ranges and anchors, documentation quality assessment, `## UX/UI guidelines` and `## Flows` tables, spec checksums. | Telesma, during clarification |
| `telesma/state/QUESTIONS.md` | Contradictions (`S`), assumptions (`A`), questions (`Q`), each with its source. | Telesma, during clarification |
| `telesma/state/PLAN.md` | Phases and tasks with checkboxes, dependencies, tags, acceptance criteria, `## Spec coverage`. | Telesma after clarification, or you |
| `telesma/state/PROJECT_CONTEXT.md` | Architecture, `## Key decisions`, `## Known problems and solutions`, `## Current state`. Survives compaction. | Telesma |
| `telesma/state/REPORT.md` | `## Summary`, `## Test status`, `## Task history`, `## Change history`, `## Visual artifacts`, `## Problem log`. | Telesma |
| `telesma/state/DECISIONS.md` | Append-only log of interactive exchanges after the loop ends. Never loaded into a prompt. | Telesma (section 10) |
| `telesma/state/BUGFIXES.md` | Append-only log of mode 2 fixes. Never loaded into a prompt. | Telesma (section 11) |
| `telesma/state/REVIEWS.md` | Append-only log of mode 3 reviews: scope, findings by severity, actions, verdict. Never loaded into a prompt. | Telesma (section 12) |
| `telesma/state/BACKLOG.md` | Topics for later — **read-write**; completed items older than 30 days move to `telesma/state/BACKLOG_DONE.md`. | Telesma + you (section 13) |
| `telesma/state/BLOCKED.md` | The last `TELESMA BLOCKED`, so it survives pipe mode. Shown and injected at the next start; deleted once resolved. | Telesma (section 5) |
| `telesma/state/WAITING.md` | The last `TELESMA WAITING` (GitHub integration: open-PR limit reached, nothing broken). Deleted after PR reconciliation. | Telesma (section 17) |
| `telesma/state/SPECKY.md` | Specky sync state: cursor, last sync date, requirement → task map. Committed. | Wizard, Telesma (section 18) |
| `telesma/state/TEST_SCENARIOS_TEMPLATE.md` | Skeleton for per-release manual test scenarios. Updated through the manifest; adapt it to your stack (your edits win). Read, never modified, by Telesma. | Launcher |
| `telesma/state/REPORT_ARCHIVE.md` | Older REPORT.md entries and whole ad-hoc sections. Write-only. | Launcher (rotation) |
| `telesma/state/CONTEXT_ARCHIVE.md` | Older rows of the two PROJECT_CONTEXT.md tables. Write-only. | Launcher (rotation) |
| `telesma/state/PLAN_ARCHIVE.md` | Fully completed phases beyond the last N, and intros of ad-hoc plan sections. Read only when a rework needs an archived task's text. | Launcher (rotation) |
| `telesma/state/SECURITY_MAP.md` | Attack-surface map for the `intent` and `red-team` checks: roles and their guards in code, ownership boundaries, routes, outbound hosts, secrets. Skeleton written at startup; rows added by Telesma with each new route. | Launcher, Telesma, you (review) |
| `telesma/state/CHECK_EXCEPTIONS.md` | Waived check findings, one fingerprint per line. Every write asks you. | You |
| `telesma/state/CHECKS.jsonl` | Log of check runs (never secret content). Machine data, in `.git/info/exclude`. | Checks hook |
| `telesma/state/PERMISSIONS.jsonl` | Log of permission-judge decisions with full commands. Stays on this machine; in `Ignore on commit`. | Judge hook |
| `telesma/state/.telesma-version` | The project's state-format version. Gates one-time migrations. Committed. | Launcher |
| `telesma/state/.telesma-manifest` | Template hash last delivered per file, so untouched files update automatically and edited ones are never overwritten. | Launcher |

### Other files

| File | Role | Written by |
|---|---|---|
| `telesma/guidelines/` | Technology guidelines loaded per task through `(tech:)` tags. Your edits win. | Launcher copies; you edit |
| `telesma/checks/` | Quality check modules and runner (with `## Checks` → `Enabled: yes`). Committed, so CI can run them. Writes ask you. | Launcher copies; you edit |
| `.git/telesma-checks/<sha>.json` | Evidence that the `commit`-point checks passed for a commit — the source of the PR status. Inside `.git/`, nothing to commit. | Checks hook |
| `telesma/artifacts/` | `screens/<id>.png` and `flows/step-<N>-<slug>.<ext>`. In `.gitignore` by default. | Telesma (opt-in) |
| `docs/test-scenarios/vX.Y.Z.md` | Manual test scenarios per release — only what automated tests could not check. Committed before the tag. | Telesma; you mark results |
| `docs/RUNBOOK.md` | How to run the project: env vars, dev/test/build commands, seeding, ports. | Telesma, at `TELESMA COMPLETE` |
| `.github/workflows/specky-ci.yml` | CI template carrying the Specky contract (with both integrations). | Wizard copies; Telesma adapts |
| `.claude/settings.local.json` | Synced from `config.md`: permissions, working directories, hooks, commit `attribution`. Your own keys are kept. | Launcher |
| `.claude/hooks/telesma-permission-judge.py` | The permission judge hook (opt-in). Updated through the manifest. | Launcher |

## State-file rotation

`telesma/state/PLAN.md`, `telesma/state/REPORT.md` and `telesma/state/PROJECT_CONTEXT.md` go **in full** into the startup
prompt of every session, and they grow linearly with the project. On a year-old project that was
~400k tokens before the first task started. At every start the launcher moves older entries into
`telesma/state/*_ARCHIVE.md` — deterministically, without calling a model, before the prompt is assembled.

| File | What stays | The rest goes to |
|---|---|---|
| `REPORT.md` | 10 Task history entries, 10 Problem log entries, 10 `###` Change history entries, the 3 latest runs in `## Test status`, 3 ad-hoc `## …` sections, 3 newest dated Summary bullets | `REPORT_ARCHIVE.md` |
| `PROJECT_CONTEXT.md` | The latest 40 `Key decisions` rows and 30 `Known problems and solutions` rows, plus **every** row marked 📌 | `CONTEXT_ARCHIVE.md` |
| `PLAN.md` | Phases with open tasks + the N latest completed ones (`Plan phases in file`, default 5) | `PLAN_ARCHIVE.md` |

Two kinds of REPORT.md sections, and the distinction is the whole point:

- **Current state** (`## Summary`, the metrics table in `## Test status`) — Claude overwrites it.
  Growth there means a session note was appended where it should not be; only the 3 newest dated
  Summary bullets are kept (the template's own `Start`, `Status`, `Progress` fields are pinned).
- **Chronicle** (test-run paragraphs, Task history, Problem log, Change history, ad-hoc sections) —
  append-only, so rotation keeps the newest N.

Rules worth knowing:

- **Nothing is lost.** Archives are ordinary files in the repository, just write-only: Telesma does not
  read them and they go into no prompt. Git has the full history.
- **An entry is a block, never a line.** A problem-log entry runs to the next `[date]` opener; a
  `### Phase …` history subsection goes whole, with its table and prose. Rotation never cuts an
  entry in half.
- **Order is by date, not by position.** Claude sometimes appends at the bottom and sometimes inserts
  at the top; "keep the last N" counted by position would archive the newest. A block without any
  date cannot be judged — it stays, but uses one slot of the budget, so the section stays bounded.
- **Test-run paragraphs** need a date in their bold opening line
  (`**Regression after Phase 12 (2026-08-20) — GREEN:** …`). A dateless paragraph is treated as the
  continuation of the run above it.
- **Ad-hoc sections** are any `## ` section whose title is not in the template.
- **Pin what still binds.** Mark a still-binding decision or a recurring pitfall with 📌 and it never
  rotates. A pitfall that comes back despite being written down should get a mechanical guard (a
  test, lint rule or check) — the row then says `→ guard: <name>`; 📌 is for what cannot be checked
  mechanically.
- **The plan archives only above 100 KB** (small projects get zero git churn) and only phases
  completed 100%. The plan keeps a stub `### Phase N: … — ✅ completed` with a
  `<!-- telesma-archived: … -->` list of task ids, so `(requires: X.Y)` on an archived task still
  resolves.
- **Intros of ad-hoc plan sections** (a `## Requests from <date> — …` header with prose, with phases
  hung underneath) are archived on their own — the header line to the first `### Phase` — and
  replaced with `> 📦 Request notes → telesma/state/PLAN_ARCHIVE.md`. Never the whole section: live phases
  sit under those headers, and a section holding any `- [ ]` is not touched. Titles starting with
  `Variant` are template blocks and exempt.
- **Commit the archives.** Rotation dirties the working tree at startup, and a dirty tree blocks
  release tagging, so Telesma adds `telesma/state/*_ARCHIVE.md` to the session's first commit.
- **A legacy `## Files created/modified` section** in old reports is archived whole — git knows the
  file list better.
- **Switches:** `Rotate state files: no` turns everything off; `Plan phases in file: none` leaves
  PLAN.md alone.

Rotation is half of the story; the other half is not growing in the first place. Task lines are
capped at **400 characters**: the plan says *what* is to be done, and rationale or notes from the work
belong in REPORT.md or PROJECT_CONTEXT.md, which rotate.

## Startup-prompt diet

Even after rotation, a large share of the startup prompt did not serve picking and doing the next
task: on the reference project it was 425k characters (~105k tokens), and every turn of a session
carries it again. The launcher trims it — **in the prompt copy only**; files on disk are untouched:

- Completed phases (collapsed or archived) become one line of ids at the end of the plan — enough for
  `(requires: X.Y)`; a title is one Grep away. The `telesma-archived` id lists are stripped (they are
  for the validator, not for Claude).
- A non-template `## ` plan section with no phase and no `- [ ]` left is dropped.
- `config.md` loses its `<!-- -->` comments.
- Rows of the two PROJECT_CONTEXT.md tables are cut at 400 characters with a pointer to the file;
  `## Current state` is cut at 2 KB.
- Ad-hoc `Change history` sections in REPORT.md are reduced to their header — their text lives in
  `telesma/changes/processed/`, which Telesma reads for `(change:)` tasks anyway.

Measured on the reference project: 425k → 286k characters. The diagnosis below flags table rows over
400 characters, so Claude shortens them at the source — what the model does not do consistently,
the script enforces.

## Diagnosis and `--repair`

The plan validator checks the plan and the config validator checks the config, but nothing used to
measure the state files themselves — which is how a project could grow to 550 KB of prompt before
anyone looked. `tools/telesma-repair.py` fills that gap.

### Diagnosis (every start)

Pure file reads, no git, silent when there is nothing to report. It flags:

- orphaned paragraphs in `## Problem log` and phase subsections whose table lost its rows;
- unfinished `- [ ]` tasks sitting in `PLAN_ARCHIVE.md`;
- task lines over 400 characters and checkbox items that are not tasks (no `Task`/`Test` keyword);
- a duplicated legacy `## Known pitfalls` section, an oversized `## Current state`, table rows over
  400 characters;
- files past their size threshold.

Findings come in two severities: **`damage`** (repairable, shown in red, with the repair hint) and
**`notice`** (worth knowing, yellow).

### Repair

```bash
telesma.sh --repair /path/to/project
```

Repairs and exits without starting Claude. It is a separate flag rather than a startup step because
it reads the **entire** git history of `telesma/state/REPORT.md` (seconds on a large project) and rewrites
files — a deliberate act, not a side effect of starting work.

The source of truth is git, with one rule per kind of entry:

- A **problem-log entry** is restored from the commit that first introduced it (entries are written
  once).
- A **task-history subsection** is restored additively from its longest version ever — missing rows
  are inserted, nothing is removed.
- Orphaned text is deleted from REPORT.md only after it is verified present in the archive.
- **A phase archived with unfinished work** (possible with older versions, which did not count a `⛔`
  task) goes back into the plan: the archived block replaces its stub. A stub someone has since
  edited is reported instead of guessed at.
- **A `- [x]` item without `Task`/`Test`** is a realization note wearing a checkbox. It moves to
  `## Task history` under its phase, dated with `git log -S` on the line.
- **A task line over 400 characters**: a trailing `<!-- … -->` note moves to `PLAN_ARCHIVE.md`
  (text unchanged), and what is still too long is broken into indented continuation lines, with the
  tags kept on the task line.
- A `- [ ]` item that is not a task stays for you to decide — it is either a forgotten task or a
  BACKLOG entry, and only a person can say which.

Guarantees: repair never deletes what git does not know about, and a second run changes nothing.
It opens exactly four files — `REPORT.md`, `REPORT_ARCHIVE.md`, `PLAN.md`, `PLAN_ARCHIVE.md`.
`DECISIONS.md`, `BACKLOG.md`, `BUGFIXES.md`, `REVIEWS.md`, `PROJECT_CONTEXT.md`, `CONTEXT_ARCHIVE.md`,
`config.md`, `SPEC_INDEX.md`, `telesma/changes/` and `telesma/spec/` are outside its reach by construction.

Running the tool directly:

```bash
python3 tools/telesma-repair.py /path/to/project          # diagnosis only
python3 tools/telesma-repair.py /path/to/project --fix    # repair
```
