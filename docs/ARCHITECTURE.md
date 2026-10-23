# Telesma architecture and design rationale

This document explains **why** Telesma works the way it does. `CLAUDE.md` says what is where and
which invariants must hold; this file keeps the reasoning and the lessons behind each mechanism,
with the numbers that decided them. Before 1.0, Telesma was developed privately (internal versions
1–17); most of the lessons below come from that period and from a few long-running
projects built with it. "The reference project" means the largest of them — a production
application developed with Telesma for more than a year, with close to two thousand tasks in its
plan. Where history mentions old names, the current English names are used.

The recurring theme: **whatever the model does not do consistently, a script enforces.** Several
mechanisms started as instructions, were measured, found to be followed unevenly, and moved into
the launcher, a hook or a check.

---

## 1. Continuous session instead of restart-per-task

Classic Claude automation restarts the CLI for each task and feeds it a fresh prompt. Telesma does
the opposite: one session, in which the model runs the loop itself — pick a task, load what it
needs, implement, test, commit, report, pick the next one — and calls `/compact` when context
grows (per config: every N tasks or after a phase).

The price of a continuous session is that the context will be compacted, and anything held only
in the conversation is lost. Hence the **state files**: `telesma/state/PLAN.md` (what to do), `REPORT.md`
(what happened), `PROJECT_CONTEXT.md` (architecture, decisions, pitfalls), `SPEC_INDEX.md` (where
things are in the spec), `config.md`. The model is told to update them *before* compacting. They
are also what a new session starts from, so a session resume is detected from `REPORT.md` history,
not from memory.

The launcher (`telesma.sh`) does everything deterministic before the model starts — migration,
rotation, validation, prompt assembly — because work done by a script costs zero tokens and does
not depend on the model remembering it.

Modes after clarification: **autonomous** (the loop), **bugfix** (chat: report → diagnosis →
proposal → acceptance → fix → test → commit → `BUGFIXES.md` entry), **review** (chat: choose a
scope, load telesma/spec/guidelines/context as criteria, findings with severity, low-severity fixes batched
automatically, the rest gated, `REVIEWS.md` entry) and **artifacts** (autonomous, idempotent
backfill of screenshots and recordings). Modes 2 and 3 force interactive mode because the chat is
their point.

## 2. Clarification and plan generation

A spec is never complete, and a model that guesses silently builds the wrong thing confidently.
Clarification (section -1) therefore runs before any code:

1. The model reads `telesma/spec/` and writes `telesma/state/SPEC_INDEX.md`: a two-level index with line ranges,
   per-section anchors, keywords — and a **quality assessment** (completeness, unambiguity,
   consistency, topic gaps, recommendation). The assessment drives the number of questions.
2. `telesma/state/QUESTIONS.md` has three sections, in the order the user resolves them:
   - **Contradictions** (`### S…`) — two sources that disagree, with a proposed resolution.
     They must be settled first; answering questions on top of a contradiction wastes the answers.
   - **Assumptions** (`### A…`) — decisions taken without asking (industry standards, stack
     conventions), listed for a spot-check. This is what keeps the question count down.
   - **Questions** (`### Q…`) — only what cannot reasonably be assumed. The count is adaptive:
     3–7 for a small project with a good spec, 15–30+ for a large one with a poor spec. Every
     question cites its **Source** in the spec.
3. After the answers, the plan is generated from four sources: spec, contradiction resolutions,
   accepted assumptions, answers. The launcher first tries `claude --continue` on the indexing
   session, which already has the whole spec in context (cheaper and better informed), and falls
   back to a fresh run if no plan materialises.
4. The plan starts with task 1.1 "architecture skeleton", carries `- AC:` acceptance criteria on
   non-trivial tasks and a `## Spec coverage` section mapping every index section to tasks or to a
   justified "out of scope", and passes a self-review checklist.

Then `Clarified: yes` is set and `telesma/spec/` is frozen.

The launcher validates the plan mechanically before every start: dependency graph (existence,
cycles, duplicate ids), `(tech:)` tags against `telesma/guidelines/`, `(spec:)` / `(ui-*:)` /
`(flow:)` tags against files. Errors gate the start. It also computes a next-task hint and
collapses completed phases in the prompt copy.

## 3. Selective retrieval and anchors

Telesma never loads a whole spec document. A task carries `(spec: file.md)`; the index gives the
section and its line range; the model reads only that fragment with `offset`/`limit`. Grep over
`telesma/spec/` is the fallback.

Line ranges go stale when someone edits a file. So each index entry also carries an **anchor** —
the exact heading text — and the model verifies that the fragment it read starts with it. On a
mismatch it greps the heading, reads from the right offset and fixes the index entry itself. The
launcher additionally stamps spec checksums into the index and warns on drift.

UX/UI material in `telesma/spec/ux_ui/` (tokens, primitives, screens as CSS/JSX/HTML) is indexed per
element. Tags `(ui-tokens:)`, `(ui-component: file#A,B)` and `(ui-screen: file#Screen)` load one
element at a time. Prototype components are **rewritten** into the production stack, never copied
(prototypes are typically in-browser Babel with globals); a screen task reads the production
component API, not the prototype again. Mockups that live outside the repo are entries in
`telesma/spec/ux_ui/LINKS.md`, resolved through the index to a web fetch. That file is exempt from the
spec freeze; the launcher detects unindexed entries deterministically and asks for a re-index.

