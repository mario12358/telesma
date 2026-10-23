# How Telesma works

This page describes Telesma from the user's side: what happens in each phase, how to write a plan,
how to feed changes in, and what each mode does. Configuration keys are listed in
[CONFIGURATION.md](CONFIGURATION.md); the files Telesma creates in your project in
[STATE_FILES.md](STATE_FILES.md).

Section numbers such as "section 0.3" refer to the instruction modules in
`templates/instructions/`, which the launcher assembles into the startup prompt.

- [1. Clarification](#1-clarification)
- [2. The plan](#2-the-plan)
- [3. Writing a good plan](#3-writing-a-good-plan)
- [4. Selective spec retrieval](#4-selective-spec-retrieval)
- [5. Technology guidelines](#5-technology-guidelines)
- [6. UX/UI assets](#6-uxui-assets)
- [7. Visual artifacts](#7-visual-artifacts)
- [8. Changes after clarification](#8-changes-after-clarification)
- [9. Multi-client projects (BFF)](#9-multi-client-projects-bff)
- [10. E2E tasks at the end of a phase](#10-e2e-tasks-at-the-end-of-a-phase)
- [11. Interactive mode and DECISIONS.md](#11-interactive-mode-and-decisionsmd)
- [12. Mode 2 — bugfix](#12-mode-2--bugfix)
- [13. Mode 3 — code review](#13-mode-3--code-review)
- [14. Mode 4 — artifacts](#14-mode-4--artifacts)
- [15. BACKLOG](#15-backlog)
- [16. Releases and manual test scenarios](#16-releases-and-manual-test-scenarios)
- [17. Resuming a session](#17-resuming-a-session)
- [18. Monitoring progress](#18-monitoring-progress)

## 1. Clarification

Clarification runs while `Clarified: no` in `telesma/config.md`. It is always interactive — if you
start without `-i`, the launcher adds it.

```bash
telesma.sh /path/to/project -i
```

Telesma:

1. Reads every file in `telesma/spec/`. Binary documents (`.docx`, `.pdf`, `.odt`, `.rtf`) are converted
   automatically when `pandoc` is installed.
2. Writes `telesma/state/SPEC_INDEX.md` — a two-level index: for each document a short description, a table
   of sections with exact line ranges, an **anchor** (the exact heading that opens the section) and
   a description, plus keywords. It also contains a **documentation quality assessment**:
   completeness in percent, unambiguity, consistency, project size, topic gaps and a
   recommendation. That assessment drives how many questions follow.
3. Writes `telesma/state/QUESTIONS.md` with three sections:
   - **Contradictions** (`### S…`) — explicit conflicts in the spec, quoting both sources, with a
     proposed resolution. These are resolved first.
   - **Assumptions** (`### A…`) — things Telesma decided without asking (industry standards, stack
     conventions), listed for a quick spot-check. This keeps the question count down.
   - **Questions** (`### Q…`) — only what cannot reasonably be assumed. The count is **adaptive**:
     roughly 3–7 for a small project with a good spec, 15–30 or more for a large or thin one. Every
     question has a **Source** field pointing at the place in the spec that raised it.
4. Walks you through them in order: contradictions → assumptions → questions. You can stop at any
   time (Ctrl+C) and resume later; ENTER accepts the proposed answer.
5. Writes `telesma/state/PLAN.md` from four sources of knowledge: the spec, the resolved contradictions, the
   accepted assumptions and your answers. The launcher first tries `claude --continue` on the
   indexing session — it already has the whole spec in context, which is cheaper and gives a better
   plan; if no plan appears, it retries with a fresh session and the full clarification prompt.
   The plan contains task 1.1 "architecture skeleton", acceptance criteria (`- AC:`) on non-trivial
   tasks, a `## Spec coverage` section (every SPEC_INDEX section → tasks, or "out of scope — reason")
   and passes a self-review checklist.
6. Sets `Clarified: yes`.

After indexing, the launcher stamps checksums of the spec files into SPEC_INDEX
(`TELESMA_SPEC_CHECKSUMS`). On later starts, a changed spec file prints a warning in the terminal and
an annotation in the prompt that forces anchor verification.

## 2. The plan

`telesma/state/PLAN.md` is a list of phases (`### Phase N: Title`) with checkbox tasks. Every item must start
with `Task` or `Test` — an item without that keyword is invisible to the loop.

```markdown
### Phase 2: Authentication

- [ ] Task 2.1: Endpoint POST /api/auth/register with email validation (requires: 1.1) (spec: api-spec.md) (tech: python)
  - AC: a duplicate email returns 409 with the standard error body
  - AC: entry — "Sign up" form on the landing page submits to this endpoint
- [ ] Test 2.1: registration covers both AC criteria (requires: 2.1)
```

### Tags

| Tag | Example | Meaning |
|---|---|---|
| `(requires: X.Y, …)` | `(requires: 1.1, 1.3)` | Dependencies. A task whose dependencies are not done is skipped; the next available one is chosen. |
| `(spec: file, …)` | `(spec: api-spec.md, auth.md)` | Which spec documents define the task. Only their relevant fragments are loaded. |
| `(tech: tag, …)` | `(tech: react, typescript)` | Which guideline files apply. A tag without a file in `telesma/guidelines/` → `TELESMA BLOCKED`. |
| `(ui-tokens: file)` | `(ui-tokens: telesma/spec/ux_ui/tokens.css)` | Copy design tokens 1:1 into the project. |
| `(ui-component: file#A,B)` | `(ui-component: telesma/spec/ux_ui/primitives.jsx#Icon,Avatar)` | Rewrite each reference component into the production stack. |
| `(ui-screen: file#Id)` | `(ui-screen: telesma/spec/ux_ui/screens.jsx#B1_ProjectOverview)` | Implement one screen from its mockup fragment. |
| `(screen: id)` | `(screen: B1_ProjectOverview)` | Capture `telesma/artifacts/screens/<id>.png` after the task (when screenshots are on). |
| `(flow: file#step-N)` | `(flow: telesma/spec/APP_FLOW.md#step-1)` | Record step N of a user flow on an e2e task (when recordings are on). |
| `(change: file.md)` | `(change: 2026-04-23-mx-check.md)` | The task was modified by a change file; Telesma reads it from `telesma/changes/processed/`. |
| `(pr: #n)` | `(pr: #42)` | GitHub integration: the task's PR is open; the task is done after merge. |

### Acceptance criteria

- `- AC: <criterion>` lines go **under** the task, not on its line. Every criterion needs a test that
  checks it; green tests that do not touch the criteria do not finish the task.
- `- AC: entry — <trigger>` names what triggers a new mechanism in the running product: a user step
  ("click »Export« in dialog X"), an event, a schedule, or an external call. At least one test must
  reach the mechanism **through that entry**, not by calling the service directly. If no entry can
  be named, the plan is missing a sibling task that builds it. When a mechanism acts in N places,
  the criterion lists all N by name.

The reason: the most expensive defect class an autonomous loop produces is code that was built,
tested, and wired to nothing. A 30-second check — disable the call at the wiring point and see
whether any test goes red — exposes it (the mutation procedure lives in `telesma/guidelines/general.md`).

### Markers

- `⛔` before a task means "waiting for a human" (a manual production test, the owner's decision). It
  counts toward phase completeness, but the next-task hint skips it unless nothing else is left.
- A `### Phase N: … — ✅ completed` header with a `<!-- telesma-archived: … -->` comment is the stub of
  a phase moved to `telesma/state/PLAN_ARCHIVE.md`. Do not edit it — dependencies on its tasks still resolve.

### Validation before the start

Before mode 1 starts, the launcher validates the plan without spending tokens: the dependency graph
(missing ids, cycles, duplicate ids), `(tech:)` tags against `telesma/guidelines/`, `(spec:)` /
`(ui-*:)` / `(flow:)` tags against files. Errors are shown in the terminal and you confirm whether to
continue. It also computes a **next-task hint** (the first unblocked `- [ ]` in the active phases) so
the model verifies a pointer instead of scanning the plan, and collapses fully completed phases in
the prompt copy of the plan.

## 3. Writing a good plan

Good tasks:

```markdown
- [ ] Task 2.1: Create the User model with id, email, password_hash, created_at (spec: data-model.md) (tech: python, sql)
- [ ] Task 2.2: Endpoint POST /api/auth/register with email validation (requires: 2.1) (spec: api-spec.md, auth-requirements.md) (tech: python)
- [ ] Task 3.1: Copy the design tokens (ui-tokens: telesma/spec/ux_ui/tokens.css) (tech: react, typescript)
- [ ] Task 3.2: Primitives — Icon, Avatar, Badge (requires: 3.1) (ui-component: telesma/spec/ux_ui/components-primitives.jsx#Icon,Avatar,Badge) (tech: react, typescript)
- [ ] Task 3.3: Screen B1 Project Overview, uses TopBar, Avatar, Badge, ProjectCard (requires: 3.2) (ui-screen: telesma/spec/ux_ui/screens-b1-b2.jsx#B1_ProjectOverview) (spec: requirements.md) (tech: react, typescript)
- [ ] Task 3.4: E2E test — sign-up, login, logout (requires: 3.1, 3.2, 3.3) (spec: user-flows.md) (tech: playwright, typescript)
```

Bad tasks:

```markdown
- [ ] Task 4.1: Build the backend            (too broad)
- [ ] Task 4.2: Fix the bugs                 (undefined)
- [ ] Task 4.3: Optimise                     (no success criterion)
```

Guidelines:

- One task = one concrete change, with a stated expected result.
- Tasks in a logical order; a test right after the implementation it checks.
- Dependencies explicit through `(requires:)`, requirement sources through `(spec:)`, conventions
  through `(tech:)`.
- A task line stays under **400 characters**. The plan says *what* is to be done; rationale and
  findings belong in `telesma/state/REPORT.md` or `telesma/state/PROJECT_CONTEXT.md`, which rotate — the plan does not.

A complete example is in [`examples/example-plan.md`](../examples/example-plan.md).

## 4. Selective spec retrieval

Telesma never loads whole spec documents into context (section 0.1). Before a task it:

1. Reads the `(spec:)` tag → knows which file.
2. Looks the relevant section up in `telesma/state/SPEC_INDEX.md` → knows which lines.
3. Reads only that fragment (`Read` with offset and limit).
4. **Verifies the anchor**: the fragment must start with the heading recorded in the index. If it
   does not (the spec was edited after indexing), Telesma greps for the heading, reads from the right
   offset and fixes the index entry. Without this check a stale line range is a *silent* error —
   the task gets implemented from the neighbouring section.
5. Falls back to `Grep` over `telesma/spec/` by keyword.

A 2,450-line `api-spec.md` therefore costs a registration task only lines 46–180 ("Auth module").

## 5. Technology guidelines

`telesma/guidelines/` in your project holds convention files for languages and frameworks
(section 0.2).

1. The first run copies `templates/guidelines/` into `telesma/guidelines/`.
2. At every start the launcher builds a `GUIDELINES_INDEX` (tag + keywords from each file's
   frontmatter) and puts it in the prompt — without the full content.
3. When writing the plan, Claude matches `(tech:)` tags to tasks using that index.
4. Before each task Claude reads `telesma/guidelines/general.md` (always) plus one file per `(tech:)` tag.
5. A tag without a file → `TELESMA BLOCKED`. Telesma does not guess conventions.

File format:

```markdown
---
tag: react
keywords: react, hooks, jsx, tsx, component
---

# Guidelines: React
...
```

**Adding your own:** create `telesma/guidelines/<tag>.md` with `tag` and `keywords` in the frontmatter,
describe conventions, structure, tests and what to avoid, and start Telesma again — the tag appears in
the index.

**Editing:** edit freely. Your edits win: a file you changed is never overwritten. A file you did not
change is updated automatically when the template changes (tracked in `telesma/state/.telesma-manifest`); a
file you did change gets a one-time notice with a `diff` command instead.

**Conflicts:** a specific guideline (`python.md`) beats the general one; the spec beats a guideline,
but Claude asks first.

## 6. UX/UI assets

Mockups, design tokens and reference components (CSS, HTML, JSX, TSX, images) go into
`telesma/spec/ux_ui/` (section 0.4). The directory is always created; an empty one is fine. The files are
part of `telesma/spec/` — frozen after clarification — but they are loaded fragment by fragment: the
`## UX/UI guidelines` section of SPEC_INDEX lists each file with its type and a line range per
element, and each `#identifier` in a task tag resolves to one row.

| Tag | What Claude does |
|---|---|
| `(ui-tokens: …)` | Copies the file **1:1** into the project (e.g. `src/styles/tokens.css`) and wires it into the global styles. |
| `(ui-component: …#A,B)` | Loads each identifier's fragment and **rewrites** the component into the production stack (`src/components/<Name>.tsx`). |
| `(ui-screen: …#Id)` | Loads the screen's fragment and implements it with the components already in `src/components/`, reading *their* API rather than the prototype's. |

Rules:

- `.jsx` mockups are **prototypes** (Babel in the browser, global variables) — never copied 1:1.
  Only `tokens.css` is.
- Colours, spacing and typography use `var(--*)` from the tokens; no hard-coded hex or px where a
  token exists. Layout, hierarchy, states (hover/active/disabled) and interactions follow the mockup.
- **React Native**: CSS variables do not exist there; `react-native.md` tells Claude to transcribe
  the tokens into a `theme.ts` with a Context and to rewrite web JSX into `<View>`/`<Text>`/`<Pressable>`.

### Mockups as links (`telesma/spec/ux_ui/LINKS.md`)

Mockups kept outside the repository (for example Claude Design canvases) are registered as links in
`telesma/spec/ux_ui/LINKS.md`. One entry = `## <id> — Title` plus `- link:`, `- type:` and `- scope:`. Tasks
use the same grammar, with the registry as the file: `(ui-screen: telesma/spec/ux_ui/LINKS.md#<id>)`. Telesma
resolves the tag through the links table in SPEC_INDEX and fetches the content with WebFetch.

- The link must be **shared** (public or share link) — Telesma cannot fetch a private artifact. An
  unreachable link at task time is `TELESMA BLOCKED`; the launcher also checks reachability at every
  start (yellow warning).
- The registry is **exempt from the spec freeze**: add links whenever you like. The launcher detects
  entries not yet in SPEC_INDEX and tells Telesma to index them at the next start.
- The template marker `TELESMA_UX_LINKS_TEMPLATE` in the first line means "not filled in yet".
- Files and links can coexist.

## 7. Visual artifacts

An opt-in module that gives you **visual proof of what Telesma built** without starting the app
(section 0.5). Enable it in `## Visual artifacts`:

```markdown
- **Screenshots**: yes          # one PNG per screen, after tasks tagged (screen: <id>)
- **Recordings**: yes           # one video per flow step, on e2e tasks tagged (flow: <file>#step-<N>)
- **Flow files**: telesma/spec/APP_FLOW.md
- **Artifacts dir**: telesma/artifacts/
- **Commit artifacts**: no      # yes = telesma/artifacts/ goes into git (consider Git LFS for videos)
```

Both are off by default; enable either or both.

| Tag | When | What Claude does |
|---|---|---|
| `(screen: <id>)` | After the task's tests pass | Takes a screenshot in an existing test or a short dedicated spec and saves `telesma/artifacts/screens/<id>.png`. |
| `(flow: <file>#step-<N>)` | On the end-of-phase e2e task | Reads step N from the flow file (line range from `## Flows` in SPEC_INDEX), writes an e2e test that mirrors the prose, records it and saves `telesma/artifacts/flows/step-<N>-<slug>.webm` (Playwright) or `step-<N>-<slug>-<platform>.mp4` (Detox). |

**`telesma/spec/APP_FLOW.md`** is the source of truth for recordings. The setup wizard creates it from
the template when you turn recordings on (`telesma.sh --setup` → Visual artifacts). Each `## Step N — Title` heading is one e2e scenario and one recording (a 1:1 mapping). Write
each step as prose from the user's point of view ("The user clicks X. The system shows Y.") — Claude
turns it into actions and assertions.

Rules and edge cases:

- **No APP_FLOW.md despite `Recordings: yes`**, or an unfilled template (marker
  `TELESMA_APP_FLOW_TEMPLATE` in the first line) → a note in REPORT.md, not a blocker.
- **Capture happens before the commit**, so the artifact can go into the same commit when
  `Commit artifacts: yes`.
- `telesma/artifacts/` is in the default `Ignore on commit` list. Videos can be large.
- `playwright.md` and `detox.md` have a `## Recording` section: deterministic viewport, mocked
  timestamps, naming convention, moving videos from `test-results/` into `telesma/artifacts/flows/`.
- **Visual verification**: when a task has both `(ui-screen: …)` and `(screen: <id>)`, Claude reads
  the PNG once and compares it with the mockup — layout, hierarchy, states, token colours. A
  mismatch is fixed before the task is marked ✅ (one verification round per task). This catches a
  class of defects functional tests cannot.

To create artifacts after the fact, use [mode 4](#14-mode-4--artifacts).

## 8. Changes after clarification

After clarification `telesma/spec/` is **frozen**. Requirement changes go through `telesma/changes/` (section 0.3).

1. **Drop a file** into `telesma/changes/` — any name, e.g. `2026-04-23-email-mx-check.md`. The first run
   puts an annotated example there, `telesma/changes/EXAMPLE.md`, which is never processed as a change.
2. **Start Telesma as usual.** The launcher lists pending change files in the prompt.
3. **Before choosing a task**, Telesma:
   - reads the change file and, if `affects:` points at a spec section, that section too ("before
     vs after");
   - edits `telesma/state/PLAN.md`: a pending task is modified in place and annotated `(change: <file>)`;
     new functionality becomes new tasks in the right phase; a completed ✅ task that needs rework
     gets a new **rework phase** `Phase N.Z1` with tasks `(requires: <original id>)` — completed
     checkboxes are never unchecked;
   - gives every new task that adds a mechanism an `- AC: entry — …` line;
   - appends an entry to `## Change history` in `telesma/state/REPORT.md`;
   - moves the file to `telesma/changes/processed/` and commits.
4. **Later**, when working on a task annotated `(change: <file>)`, Telesma also reads
   `telesma/changes/processed/<file>` for the what and the why.

Change file format (the frontmatter is optional but recommended):

```markdown
---
date: 2026-04-23
priority: normal          # critical | normal
kind: correction          # feature | correction | bug
affects: telesma/spec/requirements.md (section "Email validation")
---

# What changes

Email validation must also check the domain's MX record, not only the format.

# Why

Spam accounts with fake domains pass the current validation.
```

- No frontmatter → `priority: normal`, `affects: general`, and Telesma judges the kind from the content.
- Critical changes are applied before normal ones; within a priority, alphabetically by file name.
- An ambiguous change → `TELESMA BLOCKED`. Telesma does not apply changes blindly.
- **`kind`** matters more than it looks: `telesma/changes/` is the main way a project *grows*, so the number of
  changes says nothing about quality. What does is how many exist because something already built
  does not work (`bug`). For bugs Telesma also records `Bug source` (the task that built the faulty
  thing) and `Detected by` (test, scenario, review, telesma, owner, production, guard).

Three layers of truth:

| Layer | Role | Mutability |
|---|---|---|
| `telesma/spec/` | The original requirement | Frozen after clarification |
| `telesma/changes/processed/` | What changed and why, with `affects:` pointing at the spec | Append-only (audit trail) |
| `telesma/state/PLAN.md` | Current execution state, `(change:)` annotations | Mutable |

Telesma normally reads only PLAN.md and spec fragments. It opens `telesma/changes/processed/` only for a task
with a `(change:)` annotation, and `telesma/spec/` through `affects:` only to see "before vs after".

**Rework phase ids.** `.Z<n>` phases belong to the track of their base phase. The phase header regex
is `^### Phase ([0-9]+[A-Z]?(?:\.Z[0-9]+)?):` — `Phase 6.Z1` is the first rework of phase 6,
`Phase 2M.Z1` the first rework of the mobile track of phase 2. In `Active phases` it is enough to list
the base phase (`2`, `2M`); its `.Z<n>` phases are included automatically.

With the Specky integration, requirement changes arrive in `telesma/changes/` automatically
([INTEGRATIONS.md](INTEGRATIONS.md)).

## 9. Multi-client projects (BFF)

When the spec implies **two or more clients** (web + mobile, web + CLI, …), Telesma raises an
**assumption** during clarification: a backend-for-frontend with dedicated controllers per client
and a branch per client. It is accepted by default (🔵 → ✅ after your spot-check).

For two clients (web + mobile), each module gets **two phases**:

- `Phase N` — **Core + Web**: entities, repositories, domain services, the `/api/web/*` controller and
  the web UI. Core goes here because web usually leads.
- `Phase NM` — **Mobile**: the `/api/mobile/*` controller and the React Native screens. Its tasks
  `(requires: N.X)` the core services, so the mobile track waits until core has landed and the
  mobile branch has rebased.

Tasks in each track touch only files specific to their client (`src/controllers/mobile/`,
`mobile-app/`, `ios/`, `android/`), so the `web` and `mobile` branches do not conflict.

Numbering: `Phase 1` = `1`, `Phase 1M` = `1M`, `Phase 6.Z1` = `6.Z1`, `Phase 2M.Z1` = `2M.Z1`. Phases
`1` and `1M` are **siblings**, not nested, and are usually worked on in separate branches; tasks in
`1M` are numbered `1M.1`, `1M.2`, … On each branch, set `Active phases` to its track
(`1, 2, 3` on web, `1M, 2M, 3M` on mobile).

With **three or more clients** Telesma does not assume a convention; it asks how to name the tracks.

## 10. E2E tasks at the end of a phase

Every phase that contains at least one task with a UI tag (`react`, `react-native`, `vue`,
`angular`, `svelte`) **must end with a full e2e task** — not just a `Test:` line — covering all UI
scenarios of that phase.

| Platform | Tags | Tool |
|---|---|---|
| Web | `(tech: playwright, typescript)` | Playwright |
| React Native | `(tech: detox, typescript)` | Detox (Maestro as an alternative — asked during clarification) |

The e2e task has an id like any other, `(requires:)` on **all** earlier tasks of the phase (it needs
the full stack), `(spec:)` pointing at user-flow documents, and a description that names concrete
scenarios ("sign-up → email verification → login → logout").

Phases without UI (backend, migrations, infrastructure) get no e2e task — a test after each task
plus the full suite after the phase is enough.

## 11. Interactive mode and DECISIONS.md

When the loop ends (`TELESMA COMPLETE`), stops (`TELESMA BLOCKED`), or runs out of tasks in the active
phases, the Claude session **stays open**. You talk to Claude normally — ask questions, request
tweaks, agree on direction. Telesma no longer picks tasks on its own.

Every such exchange is appended to `telesma/state/DECISIONS.md` (section 10):

```markdown
## 2026-04-23 16:42 — API caching strategy

**Kind**: question
**Question/context**: Whether to move the /api/products cache from Redis to in-memory.
**Outcome**: Staying with Redis. In-memory saves ~5 ms but loses cache consistency across 3 pods.
Revisit if we go single-pod or accept stale data.
**Impact**: Task 4.3 (cache layer) unchanged.
```

| Goes into the entry | Does not |
|---|---|
| A paraphrase of your question (1–2 sentences) | Quotes longer than one sentence |
| The essence of the outcome (2–4 sentences) | Claude's full answers |
| An explicit decision ("we agreed that X") | Code, snippets, diffs |
| Optionally the affected task, file or phase | File lists, command output |

There is no filtering — every interactive exchange is logged, including educational questions and
debugging. The file is for you.

What DECISIONS.md does **not** do:

- It is **never loaded into a prompt**. Telesma does not read it in the autonomous loop. Decisions with
  architectural impact are therefore **also** written to `## Key decisions` in
  `telesma/state/PROJECT_CONTEXT.md`, which the next autonomous session does see.
- It does not replace `telesma/changes/`: if an outcome requires plan changes, use the change channel.
- It does not replace REPORT.md: autonomous iterations are logged there.

Each entry carries `Kind` (`bug | correction | feature | question | operations`); for bugs also
`Bug source` and `Detected by`, as in change entries.

## 12. Mode 2 — bugfix

```bash
telesma.sh /path/to/project -m 2
```

Always interactive. A conversation about fixing bugs — no autonomous loop, no task selection, no
processing of `telesma/changes/`. Claude has the full project context (plan, report, context, spec index,
guidelines) and uses it in the diagnosis.

1. Claude greets you: "Bugfix mode active. Give me the bug (error message, stack trace or a
   description of the behaviour) …"
2. You paste the bug.
3. For each report:
   - **Diagnosis** — logs, locating the code, loading the guidelines for the affected files, and the
     spec fragment if the bug concerns a requirement.
   - **Proposal** — 2–4 sentences: where the problem is, what to change, regression risk.
   - **Your decision** — OK / change it / a question.
   - **Fix**, following the guidelines.
   - **Test** with the command from `telesma/config.md`.
   - **Commit** `Telesma: fix [description]` (when `Auto-commit: yes`).
   - **Entry in `telesma/state/BUGFIXES.md`**: Kind, Bug source, Detected by, Symptom, Cause, Fix, Test, Commit.
   - **A one-line release proposal** (patch version) after a commit.
4. You stay in the mode — paste the next bug or close the CLI.

Mode 2 does not add features, does not refactor beyond what the fix needs, does not modify `telesma/spec/`,
`telesma/changes/` or `PLAN.md`, and does not log to DECISIONS.md. If a "bug" turns out to be a missing
feature, Claude explains, proposes a task text and asks you to restart in mode 1.

Not every BUGFIXES.md entry is a bug: the mode doubles as a channel for small adjustments, which is
why each entry states its `Kind`.

## 13. Mode 3 — code review

```bash
telesma.sh /path/to/project -m 3
```

Always interactive. A **local, context-aware review**: Claude uses `telesma/spec/`, `telesma/guidelines/` and
`PROJECT_CONTEXT.md` as criteria — things generic tooling does not know. Results go to
`telesma/state/REVIEWS.md`.

Scope selection:

```
Code review mode active. Choose the scope:
  a) Uncommitted changes (git diff)
  b) The last commit (HEAD)
  c) Branch vs main (git diff main...HEAD)
  d) A specific task from PLAN.md (give the number, e.g. 3.2)
  e) Selected files (give a list of paths)
```

Procedure:

1. **Context mapping** — which plan task each changed file belongs to, with its `(spec:)` and `(tech:)` tags.
2. **Loading criteria** — spec fragments through SPEC_INDEX, technology guidelines, decisions from
   PROJECT_CONTEXT.
3. **Analysis in seven dimensions** — spec compliance, guideline compliance, tests (coverage and
   quality), security (OWASP), clean code, consistency with the rest of the code, performance.
4. **Severity per finding**: 🔴 **Blocker** (bug, security, broken contract, spec violation),
   🟡 **Important** (guideline violation, missing test, code smell, inconsistency),
   🟢 **Suggestion** (cosmetics, naming, small refactor).

Fix policy, in the order 🔴 → 🟡 → 🟢:

- **🔴 and 🟡 are gated per finding**: *fix* (Claude fixes and commits `Telesma: review-fix [description]`),
  *skip / accept* (recorded as accepted as-is, with your comment), or *task* (Claude proposes a plan
  task, recorded as TODO — you add it via mode 1 or `telesma/changes/`).
- **🟢 as a batch**: one "yes" applies all of them in one commit `Telesma: review-fix (cosmetic)`, reverted
  automatically if the tests fail.

Mode 3 vs `/ultrareview`:

| | Mode 3 (local) | `/ultrareview` (cloud) |
|---|---|---|
| Started by | `telesma.sh -m 3` | You, typing `/ultrareview` in the CLI |
| Context | Full: spec, guidelines, PROJECT_CONTEXT | The branch's code |
| Criteria | Project-specific | General best practices |
| Multi-agent | No | Yes |
| Cost | A normal session | Billed separately |
| Result | `telesma/state/REVIEWS.md` | Cloud UI |

They complement each other. For large scopes (a branch over ~2,000 lines) or critical modules (auth,
payments) the verdict may suggest `/ultrareview`; Claude never starts it itself — it needs your
gesture in the CLI.

## 14. Mode 4 — artifacts

```bash
telesma.sh /path/to/project -m 4
```

An **autonomous backfill** of screenshots and recordings for the project's current state. Use it when
the plan is already done and you want recordings after the fact, when you added `telesma/spec/APP_FLOW.md`
or `telesma/spec/ux_ui/` later, when you switched `Recordings` or `Screenshots` from `no` to `yes`, or when you
refactored the UI and want everything re-recorded (`rm -rf telesma/artifacts/` first).

Entry rules: `Clarified: yes`; at least one of `Screenshots` / `Recordings` set to `yes` (otherwise
"TELESMA ARTIFACTS: nothing to do" and the session ends). Mode 4 does not pick tasks, does not touch
checkboxes or task text, and does not process `telesma/changes/`.

Procedure:

1. Collect targets from two sources: every `(screen:)` and `(flow:)` tag in PLAN.md (regardless of
   checkbox state), and every `## Step N` in the flow files — even without a matching plan tag,
   which is the typical backfill case.
2. Deduplicate; drop screenshot targets if `Screenshots: no` and flow targets if `Recordings: no`.
3. **Idempotency**: an artifact that already exists is skipped. To force regeneration, delete it.
4. For each missing artifact: find its test (or write one per section 0.5 and the `## Recording`
   section of the guideline), run it with recording, move the file to its deterministic name, and
   add a line to `## Visual artifacts` in REPORT.md.
5. A failing target does not stop the others — it goes to the Problem log.
6. **One commit** at the end: `Telesma: regenerate visual artifacts ([N flows], [M screens])`. No commit if
   every target failed.
7. A final report:

```
TELESMA ARTIFACTS REGENERATED

Recordings:  X generated / Y skipped (already exist) / Z failed
Screenshots: A generated / B skipped / C failed
...
```

The session then switches to interactive mode.

| Mode | What it does | Modifies PLAN.md? | Records? |
|---|---|---|---|
| 1 (autonomous) | Works on new tasks; capture as a side effect | Yes (marks ✅) | Only for the current tagged tasks |
| 4 (artifacts) | Backfills artifacts for the existing state | No | Yes — that is the point |

Mode 4 never generates artifacts from unfilled templates, never writes missing implementation (a
screen that does not exist is logged and skipped), and never deletes existing artifacts or tests.

## 15. BACKLOG

`telesma/state/BACKLOG.md` collects **things to do some day** — ideas, small improvements, technical debt
noticed during interactive sessions (section 13). Unlike DECISIONS, BUGFIXES and REVIEWS, which are
write-only logs, it is **read-write**.

| Signal in the conversation | Channel |
|---|---|
| "We agreed that …" | DECISIONS.md (section 10) |
| A reported bug → diagnosis → fix | BUGFIXES.md (section 11) |
| A review of a scope → findings | REVIEWS.md (section 12) |
| "Let's change requirement X" | `telesma/changes/<file>.md` (section 0.3) |
| **"Later" / an idea / debt** | **BACKLOG.md (section 13)** |

Entry format:

```markdown
- [ ] **Title** — `P2` `area`
  - **Context**: date, where it came from, the observation
  - **Suggested solution**: one or two sentences
  - **Dependencies**: other items (optional)
```

Priorities: `P0` next session, `P1` this phase, `P2` nice to have, `P3` an idea.

- **Adding** — Claude picks up signals ("for later", an out-of-scope observation in bugfix or review
  mode, the variants you did not choose) and **proposes** an entry with a title, priority and area.
  Nothing is added without your OK; "skip" means it will not ask about that topic again this session.
- **Promotion to `telesma/changes/`** — "promote X": Claude creates `telesma/changes/<slug>.md` with frontmatter and
  marks the item `[→ telesma/changes/<slug>.md]`; the next mode 1 start applies it.
- **Ad-hoc execution** — "do item X": Claude implements, tests, commits and marks it `[x] (abc1234)`.
- **Archiving** — completed items older than 30 days move to `BACKLOG_DONE.md`; when there are more
  than 10, Claude proposes the move at the start of an interactive session.
- **Mode 1 does not modify the backlog.** One exception: when the loop runs out of active phases, it
  reads the backlog and mentions unpromoted `P0`/`P1` items before finishing.

## 16. Releases and manual test scenarios

`vX.Y.Z` means **what shipped to production** — deliberately separate from the internal progress
tags `telesma/phase-<ID>`. In conversation Telesma says "release version vX.Y.Z", never a bare "tag",
which would be easy to confuse with `(tech:)` tags or phase tags.

**Telesma proposes, you decide.** A proposal is always the same, visibly separate block:

```
📦 RELEASE PROPOSAL — version v0.5.0
Previous version: v0.4.2 (2026-09-30), 14 commits since then, phases: 7, 8.
What landed: <2–3 sentences in product language — what the user can see or do>
Number: minor, because features were added
Attack surface: <new routes, public ones among them, role changes> — only when there is one
Answer "yes" (or give another number) → I create the release version v0.5.0, write
docs/test-scenarios/v0.5.0.md for the testers and give you the push command.
"no" or no answer → I go back to the loop and will ask after the next phase.
```

When it is proposed: after a green full suite at the end of a phase; at `TELESMA COMPLETE` (before the
final message); on entering interactive mode for another reason (once per session, when there are
commits since the last version); and as a one-line patch proposal after every bugfix-mode commit.
"Do not ask about releases" turns it off for the rest of the session. The launcher computes the data
for the block (the `VERSIONS:` line in the prompt: last `v*` tag, its date, commits since), so the
proposal does not depend on the model remembering to run `git describe`.

**Numbering:** read from `git describe --tags --abbrev=0 --match 'v*'`. Minor for features, patch for
fixes, major only when you say so. No `v*` tag yet → `v0.1.0`.

After "yes", in this order:

1. **Manual test scenarios** — `docs/test-scenarios/vX.Y.Z.md` (file name = version), built from
   `telesma/state/TEST_SCENARIOS_TEMPLATE.md`. Only what **automated tests could not check**: appearance, real
   data, external services, production-only paths — sourced from `git log <previous>..HEAD` and notes
   on the tasks closed in that range. One scenario = one checkbox (`- [ ] **Result N.M**`), each with
   a **failure signal**; a release that adds a limit, validation or permission gets a **Barriers**
   section of things that must be *rejected*. A step in `telesma/spec/APP_FLOW.md` already covered by a green
   e2e test is exactly what does *not* belong here; the regression section points at steps by name,
   with the matching recording as "this is how it should look". The file is committed **before** the
   tag, so it is part of the tagged state. You mark results afterwards: `[x]` works, `[-]` broken.
2. **The tag** — `git tag -a vX.Y.Z -m "<2–4 sentences from git log, in product language>"`. Git says
   what actually landed; the plan only says what was planned. Blockers: a red suite, a dirty working
   tree (a tag on a dirty tree points at a state nobody can reproduce), an existing tag of that name.
   `-f` is forbidden here, unlike phase tags. With quality checks enabled, an open weakening
   (`telesma: weakening …`) also blocks the release tag.
3. **A closing block**: the version created (SHA), the scenarios path, and `git push origin vX.Y.Z`
   — with the reminder that tags do **not** travel with a plain `git push`.
4. A one-line entry in `telesma/state/DECISIONS.md`.
5. With `Tracker: specky`, a **release snapshot** in Specky with the tag, SHA and full scenarios.
   Specky being unreachable never blocks a release.

Telesma **never** pushes the tag, merges to `main`, deploys, or edits version fields in
`package.json` / `pyproject.toml` (the version is derived from git when the image is built).

## 17. Resuming a session

Telesma detects a resumed session from `telesma/state/REPORT.md`: it reads the task history, finds the last
completed task and continues with the next unfinished one. Because the state files are updated after
every task, an auto-compaction in the middle of a session is handled the same way — the state is
rebuilt from the files.

A blocker from the previous session (`telesma/state/BLOCKED.md`) is shown in the terminal and injected into the
prompt; Telesma resolves it before choosing a task and deletes the file afterwards. The same applies
to `telesma/state/WAITING.md` with the GitHub integration.

## 18. Monitoring progress

**In `telesma/state/PLAN.md`** — checkboxes:

```markdown
- [x] Task 1.1: Project structure ✅
- [x] Task 1.2: Configuration ✅
- [ ] Task 2.1: Endpoint POST /todos      ← in progress
- [ ] Task 2.2: Endpoint GET /todos
```

**In `telesma/state/REPORT.md`** — the summary, test status, task history and problem log:

```markdown
## Test status

| Metric | Value |
|--------|-------|
| Total tests | 14 |
| Pass | 12 |
| Fail | 2 |

## Task history

| Task | Status | Tests | Tries | Commit | Time |
|------|--------|-------|-------|--------|------|
| 1.1: Project structure | pass | 3/3 | 1 | a1b2c3 | 6 min |
| 2.1: Endpoint POST | blocked | 2/4 fail | 3 | - | - |
```

**In git:**

```bash
git log --oneline | grep "Telesma:"
git tag --list 'telesma/phase-*'
```