## 4. Technology guidelines

Conventions per language/framework live in `telesma/guidelines/` (copied from
`templates/guidelines/`). The prompt carries only an index (tag + keywords). Per task the model
reads `general.md` plus one file per `(tech:)` tag. A missing tag file is `TELESMA BLOCKED` — asking
is cheaper than a project written in invented conventions.

Users edit these files freely. Updates go through `.telesma-manifest`, which stores the hash of the
template version last delivered: an unedited file (equal to any historical template version) is
replaced; an edited one gets a one-time warning with a diff command and is never overwritten.
The same mechanism delivers the judge hook, the checks and the test-scenario skeleton.

## 5. The changes channel

After clarification `telesma/spec/` is frozen; changes come through `telesma/changes/`, one Markdown file per
change, optional frontmatter (`date`, `priority`, `affects`, `kind`). Before picking the next task
the model processes pending changes (section 0.3): modifies pending tasks in place with
`(change: <file>)`, creates a **rework phase** (`Phase N.Z1`) for completed tasks that need
rework — completed boxes are never unchecked — writes a `## Change history` entry and moves the
file to `telesma/changes/processed/`. A task carrying `(change:)` re-reads that file when executed.

Designed for spec corrections, `telesma/changes/` turned out to be the **main channel through which
projects grow** — hundreds of changes in a few months on the reference project, and many projects
start from a deliberately thin spec. So neither the number of changes nor the share ending in
rework says anything about quality. What carries signal is a change that exists because something
already built does not work — hence the `Kind` field (`bug | correction | feature`), see §11.

## 6. Interactive decision log

After `TELESMA COMPLETE` or `TELESMA BLOCKED` the session stays open and the human takes over. Every
exchange is appended to `telesma/state/DECISIONS.md` (question/context paraphrased, the outcome in 2–4
sentences, optional impact). The file is **write-only** — never loaded into a prompt — so
decisions with architectural impact are **dual-written** to the `## Key decisions` table in
`PROJECT_CONTEXT.md`; otherwise the next autonomous session would never see them. Topics for later
go to `telesma/state/BACKLOG.md`, which, unlike the logs, is read-write.

## 7. Release versions and manual test scenarios

`vX.Y.Z` marks what shipped; it is deliberately separate from the internal `telesma/phase-<ID>`
progress tags. Telesma **proposes** a release and waits — no answer, no tag. The proposal is a fixed,
visibly separate block (`📦 RELEASE PROPOSAL`: previous version and date, commits since, what landed
in product language, the suggested number with the reason, what "yes" will do), because a sentence
folded into a phase report was easy to miss. Moments: green full suite at phase end,
`TELESMA COMPLETE`, entering interactive mode with unreleased green commits, and a one-line patch
proposal after a bugfix commit. The launcher computes the data (`VERSIONS:` directive) so the
proposal does not depend on the model remembering `git describe --tags --abbrev=0 --match 'v*'`
(the `--match` matters, or `describe` returns a phase tag). In user-facing text Telesma says "release
version vX.Y.Z", never bare "tag" — to an owner the bare word means nothing specific.

Before tagging, Telesma writes `docs/test-scenarios/vX.Y.Z.md` and commits it, so the file is part
of the tagged state and the tree is clean. It contains **only what automated tests could not
check** — look and feel, real data, external services, production-only paths — sourced from
`git log <prev>..HEAD` and notes on tasks closed in that range. Every scenario has a failure
signal; a release that adds a limit, validation or permission also gets a **barriers** section of
things that must be *rejected*. `telesma/spec/APP_FLOW.md` contributes by exclusion: a step covered by a
green e2e test is exactly what must not be copied here.

Blockers: red suite, dirty tree (a tag on a dirty tree points at a state nobody can reproduce), an
existing tag of that name (`-f` is forbidden, unlike phase tags). Never: push (the user gets the
command and the note that tags do not travel with a plain push), merge to main, deploy, or edits
of version fields in manifests — the version is derived from git.

## 8. State-file rotation

`PLAN.md`, `REPORT.md` and `PROJECT_CONTEXT.md` go into every startup prompt in full and grow
linearly. On the reference project, after a year, that was ~400k tokens before a single task
started, 77% of it `REPORT.md`. The launcher rotates them at startup — deterministic, zero tokens —
into `*_ARCHIVE.md` files that are never loaded.

**Two kinds of sections.** *Current state* (`## Summary`, the metrics table in `## Test status`)
is overwritten by the model; growth there means a session note was appended where it should not
be, and only the three newest dated bullets survive. *Chronicle* sections (`Test status` run
paragraphs, `Task history`, `Problem log`, `Change history`, ad-hoc sections) are append-only and
keep the newest N (3 runs, 10 entries, 10 log entries, 10 change entries, 3 ad-hoc sections).
Ad-hoc sections are recognised by a **title not in the template's set** — a name pattern missed
everything the model invented, and one such section sat in every prompt for three weeks.

**An entry is a block, never a line.** An early rotation archived single lines — a table row, a
`[date]` opener — while the model writes multi-line entries (symptom + fix + lesson; a phase
history subsection with its own table). Rotation cut entries in half: the archive held bare
openers, the report kept headers with no rows and paragraphs starting mid-sentence. This was the
one framework bug that *destroyed* content, which is why repair exists (§10).

**Ordering is date-driven, not positional.** The model appends to the bottom in some sessions and
prepends in others; "keep the last N" silently archived the newest entries. The N newest by date
survive wherever they sit. An undated block cannot be judged, so it stays but consumes a slot — an
earlier rule required *every* block to carry a date, so one undated entry flipped the whole section
back to positional mode.

`## Test status` was first classified as current state — a mistake: every run is compared with the
previous one, so the model appends paragraphs. On the reference project the section reached 128 KB
(~25k tokens per start, 90 runs back). Run blocks are now paragraphs opened by bold text with a
date; a dateless paragraph continues the block above (wrapped lines also start with `**`, and
treating them as blocks broke the date sort). 128 KB → 2.4 KB.

`PROJECT_CONTEXT.md` keeps the last 40 `Key decisions` rows and the last 30 `Known problems and
solutions` rows, date-sorted; a row marked `📌` never rotates. The template once offered two
sections for the same job (a problems table and a pitfalls list); the model filled the one the
instructions did not describe, so the list was removed and folded into the table. Its size limit
is in KB, not lines: "~150 lines" is no limit when a line runs to 2300 characters (162 lines,
82 KB on the reference project).

`PLAN.md` archives 100%-complete phases beyond the last N, only above 100 KB (small projects get
no churn). A stub plus `<!-- telesma-archived: 12.1 12.2 … -->` stays, so the validator still
resolves `(requires: 12.3)`. Archiving is prompt-neutral (collapsing already protected the prompt);
it buys file size, Edit/Grep cost and readable diffs — 1672 KB → 142 KB on the reference project.
Ad-hoc `## Requests from <date> — …` sections were *not* prompt-neutral: their prose intros
(91 KB of commentary on long-shipped changes) escaped both collapsing and archiving, which only see
`### Phase`. Rotation archives only the intro, never the section — live phases hang under those
headers, and a section with any open `- [ ]` is skipped entirely.

**What counts as a task.** The task regex once allowed only `✅` before the keyword, so a task
marked `⛔` (waiting for a human) was invisible — and not counted toward phase completion, so a
phase whose only remaining work was a `⛔` task read as complete and was archived with unfinished
work inside. Any leading marker is now tolerated; `⛔` counts toward completeness, and the
next-task hint skips it unless nothing else is left. Task lines are capped at 400 characters;
long rationale belongs in the files that rotate.

Rotation dirties the tree at startup, which would block release tagging, so the instructions tell
the model to include `telesma/state/*_ARCHIVE.md` in the session's first commit.

## 9. Startup prompt diet

The first measurement across dimensions (§11) found the reference project's startup prompt at 425k
characters (~105k tokens) before Telesma did anything — carried again on every turn. 60% of it did
not serve picking and doing the next task: 410 one-line stubs of archived phases, dozens of empty
ad-hoc headers, `PROJECT_CONTEXT.md` table rows with a median of 967 characters (the instructions
say "a couple of sentences"), ad-hoc change-history sections whose text already lives in
`telesma/changes/processed/`, and 13 KB of template comments in `config.md`.

All of it is trimmed **in the prompt copy only**; files on disk are untouched. Finished phases
become one line of ids (enough for dependencies — the title is one grep away), exhausted ad-hoc
sections are dropped, config comments stripped, table rows cut at 400 characters with a pointer
to the file. The diagnosis flags oversized rows so the model shortens them at the source. Result:
425k → 286k characters (−33%). The side effect to watch is retries — the model occasionally needs
a grep for something the prompt no longer shows.

## 10. State-file diagnosis and repair

Nothing used to measure the state files themselves; the reference project grew to 550 KB of prompt
before anyone looked. `tools/telesma-repair.py` does two jobs:

- **Diagnosis** at every start (file reads only, silent when clean): orphaned paragraphs in the
  problem log, history subsections whose table lost its rows, unfinished tasks in the plan
  archive, over-long task lines, checkbox items that are not tasks, oversized sections and files.
  Findings are `damage` (repairable) or `notice`.
- **Repair** (`--repair`), a deliberate act rather than a startup step: it reads the entire git
  history of `REPORT.md` and rewrites files.

**Git is the source of truth**, with a rule per section: a log entry is restored from the commit
that first introduced it (written once; later versions carry glued-on orphans of entries rotated
away below it), a history subsection from its longest version ever (rows accumulate legitimately).
Orphans are deleted only after their text is verified present in the archive. Two further repairs
are mechanical: a phase archived with unfinished work goes back (the archive block and the stub are
verbatim what rotation moved, so swapping them reverses a wrong move), and a checked item without a
task keyword — a note wearing a checkbox — moves under its phase in `Task history`, dated by
`git log -S`. An *unchecked* non-task item stays with the human: forgotten task or backlog entry,
only a person can say.

Repair opens exactly four files (`REPORT.md`, `REPORT_ARCHIVE.md`, `PLAN.md`, `PLAN_ARCHIVE.md`), so
decisions, backlog and conversation records are out of reach by construction. **It never deletes
what git does not know about** — a first version rebuilt history subsections from git and therefore
reverted, on a second run, the notes the first run had moved in. `tools/test-repair.py` pins the
properties: every word of four or more characters occurs at least as often after repair (word level,
because the tool reformats), files outside scope are byte-identical, and a second run changes
nothing.

## 11. Quality telemetry (optional, self-hosted)

Every framework bug above was found the same way: a human opened a project and read its state
files. `tools/telesma-telemetry.py` makes that systematic. It is **optional and off by default**; when
enabled it sends events to the user's own server (a separate, self-hosted project), in the
background at startup — the start never waits for it. Payload schema version 2.

It reads what Telesma leaves behind anyway — problem log, tries per task, bugfix/review/decision
logs, change history, pitfalls, scenario results, judge decision counters — plus git history and
local Claude Code transcripts. Pure reads, zero tokens, never modifies the project. **What never
leaves the machine:** `telesma/spec/`, source code, `telesma/changes/` (written by a human about the product) and
commands from the judge log (reduced to per-day counters). Text is scrubbed of secret patterns and
the home path; `tools/test-telemetry.py` pins all of it with canaries. Sending uses plain HTTP, not
MCP: a send that depends on the model remembering to call a tool would repeat the `Test status`
lesson. What was sent is remembered in `~/.cache/telesma/`, not in the project (a file there would
dirty the tree and block release tagging); a failed send marks nothing and is retried next start.
A server older than the client returns rejected ids, and those are resent until it catches up.

Design points that came from analysing real data:

- **Event ids are natural keys** (project + type + entry opener), not content hashes: rotation
  moves an entry, the model appends a lesson — still the same event.
- **The framework version is the version at event time**, read from the git history of
  `.telesma-version`; an event older than that file gets `null`, not the first known version —
  otherwise four months of history lands in one bucket and every comparison lies.
- **State files alone are a biased sample.** Only 35% of completed tasks on the reference project
  had a row in `Task history`, and an apparent jump in retried tasks across versions was a change
  in how the column was filled, not in quality. So **tries per task come from git** too: a commit
  subject carrying a known task id yields date, files, lines, follow-up fix commits and minutes
  since the previous commit (task coverage 676 → 1074; where both exist they agree). **Sessions**
  come from transcripts: mode, model, tokens, tool calls by name and how many errored,
  compactions, duration — counters only. The model field matters: three different models worked
  on the reference project within a month, and without it a framework change cannot be told apart
  from a model change. Transcripts expire after about 30 days, so this data exists only if sent.
- **`Kind`** (`bug | correction | feature`, plus `question | operations` in decisions) makes
  changes and decisions readable as signal; the test is "had it worked, would this exchange have
  happened?". Entries without it stay `null` — the collector never guesses. A bugfix-mode entry is
  not a bug by virtue of its file: about a quarter of them were small features.
- **Bug source.** A bug is charged to the version under which it was *introduced*, not reported:
  otherwise every new version looks worse for months. Bug entries carry `Bug source: task X.Y`
  (found with `git log -S` / `git blame`); the collector stamps the source task's version, date and
  technology on the bug.
- **Detected by** (`test | scenario | review | telesma | owner | production | guard`) — the same
  number of bugs means something else when tests catch them than when the customer does. On the
  reference project roughly half of the historical bugs were found by the owner or in production —
  all under green test suites.
- **Test runs, blockers, technology.** Every dated `Test status` paragraph becomes a `test_run`
  event, including runs that were red on the way to green. Blockers come from the git history of
  `BLOCKED.md` (the file is deleted once resolved). Entries without a task id get a technology
  inferred from text, only among tags the plan uses, and marked as inferred.
- **Ten dimensions, not just defects.** The first retro looked at quality only, and its rules then
  cost ~35% more time per stage in the benchmark — a trade-off nobody had stated. Analysis now
  reports one row per framework version across quality, performance, tokens, repeatability,
  history size, reporting, autonomy, truthfulness of reports (share of done tasks that later became
  a bug source), lines of defence, and code health (suite duration, test churn, share of added
  lines that are tests). Every proposal must name its dimension and side cost, and rules that did
  not move their metric are proposed for withdrawal: every instruction line costs tokens in every
  session of every project.

A sender signature (hash of the git email, readable git name) gives attribution, not
authentication. Event ids deliberately exclude the sender, so two people on one project produce
one event per entry.

## 12. The first retro's rules — lessons

The first analysis of the reference project's events produced three rules, each now in the
instructions and in `general.md`:

1. **A task that adds a mechanism names what triggers it, and one test goes through that entry.**
   The costliest defect class was code built, tested and wired to nothing: a toolbar rendered only
   in its own test, screens with no navigation entry, a phase that "did not work end to end despite
   37 green tests". The plan had zero `- AC:` lines across ~1900 tasks, because projects grow
   through `telesma/changes/` and acceptance criteria existed only in plan generation. Now every new
   mechanism gets `- AC: entry — …`, a test goes through that entry, and a 30-second check asks
   "disable the call — does anything go red?".
2. **A pitfall that came back despite being written down gets a guard, not a pin.** A pitfall about
   a typographic closing quote truncating a string literal was recorded, pinned and loaded into
   every prompt — and recurred nine times in five weeks. A note works on errors of ignorance, not
   on errors made by reflex. On the second occurrence a pitfall becomes a mechanical check (guard
   test, lint rule, grep in the smoke suite) and the row says `→ guard: <name>`; `📌` is reserved
   for what cannot be checked mechanically.
3. **A rule's test is verified by mutation — with a procedure that does not wreck the repo.** Telesma
   arrived at manual mutation testing on its own and it kept exposing green tests that guarded
   nothing; it also wiped uncommitted work with `git checkout` and once left a `MUTANT` disabling
   production validation past the end of a session. `general.md` now states a four-step procedure,
   and the commit step greps for `MUTANT`.

`TELESMA_FORMAT` was bumped with no migration for this, deliberately: telemetry tells "before" from
"after" by the version, and a change without a new number would be invisible to the measurement it
was made for.

## 13. Integrations: repository and tracker

Telesma has **no integration by default**: it commits to the current branch, never pushes, knows no
tracker. Integration instructions are separate files appended only when `## Integrations` names
them, so a non-integrated project behaves exactly as before and pays no tokens. User doc:
`docs/INTEGRATIONS.md`.

The origin: a test project finished its whole plan and left **77 open PRs**. The loop treated a task
as done when its PR was opened, knew nothing about required checks or merge, chained every PR on the
previous unmerged one — and the PR convention lived only in the session's memory while the config
said "no branches, no push".

- **Done means merged.** A task with a PR carries `(pr: #n)` with the checkbox open until the merge.
  The checkbox is what phase completeness, collapsing and archiving already read, so phase tags,
  the full suite and release proposals fall in the right place with no new rule. The next-task hint
  skips `(pr:)` tasks, counts them against `Open PR limit` (`PR LIMIT REACHED` → `TELESMA WAITING`, a
  terminal state meaning "nothing is broken, the loop needs a merge"), and offers a task whose only
  unmet dependencies are open PRs last, marked `chain`. Every iteration starts with one
  `gh pr list` reconciliation.
- **Three merge modes**: `auto` (`gh pr merge --auto`, needs repository features a free private repo
  lacks), `manual` (waits for a human) and `agent` (default: Telesma waits on `gh pr checks --watch`
  and merges itself). In `agent` mode the rule "merge only on green required checks" is enforced
  by the **permission judge**, not an instruction: it runs its own `gh pr checks` before letting
  `gh pr merge` through, and every required check must be *present* and green — a missing check is
  not a green one. Push is allowed only to the task branch prefix.
- **Chains need a rebase, in the right order.** Squash stays (one commit = one task on main). The
  first version claimed GitHub retargets a PR whose base branch is deleted at merge; on the first
  real chain, merging with `--delete-branch` *closed* the successor instead. The order is now
  bottom-up: retarget the successor to main first, merge the predecessor without deleting its
  branch, then rebase the successor `--onto origin/main` and force-with-lease push. The same episode
  showed a phase regression recorded from a branch while main had a red test — so a full run on a
  branch is a `Preliminary run`, and `Regression after Phase N` is recorded only from main.
- **Specky sync materialises as `telesma/changes/` files.** For the [Specky](https://app.specky.app)
  requirement tracker, `what_changed` + `get_work_queue` become `telesma/changes/<date>-specky-<id>.md`
  with `kind` in the frontmatter and then ride the existing section 0.3. The cursor moves only after
  the files are written. Plan anchors `- Specky: (req: <id> v<n> @<hash7>)` are checked before each
  task; tests carry `specky: crit <id>`; the proof is the JUnit report from CI, not Telesma's word.
  Telesma proposes; decisions in Specky stay with the human.
- **A release is a Specky snapshot.** Right after the version tag Telesma creates a snapshot with the
  tag, the commit SHA, the message and the full test-scenarios file. After the tag, never before:
  the file is inside that commit, so both copies are identical by construction. Specky being down
  never blocks a release. `tools/telesma-specky-snapshots.py` backfills older tags.
- **Wizard, not a form.** `--integrations` (and the first config creation) asks which integrations
  to enable, checks `gh`, login, remote and what the repository allows, recommends a merge mode and
  writes only `config.md`. Config fields are validated like the test commands.

## 14. Permission judge

An opt-in hook (`## Auto-approval`) that answers permission prompts on the user's behalf. Purely a
harness feature; the instructions never mention it. Governing rule: **the judge only removes
prompts, never adds blocks.** Anything dangerous still prompts, so the human remains the backstop
exactly as before. Layers that recognise danger therefore *ask* rather than deny — `rm -rf
node_modules` and `git push` are often legitimate, and denying would remove the user's ability to
approve them.

One exception, learned from the first live trial of the public version (2026-10-22): the whole
project ran in Claude Code's `auto` permission mode, where the built-in classifier answers prompts
and the `PermissionRequest` hook is never called. 438 decisions by the classifier, 0 by the judge; a
PR merged on a red required check, a release tag pushed. "Ask" is only a backstop when someone is
asked. So two agent-side rules of the contract — merge only on green required checks, no push of a
release tag — moved to the `PreToolUse` hook as a **deny with a reason**, because that hook runs in
every mode. The layer is kept tiny on purpose (it mirrors what the instructions already forbid), a
`gh` failure never denies, and the human can always do the operation by hand. The same hook leaves
a `note` in the log when it sees `auto`, the launcher warns at the next start, and it starts Claude
with an explicit `--permission-mode` so a session never begins in `auto` by accident.

Layers, model last and narrowest:

1. **Hard patterns** (`rm -rf`, `sudo`, `curl | sh`, `git push`, SSH keys, cloud CLIs, package
   publish, writes to `.claude/` or `telesma/config.md`) → ask. The model never sees them.
2. **`Always ask`** user regexes, obfuscation at the conservative level, and **writes disguised as
   reads** → ask.
3. **Read layer** — a command whose every member is *provably* a read inside the project or the
   working directories passes with no model.
4. **Model judge** — only the gray zone. `ALLOW` skips the prompt; anything else is "no decision".

Lessons that shaped it:

- **A broad allowlist makes the judge inert** (`PermissionRequest` fires only when a decision is
  needed) and passes what prefix-matched deny rules miss (`rm -fr` slips past `rm -rf`). Hence the
  opt-in `Force ask despite allowlist`, a `PreToolUse` guard that runs the regex layers before the
  permission rules — the one switch that *adds* prompts. It separates shell text from interpreter
  payloads (heredocs, `-c`): matching shell patterns against a Python heredoc produced only false
  positives. Payloads are checked for process spawning, sockets, deletion and `eval`, with string
  literals stripped first.
- **Command-shape fixes.** Claude Code always prompts on shapes like `cd X && git …`; each has a
  trivial equivalent (`git -C X …`), so the guard blocks with a rewrite instruction and the model
  resends — the user is never asked. Only certain equivalents are gated.
- **The problem was never model size.** When a replacement model was considered, the decision log
  answered first: of 742 gray-zone commands the large model allowed 27%; most asks were `grep`,
  `ps`, `cat`, `ls` glued with pipes. The read layer removed 26% of asks with no model. It needed
  its own quote-aware parser (`grep -E "a|b"` is one member) and follows symlinks with `realpath`;
  it found its first real hole within a minute (`git show HEAD:.env`).
- **An evaluation set first.** `tools/judge-eval/dataset.jsonl` (labels `dangerous` / `safe` /
  `disputed`) runs through the same pipeline as the hook. **The gate is zero false allows on
  `dangerous`**, because `ALLOW` is the only decision with an effect. On the first measurement no
  model passed — false allows were mostly writes that look like reads (`echo x > src/main.py`,
  `sed -i`, `sort -o`, `find -delete`) and git operations that discard work. The prompt forbade
  exactly these and models allowed them anyway, so recognition moved into rules (redirects into the
  repo, in-place edits, `rm`/`mv` of project files, git discarding work or rewriting history, secret
  files, symlinks leaving the project, programs shadowing system tools, hijacking environment
  prefixes, file writes inside interpreter payloads). After that the large model reached zero false
  allows while allowing nearly all safe cases; small local models still do not pass.
- **Fallback model and shadow mode.** A fallback endpoint is asked only when the primary *did not
  answer* — "the model was unsure" and "there is no model" are finally different things. By
  default it runs in **shadow**: it decides nothing, and its verdict is logged so the two can be
  compared on the owner's own commands; `allow` mode is for after a candidate passes the gate. A
  failed primary is skipped for two minutes, or a dead server adds a timeout to every command.
- **Human labels.** A post-execution hook records `executed` when an asked command actually ran,
  so the log finally says what the human decided. An ask without a pair is a refusal *or* an
  interrupted session, and the label extractor keeps them apart. Training an own model is
  deliberately not done yet: distilling from the current log would reproduce an over-cautious
  teacher.
- **The API key is never stored in `config.md`** (it is committed): `env:NAME`, `file:<path>`
  outside the repo, `cmd:<command>`; a literal value is warned about at every start.

Variants: `command` (own script + any OpenAI-compatible endpoint), `rules` (same script, no model),
`none`, and `prompt` / `agent` (Claude Code's built-in judge hooks, where a guard cannot stop
another hook's allow, so there the guard denies instead of asking).

## 15. Quality checks

Every quality mechanism used to depend on the model remembering it: review mode had zero recorded
uses across projects, and "watch for OWASP" works on errors of ignorance, not on reflexes. Meanwhile
a medical project invented red-team tasks on its own — and a red team with mutation, not the
implementation's own tests, found a real authorization hole. It also showed the case nothing
guarded: a debugging aid "to be removed before deployment".

- **Triggered by git operations, not by memory.** A `PreToolUse` hook recognises `git commit`
  (point `commit`), `git tag telesma/phase-*` (`phase`) and a version tag (`release`) inside any Bash
  command; CI runs the same runner with `--point ci`. A blocking finding denies the operation with
  the list; warnings come back as context. Separate from the judge on purpose: the judge only
  removes prompts, checks deliberately add blocks — so they have their own switch, off by default.
- **What a commit is.** At hook time `git add a b && git commit` has not staged anything yet, so the
  commit plan is the index plus the paths of `git add` members of the same command. Without that the
  check would scan an empty index and pass every commit.
- **The command-shape rule.** The hook sees files *before* the command runs. The first live test
  committed a planted key straight through: `printf 'KEY=…' >> config.py && git add config.py &&
  git commit` — the check read the file before `printf` ran (Telesma found and reported the hole
  itself). Before a commit or tag the same command may now contain only `git add/rm/mv/status/diff`,
  `cd` and read-only commands without redirection; anything else is denied with an instruction to
  split the command. Shell wrappers and script aliases are refused; plain aliases are expanded.
- **A check is a module**: `CHECK.md` frontmatter (kind `command | rule | agent`, run/check
  commands, default points, scope, severity) + `run.py` reading paths on stdin and printing findings
  as JSON lines. One handling rule for all of them in section 19, so a new check adds no
  instructions. Config can soften a module's severity, never harden it.
- **Secrets never leave the check** — findings carry rule, file, line and a hash; tests pin it with
  canaries. **Exceptions are the human's**: a false positive is waived by fingerprint in
  `telesma/state/CHECK_EXCEPTIONS.md`, and every write there, to `telesma/checks/` or to `## Checks` asks the
  user — the author of the code cannot close the findings that block it.
- **Weakenings.** `telesma: weakening <id> — <reason>` marks a deliberate hole; the marker *is* the
  register. An incomplete marker or `MUTANT` blocks a commit; an open weakening warns at phase end
  and blocks the release tag; typical unmarked patterns (TLS off, debug, CSRF exemption) warn.
- **Fail-open is explicit.** A timed-out hook lets the operation through, so the runner keeps its
  own budget and reports a check that did not run as "the operation passed without it".
- **Dependencies.** Model-written code invents plausible package names that anyone can register
  (*slopsquatting*). `dependencies` checks only packages new against HEAD: missing from the
  registry, under 7 days old, or a near-typo of a popular package → block; install scripts, git/URL
  dependencies, extra indexes → warn. `dependency-audit` reads every lockfile against OSV at
  phase/release/CI (a vulnerability appears without any change in the project) and blocks only what
  a version bump fixes: critical/high, a fixed version newer than the installed one, production
  dependency. Findings are merged per package (81 lines → 20 on one project). An unreachable
  registry is a warning, never a block.
- **PR status as a local attestation.** Owners wanted the PR to show that checks ran, without paying
  for CI minutes. After `git commit` the runner files the result under the new SHA; after a push to
  a task branch it posts **one commit status** (`Telesma: checks (local)`) on the branch tip — red
  when any commit lacks evidence or a check errored, because absence is not green. Rebase and squash
  change SHAs, so evidence is also matched by `git patch-id`. Honest limit, written into the name:
  this is an attestation from the developer's machine, not verification. The verifiable variant is
  the same runner in CI.
- **Five later checks, chosen by evidence**: `tests` (a green suite with tests quietly switched off
  is worse than a red one; a test modified together with the code it checks warns — that was
  53 of 134 problem-log entries on the reference project), `hygiene` (build dirs, big files, a
  manifest changed without its lockfile), `dead-entry` (the mechanical guard for `AC: entry`; warns
  only, and its first measurement changed the rule — counting only references from other files gave
  146 findings, all false; counting any other line of the own file left one, true), `sast`
  (semgrep or built-in patterns; an aggregated finding's fingerprint covers all hit lines, so a
  waiver on line 12 does not silence a new injection on line 80) and `lint-types` (project linter at
  commit, typechecker at phase, never writing; plus the typographic-quote rule from §12).
- **Attack-surface map, intent and red team.** The other checks read lines of code; they catch an
  injection typed in a hurry, not a *missing* check — and missing authorization was the costliest
  class, every time under green tests ("one doctor could admit another doctor's patient").
  `telesma/state/SECURITY_MAP.md` declares intent: roles with the **guard text in code**, ownership
  boundaries, every route with its roles and ownership, outbound hosts, secrets. The checks never
  learn the auth framework: `_routes.py` extracts each route with its *window* (decorators,
  signature, router dependencies, call arguments, mount-site middleware) and the check is a
  substring test of the map's guard tokens in that window. `intent` blocks a new route without a map
  row and a route whose window lacks the guard of its declared role. `red-team` requires a
  `telesma: red-team <METHOD> <path> — <cases>` test marker for protected routes changed in the phase,
  with cases derived from the map (`no-session`, `foreign-role`, `foreign-owner`, `csrf`). The
  finding text *is* the task, so "blocked → fix" makes Telesma create the red-team task the medical
  project invented on its own. Telesma writes the map without asking (asking on every route would
  stall the loop); the human reviews it in the release proposal, which lists attack-surface changes.
  Pilots shaped the extractor: on one application half the route decorators had the path on the next
  line, so decorators are joined first; on the medical project sub-apps are mounted elsewhere, so
  mounts are followed up to three levels — without that 83 of 235 routes looked unguarded. History
  replay found exactly the change the map exists for: one commit widened a module's access to health
  data from one role to three.

## 16. Frozen benchmark

Telemetry from real projects cannot isolate a framework change: projects keep growing and the
models change. `benchmark/bench.py` holds everything still except the Telesma version: a small spec
(a lending-library REST service on the Python standard library, with system time stored in the
database — no dependencies, no clock), a ready plan and index (clarification depends on a human's
answers, so it is skipped), and four change requests built around the defect classes of §12: a
mechanism triggered by the day change, a new item type that must work in seven places, a rework with
a boundary, and a queue that shows its bugs only with two or more entries. Any edit to those files
changes the benchmark fingerprint and makes results incomparable.

The judge is a hidden HTTP-only test suite Telesma never sees, so it measures what a user would see —
including code that was built, tested and wired to nothing. The judge earns trust first: the
reference implementation must pass everything, and each of five planted faults must be caught.
Reported alongside: Telesma's own test count (the gap between "green at my end" and the outside view
is what is being measured), minutes, tokens, models and how many `AC: entry` lines appeared.

Lessons: one run is an anecdote (compare series of at least three, same model); a run is a real
session on the user's subscription, and the first full run exhausted the session limit halfway, so
the harness recognises that and the default run starts from a frozen post-stage-A state. The first
series scored 100% on every run for both versions — the benchmark is too easy to separate quality.
It did show that the new rules are executed (entry criteria 0 vs 6–11 lines) and cost about four
minutes per stage. A benchmark that measures quality needs requests that state the outcome rather
than the trigger, and calibration to a 60–90% judge score.

## 17. Config validation

The launcher once validated the plan but never read `config.md` as data, so a test command left as
the template placeholder (`[e.g. pytest -v, npm test]`) survived 100 days on the reference project —
the model invents a command when the field is a placeholder, and "green suite" then means whatever
it guessed. Now every `- **Field**: value` is parsed per section: missing or placeholder test
commands are errors that gate an autonomous start; any other placeholder is a warning; no smoke
suite on a large plan is a warning (regressions then surface only at phase end, with no task to
attribute them to). Integration fields, the judge endpoint and key forms are validated the same way.

## 18. Working directories

`## Working directories` declares directories outside the repo that Claude may touch without
prompting (scratchpad, build caches, asset directories). The launcher syncs them into
`permissions.additionalDirectories` — settings entries grant **file access only**, whereas `--add-dir`
would also load `CLAUDE.md`, hooks and skills from that directory. Roots that would disable
protection rather than configure it (`/`, `~`, `/Users`, `/etc`, `/tmp`, …) are rejected. The judge
reads the same section, so `rm -r` passes only inside working directories, never inside the repo.
It also trusts the session scratchpad without configuration: it is the agent's own workspace, and
the "outside the project" rule exists to protect the user's documents, sibling repositories and
system paths — without it the common backup → mutate → restore pattern prompted on every step.

## 19. One directory in the user's project

The pre-release version spread itself over the project root: state and config, guidelines, checks,
`spec/`, `changes/`, `artifacts/` — six top-level entries, three of them with generic names that collide with the project's own (`spec/` is also where RSpec
and many JS projects keep tests, `changes/` and `artifacts/` are common build outputs). A reader of
the repository could not tell what belonged to the product and what to the tool, and removing the
tool meant hunting for its pieces.

Since 1.0 everything Telesma reads or writes lives in `telesma/`: `config.md` and the human's input
(`spec/`, `changes/`) at the top, what the model writes in `state/`, what the clone delivers in
`guidelines/` and `checks/`, screenshots and recordings in `artifacts/`. The directory is visible,
not hidden — the human edits the spec and the config in it. Two things stay outside on purpose:
`.claude/` (Claude Code reads its settings and hooks only from there) and `docs/RUNBOOK.md` +
`docs/test-scenarios/`, which document the *product* — they stay useful if the project stops using
Telesma.

Consequences that keep it cheap: the spec checksum stamp records paths from the project root
(`telesma/spec/…`), so it does not change with the working directory; the check modules find the
project root four levels up from their own file; the checks still skip only `telesma/checks/`
(the state files and the spec are scanned for secrets, as before). The launcher refuses to start on
a project still in the pre-release layout, so no project ever ends up with a mixed one.

## 20. Setup wizard: defaults that work on the first run

The pre-release template shipped with everything optional turned off and, once turned on, turned
on all at once. Both halves hurt. A newcomer who followed the README got the bare loop: every Bash
command prompted, no checks — and the first thing they did about it, `Auto-approve: yes`, ran into
a judge configured for a local model nobody had (`Judge: command`, Ollama on port 11434), so the
start reported a broken judge instead of fewer prompts. Flipping `Checks → Enabled: yes` fired all
eleven modules, including two that need an attack-surface map and three that need network or
tools, and the first commit died under findings the user could not place. The config's comments
explained every key; nobody reads 490 lines of comments before the first run.

Since 1.0 the launcher asks instead of assuming, once, in the order a human can follow:

- **A profile first, then one question per module.** `recommended` is the ENTER answer: judge in
  `rules` mode (no model, so nothing can be misconfigured; provable reads stop prompting,
  everything else still asks) and the `basic` check tier (secrets, weakenings, weakened tests,
  hygiene — no network, no tools, no map, so no finding the user cannot act on). `minimal` is the
  pre-release default; `full` adds the standard tier and the questions about integrations, visual
  artifacts and telemetry.
- **Detection before questions.** The stack comes from manifests (`pyproject.toml`,
  `package.json`, `Cargo.toml`, `go.mod`, …, one level down in a monorepo) and turns into the test,
  lint and typecheck commands the launcher's validator insists on; `git init` is offered when the
  directory is not a repository; the optional tools (`gitleaks`, `semgrep`) are mentioned once, in
  the wizard, instead of as a warning on every start.
- **Tiers are just blocks.** A tier is the set of `### <check>` blocks present under `## Checks`;
  the engine keeps the user's edits inside a block it keeps and takes missing blocks from the
  template; the config merge at startup already respected removed blocks. No new state, no new
  parser, reversible from the `--setup` menu.
- **The engine is separate from the questions.** `templates/setup/configure.py` does every edit
  deterministically and prints one line per change; `wizard.sh` only asks. That is what makes the
  wizard testable without a terminal (`tools/test-setup.py` drives it through a pty) and lets a
  CI run apply the recommended profile silently.
- **The first start shows one template, not three.** `APP_FLOW.md` and `ux_ui/LINKS.md` are inputs
  of the visual-artifacts module and appear when that module is turned on; before, every project
  started with three "unfilled template" markers, two of them irrelevant to most projects.

